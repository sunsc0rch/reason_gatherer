import json
import re
import zipfile
from pathlib import Path

from awg_collector.config import RESULTS_AWG_DIR, KNOWN_GOOD_DIR, TOP_N_CONFIGS

# AWG 2.x-only fields not supported by AmneziaWG 1.0.1
_AWG2_FIELDS = re.compile(r"^\s*(S3|I1)\s*=.*\n?", re.MULTILINE | re.IGNORECASE)


def _ensure_dirs() -> None:
    RESULTS_AWG_DIR.mkdir(exist_ok=True)
    KNOWN_GOOD_DIR.mkdir(exist_ok=True)


def strip_awg2_fields(conf_text: str) -> str:
    """Remove S3 and I1 keys — AWG 2.x additions unsupported by AmneziaWG 1.0.1."""
    return _AWG2_FIELDS.sub("", conf_text)


def save_known_good(conf_text: str, endpoint: str) -> Path:
    _ensure_dirs()
    host, _, port = endpoint.rpartition(":")
    path = KNOWN_GOOD_DIR / f"{host}_{port}.conf"
    path.write_text(strip_awg2_fields(conf_text))
    return path


def load_known_good() -> list[dict]:
    if not KNOWN_GOOD_DIR.exists():
        return []
    results = []
    for path in sorted(KNOWN_GOOD_DIR.glob("*.conf")):
        text = path.read_text(errors="replace")
        stem = path.stem
        last = stem.rfind("_")
        if last == -1:
            continue
        endpoint = stem[:last] + ":" + stem[last + 1:]
        results.append({"text": text, "endpoint": endpoint, "filename": path.name})
    return results


def remove_known_good(endpoint: str) -> None:
    host, _, port = endpoint.rpartition(":")
    path = KNOWN_GOOD_DIR / f"{host}_{port}.conf"
    path.unlink(missing_ok=True)


def build_vpn_archive(meta: dict | None = None) -> Path:
    """Build all_configs.zip with top TOP_N_CONFIGS entries sorted by speed.

    If meta is provided, configs are sorted by meta[endpoint]['speed'] descending
    and only the fastest TOP_N_CONFIGS are included. Without meta, all known_good
    configs are included unsorted.
    """
    _ensure_dirs()
    archive_path = RESULTS_AWG_DIR / "all_configs.zip"
    configs = load_known_good()
    if meta is not None:
        configs.sort(key=lambda c: meta.get(c["endpoint"], {}).get("speed", 0), reverse=True)
        configs = configs[:TOP_N_CONFIGS]
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for cfg in configs:
            zf.writestr(cfg["filename"], cfg["text"])
    return archive_path


def load_config_meta() -> dict:
    meta_file = RESULTS_AWG_DIR / "config_meta.json"
    if not meta_file.exists():
        return {}
    try:
        return json.loads(meta_file.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_config_meta(meta: dict) -> None:
    _ensure_dirs()
    (RESULTS_AWG_DIR / "config_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False)
    )


def update_meta_entry(meta: dict, endpoint: str, today: str, speed: float) -> None:
    if endpoint not in meta:
        meta[endpoint] = {"first_seen": today, "fail_streak": 0}
    meta[endpoint]["speed"] = speed


def save_candidates(configs: list[dict]) -> None:
    _ensure_dirs()
    text = "\n\n".join(cfg["text"] for cfg in configs)
    (RESULTS_AWG_DIR / "candidates.conf").write_text(text)


def load_candidates() -> list[str]:
    path = RESULTS_AWG_DIR / "candidates.conf"
    if not path.exists():
        return []
    blocks = re.split(r"(?=^\[Interface\])", path.read_text(errors="replace"), flags=re.MULTILINE)
    return [b.strip() for b in blocks if b.strip() and "[Interface]" in b]
