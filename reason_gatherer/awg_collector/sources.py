import json
import logging
import os
from pathlib import Path

import requests

from awg_collector.config import (
    GITHUB_API, GITHUB_RAW, TG_POSTS_LIMIT,
)
from awg_collector.parser import parse_awg_configs

logger = logging.getLogger(__name__)

_use_proxy = False  # learned for the lifetime of the process once direct access fails


def _clean_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def _proxies_from_env() -> dict | None:
    http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or http_proxy
    if not http_proxy and not https_proxy:
        return None
    return {"http": http_proxy, "https": https_proxy}


def _call_with_hard_timeout(session: requests.Session, method: str, url: str,
                             hard_timeout: float, **kwargs) -> requests.Response:
    """Run session.request on a daemon thread and enforce hard_timeout no matter what.

    A stalled local HTTP proxy can accept the TCP connection instantly (visible
    as ESTABLISHED) and then never respond to the CONNECT tunnel — observed to
    hang a run for 30+ minutes despite `timeout=` being passed to requests.
    The worker thread is daemonized so an eventually-abandoned socket never
    blocks process exit.
    """
    import threading
    import concurrent.futures

    fut: concurrent.futures.Future = concurrent.futures.Future()

    def _worker() -> None:
        try:
            result = session.request(method, url, **kwargs)
        except Exception as e:
            fut.set_exception(e)
        else:
            try:
                fut.set_result(result)
            except concurrent.futures.InvalidStateError:
                pass

    threading.Thread(target=_worker, daemon=True).start()
    try:
        return fut.result(timeout=hard_timeout)
    except concurrent.futures.TimeoutError:
        raise requests.exceptions.Timeout(f"{url} exceeded hard timeout of {hard_timeout}s")


def _request(session: requests.Session, method: str, url: str, **kwargs) -> requests.Response:
    """Try a direct request first; fall back to the system proxy if direct access is blocked.

    Once direct access is found to fail, subsequent calls in this process go
    straight through the proxy — avoids re-paying the ~11s dead-network
    timeout on every request for the rest of the run.
    """
    global _use_proxy
    proxies = _proxies_from_env()
    hard_timeout = kwargs.get("timeout", 15) + 8

    if _use_proxy and proxies:
        return _call_with_hard_timeout(session, method, url, hard_timeout, proxies=proxies, **kwargs)

    try:
        resp = _call_with_hard_timeout(session, method, url, hard_timeout, **kwargs)
        if resp.status_code not in (502, 503, 504):
            return resp
    except requests.RequestException:
        resp = None

    if not proxies:
        if resp is not None:
            return resp
        raise requests.RequestException(f"direct request to {url} failed and no proxy is configured")

    logger.warning(f"Direct access to {url} failed, retrying via system proxy")
    _use_proxy = True
    return _call_with_hard_timeout(session, method, url, hard_timeout, proxies=proxies, **kwargs)


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
    r = _request(session, "GET", url, timeout=timeout)
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
        r = _request(session, "GET", f"{GITHUB_API}/repos/{repo}", timeout=10)
        r.raise_for_status()
        branch = r.json().get("default_branch", "main")
    except Exception:
        branch = "main"

    # Get file tree
    try:
        r = _request(
            session, "GET",
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
