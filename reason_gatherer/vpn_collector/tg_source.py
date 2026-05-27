import json
import logging
from pathlib import Path

from vpn_collector.config import TG_AUTH_FILE, TG_SESSION_FILE, TG_POSTS_LIMIT
from vpn_collector.parser import parse_configs_from_content

logger = logging.getLogger(__name__)


def load_tg_auth() -> dict | None:
    if not TG_AUTH_FILE.exists():
        return None
    return json.loads(TG_AUTH_FILE.read_text())


def save_tg_auth(api_id: int, api_hash: str) -> None:
    TG_AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    TG_AUTH_FILE.write_text(json.dumps({"api_id": api_id, "api_hash": api_hash}))
    TG_AUTH_FILE.chmod(0o600)


def is_tg_configured() -> bool:
    session_path = Path(str(TG_SESSION_FILE) + ".session")
    return TG_AUTH_FILE.exists() and session_path.exists()


async def fetch_tg_channel_configs(client, channel: str, limit: int) -> list[str]:
    try:
        messages = await client.get_messages(channel, limit=limit)
        configs: list[str] = []
        for msg in messages:
            if msg.text:
                configs.extend(parse_configs_from_content(msg.text))
        return configs
    except Exception as e:
        logger.warning(f"TG channel {channel}: {e}")
        return []


async def fetch_all_tg_configs(channels: list[str], limit: int = TG_POSTS_LIMIT) -> list[str]:
    try:
        from telethon import TelegramClient
    except ImportError:
        logger.error(
            "Telethon not installed. Run: pip install telethon>=1.36"
        )
        return []

    if not is_tg_configured():
        logger.warning("Telegram not configured. Run --setup-tg first.")
        return []

    auth = load_tg_auth()
    if not auth or "api_id" not in auth or "api_hash" not in auth:
        logger.warning("Telegram auth file is malformed. Run --setup-tg first.")
        return []

    if not channels:
        return []

    seen: set[str] = set()
    all_configs: list[str] = []

    async with TelegramClient(str(TG_SESSION_FILE), auth["api_id"], auth["api_hash"]) as client:
        for channel in channels:
            configs = await fetch_tg_channel_configs(client, channel, limit)
            for c in configs:
                if c not in seen:
                    seen.add(c)
                    all_configs.append(c)

    return all_configs
