import asyncio
import base64
import json
import logging
import os
import random
import re
import socket
import subprocess
import threading
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse, parse_qs, unquote

import requests

from vpn_collector.config import (
    TCP_TIMEOUT, TCP_CONCURRENCY, PROXY_ENV_VARS, SINGBOX_SEARCH_PATHS,
    MIN_SPEED_MBPS, SPEEDTEST_URLS, CLAUDE_CHECK_URL,
    CLAUDE_BLOCK_URL_KEYWORDS,
    SINGBOX_STARTUP_TIMEOUT, TUNNEL_CONCURRENCY, SOCKS_PORT_RANGE,
    SPEEDTEST_EARLY_ABORT_FACTOR, SPEEDTEST_EARLY_ABORT_AFTER,
    BLACKHOLE_TTLS, PING_TIMEOUT,
)
from vpn_collector.parser import extract_host_port, extract_name, set_name

logger = logging.getLogger(__name__)


class UnsupportedTransportError(ValueError):
    """Raised when the installed sing-box engine cannot implement a share transport."""


@dataclass(frozen=True)
class SpeedTestResult:
    speed_mbps: float | None
    error: str | None = None


class FailureDiagnostics:
    """Thread-safe per-tunnel-run counters with one safe example per category."""

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.examples: dict[str, str] = {}
        self._lock = threading.Lock()

    def record(self, category: str, detail: str = "") -> None:
        with self._lock:
            self.counts[category] += 1
            if detail and category not in self.examples:
                detail = re.sub(r"https?://\S+", "<url>", detail)
                self.examples[category] = detail[:180]

    def snapshot(self) -> tuple[dict[str, int], dict[str, str]]:
        with self._lock:
            return dict(self.counts), dict(self.examples)


def classify_singbox_failure(log_text: str) -> str:
    text = log_text.lower()
    if any(token in text for token in (
        "failed to verify certificate", "certificate has expired",
        "certificate is valid for", "x509:",
    )):
        return "tls_certificate"
    if "unexpected http response status" in text:
        return "transport_handshake"
    if "reality verification failed" in text:
        return "reality_handshake"
    if any(token in text for token in (
        "no such host", "server misbehaving", "temporary failure in name resolution",
        "nxdomain",
    )):
        return "dns_error"
    if any(token in text for token in (
        "connection refused", "network is unreachable", "i/o timeout",
        "connection reset by peer", "no route to host",
    )):
        return "proxy_connect_error"
    return "singbox_error" if log_text.strip() else "probe_error"


async def tcp_check(host: str, port: int, timeout: float = TCP_TIMEOUT) -> bool:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def _ping_once(host: str, ttl: int, timeout: float = PING_TIMEOUT) -> str:
    """Run one TTL-capped ping and classify the answer.

    Returns:
      "reply"  — the destination itself answered ICMP (route + host alive).
      "hop"    — an intermediate router answered (Time-to-live-exceeded or
                 ICMP unreachable): the packet cleared the ISP drop point,
                 so the destination is NOT blackholed by the ISP.
      "silent" — no ICMP at all within `timeout`, i.e. the packet was
                 swallowed somewhere before the first answering hop.
      "error"  — ping itself failed (binary missing, bad name, no route).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", "1", "-W", "1", "-t", str(ttl), host,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except (FileNotFoundError, PermissionError, OSError):
        return "error"
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout + 2.0)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return "silent"
    text = out.decode(errors="replace")
    if "bytes from" in text:
        return "reply"
    if "Time to live exceeded" in text or "Unreachable" in text:
        return "hop"
    if "Unknown host" in text or "Name or service not known" in text:
        return "error"
    return "silent"


async def blackhole_probe(
    host: str,
    ttls: tuple[int, ...] = BLACKHOLE_TTLS,
) -> bool | None:
    """Tell an ISP destination-IP block apart from a dead host.

    True  — blackholed: no ICMP at any capped TTL (packet dies inside the
            access network, before the first hop that would answer).
    False — packets reach the destination's network (target or a router
            answered); the host is simply down or its port is closed.
    None  — inconclusive (ping unavailable or the name does not resolve).

    Calibrated on AS60095: a live-but-ICMP-silent host still yields a hop
    reply at TTL 5, while a blackholed IP stays silent at TTL 5/8/12.
    """
    saw_error = False
    for ttl in ttls:
        result = await _ping_once(host, ttl)
        if result in ("reply", "hop"):
            return False
        if result == "error":
            saw_error = True
    return None if saw_error else True


async def classify_endpoint(host: str, port: int, timeout: float = TCP_TIMEOUT) -> str:
    """Endpoint verdict: "alive", "blocked_by_isp", "server_dead" or "unknown"."""
    if await tcp_check(host, port, timeout):
        return "alive"
    blackholed = await blackhole_probe(host)
    if blackholed is True:
        return "blocked_by_isp"
    if blackholed is False:
        return "server_dead"
    return "unknown"


async def classify_endpoints(
    endpoints: list[tuple],
    concurrency: int = TCP_CONCURRENCY,
    timeout: float = TCP_TIMEOUT,
) -> dict[tuple, str]:
    """Classify every host:port (typically the ones that failed tcp_check)."""
    semaphore = asyncio.Semaphore(min(concurrency, 32))  # ping probes are cheap but bounded

    async def one(hp: tuple) -> tuple[tuple, str]:
        async with semaphore:
            return hp, await classify_endpoint(hp[0], hp[1], timeout)

    results = await asyncio.gather(*[one(hp) for hp in endpoints])
    return dict(results)


async def tcp_filter(
    configs: list[str],
    concurrency: int = TCP_CONCURRENCY,
    timeout: float = TCP_TIMEOUT,
) -> list[str]:
    # Group all configs by host:port — check each endpoint once, keep all passing configs.
    by_endpoint: dict[tuple, list[str]] = {}
    for config in configs:
        hp = extract_host_port(config)
        if hp:
            by_endpoint.setdefault(hp, []).append(config)

    unique_endpoints = list(by_endpoint.keys())
    semaphore = asyncio.Semaphore(concurrency)

    async def check_endpoint(hp: tuple) -> tuple | None:
        async with semaphore:
            return hp if await tcp_check(hp[0], hp[1], timeout) else None

    results = await asyncio.gather(*[check_endpoint(hp) for hp in unique_endpoints])
    passing = {hp for hp in results if hp is not None}

    return [cfg for hp, cfgs in by_endpoint.items() if hp in passing for cfg in cfgs]


def find_singbox() -> str | None:
    for search_path in SINGBOX_SEARCH_PATHS:
        for name in ("sing-box", "singbox"):
            candidate = Path(search_path) / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None


def _singbox_wrapper(socks_port: int, outbound: dict) -> dict:
    return {
        "log": {"level": "error"},
        "inbounds": [{
            "type": "socks",
            "tag": "socks-in",
            "listen": "127.0.0.1",
            "listen_port": socks_port,
        }],
        "outbounds": [outbound],
    }


def _parse_vless(line: str) -> dict:
    p = urlparse(line)
    params = parse_qs(p.query)
    security = params.get("security", ["none"])[0]
    sni = params.get("sni", params.get("host", [p.hostname]))[0]
    transport_type = params.get("type", ["tcp"])[0]
    if transport_type == "xhttp":
        raise UnsupportedTransportError(
            "xhttp is not supported by upstream sing-box; use an XHTTP-capable core"
        )
    outbound: dict = {
        "type": "vless",
        "tag": "proxy",
        "server": p.hostname,
        "server_port": p.port,
        "uuid": p.username,
        "flow": params.get("flow", [""])[0],
    }
    if security in ("tls", "reality", "xtls"):
        outbound["tls"] = {
            "enabled": True,
            "server_name": sni,
            "insecure": True,
            "utls": {"enabled": True, "fingerprint": "chrome"},
        }
        if security == "reality":
            outbound["tls"]["reality"] = {
                "enabled": True,
                "public_key": params.get("pbk", [""])[0],
                "short_id": params.get("sid", [""])[0],
            }
    if transport_type == "ws":
        outbound["transport"] = {
            "type": "ws",
            "path": params.get("path", ["/"])[0],
            "headers": {"Host": params.get("host", [sni])[0]},
        }
    elif transport_type == "grpc":
        outbound["transport"] = {
            "type": "grpc",
            "service_name": params.get("serviceName", [""])[0],
        }
    elif transport_type == "httpupgrade":
        outbound["transport"] = {
            "type": "httpupgrade",
            "host": params.get("host", [""])[0],
            "path": params.get("path", [""])[0],
        }
    elif transport_type == "http":
        outbound["transport"] = {
            "type": "http",
            "host": [params["host"][0]] if params.get("host", [""])[0] else [],
            "path": params.get("path", [""])[0],
        }
    return outbound


def _parse_vmess(line: str) -> dict:
    _b64 = line[8:]
    payload = base64.b64decode(_b64 + "=" * (-len(_b64) % 4)).decode("utf-8", errors="replace")
    data = json.loads(payload)
    outbound: dict = {
        "type": "vmess",
        "tag": "proxy",
        "server": data["add"],
        "server_port": int(data.get("port", 443)),
        "uuid": data["id"],
        "security": data.get("scy", "auto") or "auto",
        "alter_id": int(data.get("aid", 0)),
    }
    if str(data.get("tls", "")).lower() == "tls":
        outbound["tls"] = {
            "enabled": True,
            "server_name": data.get("sni") or data.get("host") or data["add"],
            "insecure": True,
        }
    net = data.get("net", "tcp")
    if net == "xhttp":
        raise UnsupportedTransportError(
            "xhttp is not supported by upstream sing-box; use an XHTTP-capable core"
        )
    if net == "ws":
        outbound["transport"] = {
            "type": "ws",
            "path": data.get("path", "/"),
            "headers": {"Host": data.get("host", data["add"])},
        }
    elif net == "grpc":
        outbound["transport"] = {"type": "grpc", "service_name": data.get("path", "")}
    elif net == "httpupgrade":
        outbound["transport"] = {
            "type": "httpupgrade",
            "host": data.get("host", ""),
            "path": data.get("path", ""),
        }
    elif net == "http":
        host = data.get("host", "")
        outbound["transport"] = {
            "type": "http",
            "host": [host] if host else [],
            "path": data.get("path", ""),
        }
    return outbound


def _parse_trojan(line: str) -> dict:
    p = urlparse(line)
    params = parse_qs(p.query)
    sni = params.get("sni", [p.hostname])[0]
    outbound = {
        "type": "trojan",
        "tag": "proxy",
        "server": p.hostname,
        "server_port": p.port,
        "password": unquote(p.username or ""),
        "tls": {"enabled": True, "server_name": sni, "insecure": True},
    }
    transport_type = params.get("type", ["tcp"])[0]
    if transport_type == "xhttp":
        raise UnsupportedTransportError(
            "xhttp is not supported by upstream sing-box; use an XHTTP-capable core"
        )
    if transport_type == "httpupgrade":
        outbound["transport"] = {
            "type": "httpupgrade",
            "host": params.get("host", [""])[0],
            "path": params.get("path", [""])[0],
        }
    elif transport_type == "ws":
        outbound["transport"] = {
            "type": "ws",
            "path": params.get("path", ["/"])[0],
            "headers": {"Host": params.get("host", [sni])[0]},
        }
    elif transport_type == "grpc":
        outbound["transport"] = {
            "type": "grpc",
            "service_name": params.get("serviceName", [""])[0],
        }
    return outbound


def _parse_ss(line: str) -> dict:
    p = urlparse(line)
    if p.username and p.password and p.hostname and p.port:
        method = unquote(p.username)
        password = unquote(p.password)
        host, port = p.hostname, p.port
    else:
        userinfo_host = line[5:]
        at_pos = userinfo_host.rfind("@")
        userinfo = userinfo_host[:at_pos]
        hostport = userinfo_host[at_pos + 1:]
        try:
            decoded = base64.b64decode(userinfo + "==").decode()
        except Exception:
            decoded = userinfo
        method, password = (decoded.split(":", 1) + [""])[:2]
        host, port_str = hostport.rsplit(":", 1)
        port = int(port_str)
    return {
        "type": "shadowsocks",
        "tag": "proxy",
        "server": host,
        "server_port": port,
        "method": method,
        "password": password,
    }


def _parse_hy2(line: str) -> dict:
    p = urlparse(line)
    params = parse_qs(p.query)
    sni = params.get("sni", [p.hostname])[0]
    password = unquote(p.username or "") or unquote(p.password or "")
    return {
        "type": "hysteria2",
        "tag": "proxy",
        "server": p.hostname,
        "server_port": p.port,
        "password": password,
        "tls": {"enabled": True, "server_name": sni, "insecure": True},
    }


def _parse_tuic(line: str) -> dict:
    p = urlparse(line)
    params = parse_qs(p.query)
    sni = params.get("sni", [p.hostname])[0]
    return {
        "type": "tuic",
        "tag": "proxy",
        "server": p.hostname,
        "server_port": p.port,
        "uuid": unquote(p.username or ""),
        "password": unquote(p.password or ""),
        "congestion_control": params.get("congestion_control", ["bbr"])[0],
        "tls": {"enabled": True, "server_name": sni, "insecure": True},
    }


def _parse_socks(line: str) -> dict:
    p = urlparse(line)
    username = ""
    password = ""
    # userinfo is base64(user:pass) per the socks:// share-link convention;
    # plain user:pass URLs would be silently mis-decoded here.
    if p.username:
        try:
            decoded = base64.b64decode(p.username + "==").decode("utf-8", errors="replace")
            if ":" in decoded:
                username, password = decoded.split(":", 1)
            else:
                username = decoded
        except Exception:
            username = unquote(p.username)
            password = unquote(p.password or "")
    return {
        "type": "socks",
        "tag": "proxy",
        "server": p.hostname,
        "server_port": p.port,
        "username": username,
        "password": password,
        "version": "5",
    }


def generate_singbox_config(
    config_line: str, socks_port: int, verify_tls_cert: bool = False
) -> dict:
    line = config_line.strip().split("#")[0]
    if line.startswith("vless://"):
        outbound = _parse_vless(line)
    elif line.startswith("vmess://"):
        outbound = _parse_vmess(line)
    elif line.startswith("trojan://"):
        outbound = _parse_trojan(line)
    elif line.startswith("ss://"):
        outbound = _parse_ss(line)
    elif line.startswith(("hysteria2://", "hy2://")):
        outbound = _parse_hy2(line)
    elif line.startswith("hysteria://"):
        outbound = _parse_hy2(line)
    elif line.startswith("tuic://"):
        outbound = _parse_tuic(line)
    elif line.startswith("socks://"):
        outbound = _parse_socks(line)
    else:
        raise ValueError(f"Unsupported protocol: {line[:20]}")
    if verify_tls_cert and "tls" in outbound:
        # sing-box validates certificates by default; existing collector modes
        # keep their historical insecure setting unless strict mode is asked for.
        outbound["tls"].pop("insecure", None)
    return _singbox_wrapper(socks_port, outbound)


def _wait_for_socks_port(port: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def _socks_session(socks_port: int) -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.proxies = {
        "http": f"socks5h://127.0.0.1:{socks_port}",
        "https": f"socks5h://127.0.0.1:{socks_port}",
    }
    return session


def speedtest_via_socks_detailed(socks_port: int) -> SpeedTestResult:
    abort_threshold = MIN_SPEED_MBPS * SPEEDTEST_EARLY_ABORT_FACTOR
    best_speed: float | None = None
    errors: list[str] = []
    with _socks_session(socks_port) as session:
        for url in SPEEDTEST_URLS:
            try:
                start = time.time()
                with session.get(url, stream=True, timeout=15) as resp:
                    status = getattr(resp, "status_code", 200)
                    if status >= 400:
                        errors.append(f"HTTP {status} from speed-test endpoint")
                        continue
                    downloaded = 0
                    for chunk in resp.iter_content(chunk_size=65536):
                        downloaded += len(chunk)
                        elapsed = time.time() - start
                        if elapsed >= SPEEDTEST_EARLY_ABORT_AFTER:
                            current_mbps = (downloaded * 8) / (elapsed * 1_000_000)
                            if current_mbps < abort_threshold:
                                break
                        if downloaded >= 1024 * 1024:
                            break
                elapsed = time.time() - start
                if downloaded <= 0:
                    errors.append("empty response from speed-test endpoint")
                    continue
                speed = (downloaded * 8) / (elapsed * 1_000_000) if elapsed > 0 else 0.0
                best_speed = speed if best_speed is None else max(best_speed, speed)
                if speed >= MIN_SPEED_MBPS:
                    return SpeedTestResult(speed)
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
                continue
    if best_speed is not None:
        return SpeedTestResult(best_speed)
    return SpeedTestResult(None, "; ".join(errors[-3:]) or "no speed-test response")


def speedtest_via_socks(socks_port: int) -> float:
    """Compatibility wrapper returning zero when no speed measurement was possible."""
    result = speedtest_via_socks_detailed(socks_port)
    return result.speed_mbps or 0.0


def check_claude_via_socks(socks_port: int) -> str:
    try:
        with _socks_session(socks_port) as session:
            resp = session.get(CLAUDE_CHECK_URL, timeout=20, allow_redirects=True)
            if resp.status_code == 451:
                return "---"
            if any(kw in resp.url.lower() for kw in CLAUDE_BLOCK_URL_KEYWORDS):
                return "---"
            if resp.status_code >= 400:
                return "---"
            return "+++"
    except Exception as e:
        logger.debug(f"Claude check failed: {type(e).__name__}: {e}")
        return "---"


def _read_singbox_errors(log_file) -> str:
    log_file.flush()
    log_file.seek(0)
    text = log_file.read()
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    error_lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " | ".join(error_lines[-3:])


def test_config_tunnel(
    config_line: str, singbox_path: str, socks_port: int,
    verify_tls_cert: bool = False,
    on_failure: Callable[[str, str], None] | None = None,
) -> str | None:
    def fail(category: str, detail: str = "") -> None:
        if on_failure:
            on_failure(category, detail)

    clean_env = {k: v for k, v in os.environ.items() if k not in PROXY_ENV_VARS}
    try:
        cfg = generate_singbox_config(config_line, socks_port, verify_tls_cert)
    except UnsupportedTransportError as e:
        fail("unsupported_transport", str(e))
        return None
    except Exception as e:
        fail("config_error", f"{type(e).__name__}: {e}")
        return None

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        json.dump(cfg, tmp)
        cfg_path = tmp.name

    proc = None
    try:
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stderr_log:
            try:
                proc = subprocess.Popen(
                    [singbox_path, "run", "-c", cfg_path],
                    stdout=subprocess.DEVNULL,
                    stderr=stderr_log,
                    env=clean_env,
                )
            except Exception as e:
                fail("singbox_start_error", f"{type(e).__name__}: {e}")
                return None
            if not _wait_for_socks_port(socks_port, SINGBOX_STARTUP_TIMEOUT):
                details = _read_singbox_errors(stderr_log)
                category = classify_singbox_failure(details)
                if category == "probe_error":
                    category = "singbox_start_timeout"
                elif category == "singbox_error":
                    category = "singbox_start_error"
                fail(category, details)
                return None
            if proc.poll() is not None:
                details = _read_singbox_errors(stderr_log)
                category = classify_singbox_failure(details)
                fail("singbox_exit" if category == "probe_error" else category, details)
                return None
            probe = speedtest_via_socks_detailed(socks_port)
            if probe.speed_mbps is None:
                details = _read_singbox_errors(stderr_log)
                category = classify_singbox_failure(details)
                if category == "probe_error":
                    category = "probe_error"
                    details = probe.error or "no speed-test response"
                fail(category, details)
                return None
            if probe.speed_mbps < MIN_SPEED_MBPS:
                fail("too_slow", f"measured {probe.speed_mbps:.2f} Mbps")
                return None
            marker = check_claude_via_socks(socks_port)
            return set_name(config_line, f"{marker}{extract_name(config_line)}")
    except Exception as e:
        fail("tunnel_test_error", f"{type(e).__name__}: {e}")
        return None
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            os.unlink(cfg_path)
        except Exception:
            pass


async def tunnel_filter(
    candidates: list[str],
    singbox_path: str,
    concurrency: int = TUNNEL_CONCURRENCY,
    log_every: int = 10,
    on_pass: callable = None,
    verify_tls_cert: bool = False,
) -> list[str]:
    total = len(candidates)
    done = 0
    passed_count = 0
    semaphore = asyncio.Semaphore(concurrency)
    used_ports: set[int] = set()
    diagnostics = FailureDiagnostics()

    logger.info(f"Tunnel test: {total} candidates, concurrency={concurrency}")

    def get_port() -> int:
        while True:
            p = random.randint(*SOCKS_PORT_RANGE)
            if p not in used_ports:
                used_ports.add(p)
                return p

    async def test_one(config: str, executor: "concurrent.futures.ThreadPoolExecutor") -> str | None:
        nonlocal done, passed_count
        async with semaphore:
            port = get_port()
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                executor, test_config_tunnel, config, singbox_path, port,
                verify_tls_cert, diagnostics.record,
            )
            used_ports.discard(port)  # sing-box is dead by now; port is free to reuse
        done += 1
        if result:
            passed_count += 1
            if on_pass:
                on_pass(result)  # called in event loop — no threading issues
        if done % log_every == 0 or done == total:
            fc, _ = diagnostics.snapshot()
            summary = ", ".join(f"{name}={count}" for name, count in sorted(fc.items()))
            logger.info(
                f"Tunnel test: {done}/{total} tested | {passed_count} passed | "
                f"failures: {summary or 'none'}"
            )
        return result

    # loop.run_in_executor(None, ...) would use asyncio's default executor,
    # which caps at min(32, cpu_count+4) threads — silently capping real
    # concurrency below `concurrency` on any machine with <28 cores, no
    # matter how high TUNNEL_CONCURRENCY is set. Size our own explicitly.
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        results = await asyncio.gather(*[test_one(c, executor) for c in candidates])
    _, examples = diagnostics.snapshot()
    for category, example in sorted(examples.items()):
        logger.info("Tunnel failure example [%s]: %s", category, example)
    return [r for r in results if r is not None]
