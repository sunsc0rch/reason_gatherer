import base64
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

from vpn_collector.config import VPN_PREFIXES, SKIP_FILENAMES, SKIP_EXTENSIONS


def is_vpn_line(line: str) -> bool:
    return any(line.strip().startswith(p) for p in VPN_PREFIXES)


def extract_host_port(line: str) -> tuple[str, int] | None:
    line = line.strip().split("#")[0]
    try:
        if line.startswith("vmess://"):
            payload = base64.b64decode(line[8:] + "==").decode("utf-8", errors="replace")
            data = json.loads(payload)
            return str(data["add"]), int(data["port"])
        parsed = urlparse(line)
        if parsed.hostname and parsed.port:
            return parsed.hostname, parsed.port
    except Exception:
        pass
    return None


def extract_name(line: str) -> str:
    if "#" in line:
        return unquote(line.split("#", 1)[1])
    return ""


def set_name(line: str, name: str) -> str:
    base = line.split("#")[0]
    return f"{base}#{name}"


def parse_configs_from_content(content: str) -> list[str]:
    content = content.strip()
    if not content:
        return []
    from vpn_collector.clash_parser import is_clash_yaml, parse_clash_yaml
    if is_clash_yaml(content):
        clash = parse_clash_yaml(content)
        if clash:
            return clash
    lines = _extract_lines(content)
    seen: set[str] = set()
    result = []
    for line in lines:
        line = line.strip()
        if is_vpn_line(line) and line not in seen:
            seen.add(line)
            result.append(line)
    return result


def _extract_lines(content: str) -> list[str]:
    lines = content.splitlines()
    if any(is_vpn_line(l.strip()) for l in lines):
        return lines
    try:
        padding = "=" * (4 - len(content) % 4) if len(content) % 4 else ""
        decoded = base64.b64decode(content + padding).decode("utf-8", errors="replace")
        decoded_lines = decoded.splitlines()
        if any(is_vpn_line(l.strip()) for l in decoded_lines):
            return decoded_lines
    except Exception:
        pass
    return lines


def is_vpn_file(filename: str, content: str) -> bool:
    path = Path(filename)
    name_lower = path.name.lower()
    if path.suffix.lower() in SKIP_EXTENSIONS:
        return False
    for skip in SKIP_FILENAMES:
        if name_lower.startswith(skip):
            return False
    return len(parse_configs_from_content(content)) >= 3
