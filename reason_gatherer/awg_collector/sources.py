import json
import logging
from pathlib import Path

import requests

from awg_collector.config import (
    GITHUB_API, GITHUB_RAW, TG_POSTS_LIMIT,
)
from awg_collector.parser import parse_awg_configs

logger = logging.getLogger(__name__)


def _clean_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def load_sources(sources_file: Path) -> list[dict]:
    if not sources_file.exists():
        return []
    return json.loads(sources_file.read_text())


def save_sources(sources: list[dict], sources_file: Path) -> None:
    sources_file.write_text(json.dumps(sources, indent=2))


def add_source(url_or_repo: str, sources_file: Path) -> bool:
    sources = load_sources(sources_file)
    stripped = url_or_repo.strip()

    tg_value = None
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if stripped.startswith(prefix):
            remainder = stripped[len(prefix):]
            # strip optional "s/" prefix (t.me/s/channel form)
            if remainder.startswith("s/"):
                remainder = remainder[2:]
            tg_value = remainder.strip("/")
            break

    if tg_value is not None:
        if any(s["type"] == "tg" and s["value"] == tg_value for s in sources):
            return False
        sources.append({"type": "tg", "value": tg_value})
        save_sources(sources, sources_file)
        return True

    if any(s["value"] == stripped for s in sources):
        return False

    source_type = "url" if stripped.startswith("http") else "github"
    sources.append({"type": source_type, "value": stripped})
    save_sources(sources, sources_file)
    return True


def fetch_all_configs(sources_file: Path) -> list[dict]:
    sources = load_sources(sources_file)
    seen_endpoints: set[str] = set()
    all_configs: list[dict] = []

    for source in sources:
        try:
            if source["type"] == "url":
                raw = _fetch_url(source["value"])
                parsed = parse_awg_configs(raw)
            elif source["type"] == "github":
                parsed = _fetch_github_repo(source["value"])
            elif source["type"] == "tg":
                parsed = _fetch_tg_channel(source["value"])
            else:
                continue
        except Exception as e:
            logger.warning(f"Source {source['value']} failed: {e}")
            continue

        for cfg in parsed:
            if not cfg["is_awg"]:
                continue
            ep = cfg["endpoint"]
            if ep not in seen_endpoints:
                seen_endpoints.add(ep)
                all_configs.append(cfg)

    return all_configs


def _fetch_url(url: str, timeout: int = 20) -> str:
    import io, zipfile
    session = _clean_session()
    r = session.get(url, timeout=timeout)
    r.raise_for_status()
    content_type = r.headers.get("Content-Type", "")
    # Unpack ZIP archives (e.g. .vpn or .zip URLs)
    if url.endswith((".zip", ".vpn")) or "zip" in content_type:
        parts = []
        try:
            with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                for name in zf.namelist():
                    if name.endswith(".conf"):
                        parts.append(zf.read(name).decode("utf-8", errors="replace"))
        except zipfile.BadZipFile:
            pass
        return "\n".join(parts)
    return r.text


def _fetch_github_repo(repo: str) -> list[dict]:
    session = _clean_session()
    # Get default branch
    try:
        r = session.get(f"{GITHUB_API}/repos/{repo}", timeout=10)
        r.raise_for_status()
        branch = r.json().get("default_branch", "main")
    except Exception:
        branch = "main"

    # Get file tree
    try:
        r = session.get(
            f"{GITHUB_API}/repos/{repo}/git/trees/{branch}?recursive=1",
            timeout=15,
        )
        r.raise_for_status()
        tree = r.json().get("tree", [])
    except Exception as e:
        logger.warning(f"GitHub tree for {repo}: {e}")
        return []

    configs: list[dict] = []
    for item in tree:
        path = item.get("path", "")
        if not path.endswith(".conf"):
            continue
        try:
            raw_url = f"{GITHUB_RAW}/{repo}/{branch}/{path}"
            text = _fetch_url(raw_url)
            configs.extend(parse_awg_configs(text))
        except Exception as e:
            logger.debug(f"GitHub file {path}: {e}")

    return configs


def _fetch_tg_channel(channel: str) -> list[dict]:
    from awg_collector.tg_source import is_tg_configured, load_tg_auth, fetch_tg_channel_configs
    if not is_tg_configured():
        logger.info(f"TG not configured, skipping channel {channel}")
        return []
    try:
        import asyncio
        from telethon import TelegramClient
        from awg_collector.config import TG_SESSION_FILE
        from awg_collector.tg_source import _telethon_proxy

        auth = load_tg_auth()
        if not auth:
            return []

        async def _run():
            proxy = _telethon_proxy()
            async with TelegramClient(str(TG_SESSION_FILE), auth["api_id"], auth["api_hash"], proxy=proxy) as client:
                return await fetch_tg_channel_configs(client, channel, TG_POSTS_LIMIT)

        return asyncio.run(_run())
    except Exception as e:
        logger.warning(f"TG channel {channel}: {e}")
        return []
