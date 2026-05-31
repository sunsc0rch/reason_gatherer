import asyncio
import base64
import json
import logging
import os
import random
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

import requests

from vpn_collector.config import (
    TCP_TIMEOUT, TCP_CONCURRENCY, PROXY_ENV_VARS, SINGBOX_SEARCH_PATHS,
    MIN_SPEED_MBPS, SPEEDTEST_URLS, CLAUDE_CHECK_URL,
    CLAUDE_BLOCK_URL_KEYWORDS,
    SINGBOX_STARTUP_TIMEOUT, TUNNEL_CONCURRENCY, SOCKS_PORT_RANGE,
    SPEEDTEST_EARLY_ABORT_FACTOR, SPEEDTEST_EARLY_ABORT_AFTER,
)
from vpn_collector.parser import extract_host_port, extract_name, set_name

logger = logging.getLogger(__name__)


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
    if net == "ws":
        outbound["transport"] = {
            "type": "ws",
            "path": data.get("path", "/"),
            "headers": {"Host": data.get("host", data["add"])},
        }
    elif net == "grpc":
        outbound["transport"] = {"type": "grpc", "service_name": data.get("path", "")}
    return outbound


def _parse_trojan(line: str) -> dict:
    p = urlparse(line)
    params = parse_qs(p.query)
    sni = params.get("sni", [p.hostname])[0]
    return {
        "type": "trojan",
        "tag": "proxy",
        "server": p.hostname,
        "server_port": p.port,
        "password": unquote(p.username or ""),
        "tls": {"enabled": True, "server_name": sni, "insecure": True},
    }


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


def generate_singbox_config(config_line: str, socks_port: int) -> dict:
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


def speedtest_via_socks(socks_port: int) -> float:
    abort_threshold = MIN_SPEED_MBPS * SPEEDTEST_EARLY_ABORT_FACTOR
    with _socks_session(socks_port) as session:
        for url in SPEEDTEST_URLS:
            try:
                start = time.time()
                resp = session.get(url, stream=True, timeout=15)
                downloaded = 0
                for chunk in resp.iter_content(chunk_size=65536):
                    downloaded += len(chunk)
                    elapsed = time.time() - start
                    if elapsed >= SPEEDTEST_EARLY_ABORT_AFTER:
                        current_mbps = (downloaded * 8) / (elapsed * 1_000_000)
                        if current_mbps < abort_threshold:
                            return current_mbps
                    if downloaded >= 1024 * 1024:
                        break
                elapsed = time.time() - start
                return (downloaded * 8) / (elapsed * 1_000_000) if elapsed > 0 else 0.0
            except Exception:
                continue
    return 0.0


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


_fail_counts: dict[str, int] = {
    "parse_error": 0,
    "no_port": 0,
    "proc_dead": 0,
    "too_slow": 0,
    "pass": 0,
}


def test_config_tunnel(
    config_line: str, singbox_path: str, socks_port: int
) -> str | None:
    clean_env = {k: v for k, v in os.environ.items() if k not in PROXY_ENV_VARS}
    try:
        cfg = generate_singbox_config(config_line, socks_port)
    except Exception as e:
        logger.debug(f"Config generation failed: {e}")
        _fail_counts["parse_error"] += 1
        return None

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        json.dump(cfg, tmp)
        cfg_path = tmp.name

    proc = None
    try:
        proc = subprocess.Popen(
            [singbox_path, "run", "-c", cfg_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=clean_env,
        )
        if not _wait_for_socks_port(socks_port, SINGBOX_STARTUP_TIMEOUT):
            _fail_counts["no_port"] += 1
            return None
        if proc.poll() is not None:
            _fail_counts["proc_dead"] += 1
            return None
        speed = speedtest_via_socks(socks_port)
        if speed < MIN_SPEED_MBPS:
            _fail_counts["too_slow"] += 1
            logger.debug(f"Too slow: {speed:.2f} Mbps — {config_line[:60]}")
            return None
        _fail_counts["pass"] += 1
        marker = check_claude_via_socks(socks_port)
        return set_name(config_line, f"{marker}{extract_name(config_line)}")
    except Exception as e:
        logger.debug(f"Tunnel test error: {e}")
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
) -> list[str]:
    total = len(candidates)
    done = 0
    passed_count = 0
    semaphore = asyncio.Semaphore(concurrency)
    used_ports: set[int] = set()

    logger.info(f"Tunnel test: {total} candidates, concurrency={concurrency}")

    def get_port() -> int:
        while True:
            p = random.randint(*SOCKS_PORT_RANGE)
            if p not in used_ports:
                used_ports.add(p)
                return p

    async def test_one(config: str) -> str | None:
        nonlocal done, passed_count
        async with semaphore:
            port = get_port()
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, test_config_tunnel, config, singbox_path, port
            )
            used_ports.discard(port)  # sing-box is dead by now; port is free to reuse
        done += 1
        if result:
            passed_count += 1
            if on_pass:
                on_pass(result)  # called in event loop — no threading issues
        if done % log_every == 0 or done == total:
            fc = _fail_counts
            logger.info(
                f"Tunnel test: {done}/{total} tested | {passed_count} passed | "
                f"parse={fc['parse_error']} no_port={fc['no_port']} "
                f"proc_dead={fc['proc_dead']} too_slow={fc['too_slow']}"
            )
        return result

    results = await asyncio.gather(*[test_one(c) for c in candidates])
    return [r for r in results if r is not None]
