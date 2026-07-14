import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from awg_collector.config import TG_AUTH_FILE, TG_SESSION_FILE, TG_POSTS_LIMIT
from awg_collector.parser import parse_awg_configs

logger = logging.getLogger(__name__)


def _telethon_proxy() -> tuple | None:
    for var in ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy"):
        val = os.environ.get(var, "").strip()
        if not val:
            continue
        try:
            import socks as _socks
            p = urlparse(val)
            scheme = p.scheme.lower().rstrip("h")
            proxy_types = {"socks5": _socks.SOCKS5, "socks4": _socks.SOCKS4, "http": _socks.HTTP}
            proxy_type = proxy_types.get(scheme)
            if proxy_type is None:
                continue
            port = p.port or (1080 if "socks" in scheme else 8080)
            return (proxy_type, p.hostname, port)
        except Exception:
            pass
    return None


def load_tg_auth() -> dict | None:
    if not TG_AUTH_FILE.exists():
        return None
    return json.loads(TG_AUTH_FILE.read_text())


def is_tg_configured() -> bool:
    session_path = Path(str(TG_SESSION_FILE) + ".session")
    return TG_AUTH_FILE.exists() and session_path.exists()


async def fetch_tg_channel_configs(client, channel: str, limit: int) -> list[dict]:
    try:
        messages = await client.get_messages(channel, limit=limit)
        configs: list[dict] = []
        for msg in messages:
            if not msg:
                continue
            # Текстовые блоки в теле сообщения
            if msg.text and "[Interface]" in msg.text:
                configs.extend(parse_awg_configs(msg.text))
            # Вложения .conf
            if msg.document:
                name = next(
                    (getattr(a, "file_name", None) for a in (msg.document.attributes or []) if getattr(a, "file_name", None)),
                    ""
                )
                if name.endswith(".conf"):
                    try:
                        data = await client.download_media(msg.document, bytes)
                        if data:
                            configs.extend(parse_awg_configs(data.decode("utf-8", errors="replace")))
                    except Exception as e:
                        logger.debug(f"Failed to download attachment from {channel}: {e}")
        return configs
    except Exception as e:
        logger.warning(f"TG channel {channel} error: {e}")
        return []
