import base64
import json
import logging
from urllib.parse import quote

logger = logging.getLogger(__name__)


def _ss_url(p: dict) -> str | None:
    server, port = p.get("server"), p.get("port")
    cipher, password = p.get("cipher", ""), p.get("password", "")
    if not (server and port and cipher and password):
        return None
    userinfo = base64.b64encode(f"{cipher}:{password}".encode()).decode().rstrip("=")
    return f"ss://{userinfo}@{server}:{port}#{p.get('name', '')}"


def _trojan_url(p: dict) -> str | None:
    server, port = p.get("server"), p.get("port")
    password = p.get("password", "")
    if not (server and port and password):
        return None
    sni = p.get("sni") or p.get("servername") or server
    network = p.get("network", "tcp")
    params = [f"sni={quote(str(sni))}"]
    if network == "ws":
        ws = p.get("ws-opts", {})
        params += [
            "type=ws",
            f"path={quote(ws.get('path', '/'), safe='/')}",
            f"host={quote(ws.get('headers', {}).get('Host', str(sni)))}",
        ]
    else:
        params.append("type=tcp")
    return f"trojan://{quote(str(password), safe='')}@{server}:{port}?{'&'.join(params)}#{p.get('name', '')}"


def _vmess_url(p: dict) -> str | None:
    server, port, uuid = p.get("server"), p.get("port"), p.get("uuid")
    if not (server and port and uuid):
        return None
    network = p.get("network", "tcp")
    tls = p.get("tls", False)
    sni = p.get("servername") or p.get("sni") or (str(server) if tls else "")
    path = host = ""
    if network == "ws":
        ws = p.get("ws-opts", {})
        path = ws.get("path", "/")
        host = ws.get("headers", {}).get("Host", sni)
    elif network == "grpc":
        path = p.get("grpc-opts", {}).get("grpc-service-name", "")
    elif network == "http":
        http = p.get("http-opts", {})
        paths = http.get("path", ["/"])
        path = paths[0] if paths else "/"
        raw_host = http.get("headers", {}).get("Host", "")
        host = raw_host[0] if isinstance(raw_host, list) else raw_host
    data = {
        "v": "2", "ps": p.get("name", ""),
        "add": server, "port": str(port),
        "id": uuid,
        "aid": str(p.get("alterId", 0)),
        "scy": p.get("cipher", "auto") or "auto",
        "net": network, "type": "none",
        "host": host, "path": path,
        "tls": "tls" if tls else "",
        "sni": sni, "alpn": "",
    }
    encoded = base64.b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()
    return f"vmess://{encoded}"


def _vless_url(p: dict) -> str | None:
    server, port, uuid = p.get("server"), p.get("port"), p.get("uuid")
    if not (server and port and uuid):
        return None
    network = p.get("network", "tcp")
    tls = p.get("tls", False)
    sni = p.get("servername") or p.get("sni") or ""
    fp = p.get("client-fingerprint", "")
    flow = p.get("flow", "")
    reality = p.get("reality-opts", {})
    params = [f"type={network}", "encryption=none"]
    if reality:
        params.append("security=reality")
        if reality.get("public-key"):
            params.append(f"pbk={reality['public-key']}")
        if reality.get("short-id"):
            params.append(f"sid={reality['short-id']}")
    elif tls:
        params.append("security=tls")
    if sni:
        params.append(f"sni={quote(str(sni))}")
    if fp:
        params.append(f"fp={fp}")
    if flow:
        params.append(f"flow={flow}")
    if network == "ws":
        ws = p.get("ws-opts", {})
        params.append(f"path={quote(ws.get('path', '/'), safe='/')}")
        host = ws.get("headers", {}).get("Host", str(sni))
        if host:
            params.append(f"host={quote(str(host))}")
    elif network == "grpc":
        svc = p.get("grpc-opts", {}).get("grpc-service-name", "")
        if svc:
            params.append(f"serviceName={svc}")
    return f"vless://{uuid}@{server}:{port}?{'&'.join(params)}#{p.get('name', '')}"


def _hysteria2_url(p: dict) -> str | None:
    server, port = p.get("server"), p.get("port")
    password = p.get("password") or p.get("auth")
    if not (server and port and password):
        return None
    sni = p.get("sni", "")
    params = []
    if sni:
        params.append(f"sni={quote(str(sni))}")
    if p.get("skip-cert-verify"):
        params.append("insecure=1")
    qs = ("?" + "&".join(params)) if params else ""
    return f"hysteria2://{quote(str(password), safe='')}@{server}:{port}{qs}#{p.get('name', '')}"


def _hysteria_url(p: dict) -> str | None:
    server, port = p.get("server"), p.get("port")
    if not (server and port):
        return None
    auth = p.get("auth-str") or p.get("auth", "")
    sni = p.get("sni", "")
    params = []
    if auth:
        params.append(f"auth={quote(str(auth), safe='')}")
    if sni:
        params.append(f"sni={quote(str(sni))}")
    params.append(f"protocol={p.get('protocol', 'udp')}")
    if p.get("skip-cert-verify"):
        params.append("insecure=1")
    return f"hysteria://{server}:{port}?{'&'.join(params)}#{p.get('name', '')}"


def _tuic_url(p: dict) -> str | None:
    server, port, uuid = p.get("server"), p.get("port"), p.get("uuid")
    if not (server and port and uuid):
        return None
    password = p.get("password", "")
    sni = p.get("sni", "")
    congestion = p.get("congestion-controller", "bbr")
    params = [f"congestion_control={congestion}"]
    if sni:
        params.append(f"sni={quote(str(sni))}")
    return f"tuic://{uuid}:{quote(str(password), safe='')}@{server}:{port}?{'&'.join(params)}#{p.get('name', '')}"


def _socks5_url(p: dict) -> str | None:
    server, port = p.get("server"), p.get("port")
    if not (server and port):
        return None
    username = p.get("username", "")
    password = p.get("password", "")
    name = p.get("name", "")
    if username:
        userinfo = base64.b64encode(f"{username}:{password}".encode()).decode().rstrip("=")
        return f"socks://{userinfo}@{server}:{port}#{name}"
    return f"socks://@{server}:{port}#{name}"


_CONVERTERS = {
    "ss": _ss_url,
    "trojan": _trojan_url,
    "vmess": _vmess_url,
    "vless": _vless_url,
    "hysteria2": _hysteria2_url,
    "hysteria": _hysteria_url,
    "tuic": _tuic_url,
    "socks5": _socks5_url,
}


def is_clash_yaml(content: str) -> bool:
    """Quick check: does this content look like a Clash YAML with proxies?"""
    head = content.lstrip()[:300]
    return "proxies:" in head


def parse_clash_yaml(content: str) -> list[str]:
    """Parse Clash YAML and return VPN URL strings for all supported proxy types."""
    try:
        import yaml
    except ImportError:
        logger.warning("pyyaml not installed — cannot parse Clash configs. Run: pip install pyyaml")
        return []
    try:
        data = yaml.safe_load(content)
    except Exception as e:
        logger.debug(f"YAML parse error: {e}")
        return []
    if not isinstance(data, dict):
        return []
    proxies = data.get("proxies") or data.get("Proxies")
    if not proxies:
        return []
    result = []
    for proxy in proxies:
        if not isinstance(proxy, dict):
            continue
        ptype = proxy.get("type", "").lower()
        converter = _CONVERTERS.get(ptype)
        if converter is None:
            continue
        try:
            url = converter(proxy)
            if url:
                result.append(url)
        except Exception as e:
            logger.debug(f"Clash proxy convert failed ({ptype}): {e}")
    return result
