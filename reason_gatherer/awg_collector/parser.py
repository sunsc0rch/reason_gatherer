import re
from pathlib import Path

AWG_FIELDS = {"Jc", "Jmin", "Jmax", "S1", "S2", "H1", "H2", "H3", "H4"}
REQUIRED_FIELDS = {"PrivateKey", "PublicKey", "Endpoint"}


def parse_awg_configs(text: str) -> list[dict]:
    blocks = re.split(r'(?=^\[Interface\])', text, flags=re.MULTILINE)
    configs = []
    for block in blocks:
        block = block.strip()
        if not block or "[Interface]" not in block:
            continue
        result = _parse_single(block)
        if result is not None:
            configs.append(result)
    return configs


def parse_awg_file(path: Path) -> list[dict]:
    try:
        return parse_awg_configs(path.read_text(errors="replace"))
    except OSError:
        return []


def _parse_single(text: str) -> dict | None:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            fields[key.strip()] = value.strip()

    if not REQUIRED_FIELDS.issubset(fields):
        return None

    endpoint = fields.get("Endpoint", "")
    if not _valid_endpoint(endpoint):
        return None

    is_awg = bool(AWG_FIELDS & set(fields))

    host, _, port = endpoint.rpartition(":")
    filename = f"{host}_{port}.conf"

    return {
        "text": text,
        "endpoint": endpoint,
        "filename": filename,
        "is_awg": is_awg,
    }


def _valid_endpoint(endpoint: str) -> bool:
    if not endpoint:
        return False
    host, _, port = endpoint.rpartition(":")
    if not host or not port:
        return False
    try:
        p = int(port)
        return 1 <= p <= 65535
    except ValueError:
        return False
