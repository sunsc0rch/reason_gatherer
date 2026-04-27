import asyncio
import base64
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

from vpn_collector.config import TCP_TIMEOUT, TCP_CONCURRENCY, PROXY_ENV_VARS, SINGBOX_SEARCH_PATHS
from vpn_collector.parser import extract_host_port

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
    semaphore = asyncio.Semaphore(concurrency)

    async def check_one(config: str) -> str | None:
        hp = extract_host_port(config)
        if not hp:
            return None
        async with semaphore:
            return config if await tcp_check(hp[0], hp[1], timeout) else None

    results = await asyncio.gather(*[check_one(c) for c in configs])
    return [r for r in results if r is not None]


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
    payload = base64.b64decode(line[8:] + "==").decode("utf-8", errors="replace")
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
    if p.username and p.hostname and p.port:
        method = unquote(p.username)
        password = unquote(p.password or "")
        host, port = p.hostname, p.port
    else:
        userinfo_host = line[5:].split("#")[0]
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
    else:
        raise ValueError(f"Unsupported protocol: {line[:20]}")
    return _singbox_wrapper(socks_port, outbound)
