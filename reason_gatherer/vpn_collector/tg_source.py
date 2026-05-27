import json
import logging
from pathlib import Path

from vpn_collector.config import TG_AUTH_FILE, TG_SESSION_FILE

logger = logging.getLogger(__name__)


def load_tg_auth() -> dict | None:
    if not TG_AUTH_FILE.exists():
        return None
    return json.loads(TG_AUTH_FILE.read_text())


def save_tg_auth(api_id: int, api_hash: str) -> None:
    TG_AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    TG_AUTH_FILE.write_text(json.dumps({"api_id": api_id, "api_hash": api_hash}))


def is_tg_configured() -> bool:
    session_path = Path(str(TG_SESSION_FILE) + ".session")
    return TG_AUTH_FILE.exists() and session_path.exists()
