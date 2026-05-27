import json
import logging
import os
import requests
from pathlib import Path

from vpn_collector.config import DEFAULT_SOURCES, PROXY_ENV_VARS, SOURCES_FILE
from vpn_collector.parser import parse_configs_from_content, is_vpn_file

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"


def _clean_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def load_sources(sources_file: Path) -> list[dict]:
    if not sources_file.exists():
        save_sources(DEFAULT_SOURCES, sources_file)
        return DEFAULT_SOURCES.copy()
    return json.loads(sources_file.read_text())


def save_sources(sources: list[dict], sources_file: Path) -> None:
    sources_file.write_text(json.dumps(sources, indent=2))


def add_source(url_or_repo: str, sources_file: Path) -> bool:
    sources = load_sources(sources_file)
    stripped = url_or_repo.strip()

    # Normalise Telegram URLs to bare channel name
    tg_value = None
    for prefix in ("https://t.me/", "t.me/"):
        if stripped.startswith(prefix):
            tg_value = stripped[len(prefix):]
            break
    if tg_value is not None:
        if tg_value.startswith("s/"):
            tg_value = tg_value[2:]
        tg_value = tg_value.strip("/")
        if any(s["type"] == "tg" and s["value"] == tg_value for s in sources):
            return False
        sources.append({"type": "tg", "value": tg_value})
        save_sources(sources, sources_file)
        return True

    if any(s["value"] == stripped for s in sources):
        return False
    source_type = "url" if stripped.startswith("http") else "repo"
    sources.append({"type": source_type, "value": stripped})
    save_sources(sources, sources_file)
    return True


def sync_stars(username: str, sources_file: Path) -> int:
    sources = load_sources(sources_file)
    existing_values = {s["value"] for s in sources}
    added = 0
    page = 1
    while True:
        try:
            resp = _clean_session().get(
                f"{GITHUB_API}/users/{username}/starred",
                params={"per_page": 100, "page": page},
                timeout=10,
            )
            repos = resp.json()
            if not repos:
                break
            for repo in repos:
                full_name = repo["full_name"]
                if full_name not in existing_values:
                    sources.append({"type": "repo", "value": full_name})
                    existing_values.add(full_name)
                    added += 1
            page += 1
        except Exception as e:
            logger.warning(f"Failed to fetch stars page {page}: {e}")
            break
    save_sources(sources, sources_file)
    return added


def _is_fetchable(path: str) -> bool:
    """Return True if a repo file path is worth fetching and content-checking."""
    from pathlib import Path as _Path
    from vpn_collector.config import SKIP_EXTENSIONS, SKIP_FILENAMES
    p = _Path(path)
    if p.suffix.lower() in SKIP_EXTENSIONS:
        return False
    name_lower = p.name.lower()
    return not any(name_lower.startswith(s) for s in SKIP_FILENAMES)


def fetch_url_configs(url: str) -> list[str]:
    try:
        resp = _clean_session().get(url, timeout=15)
        return parse_configs_from_content(resp.text)
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return []


def fetch_repo_configs(repo: str) -> list[str]:
    try:
        session = _clean_session()
        resp = session.get(
            f"{GITHUB_API}/repos/{repo}/git/trees/HEAD",
            params={"recursive": "1"},
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning(f"Trees API {resp.status_code} for {repo}")
            return []
        txt_files = [
            item["path"] for item in resp.json().get("tree", [])
            if item["type"] == "blob" and _is_fetchable(item["path"])
        ]
        seen: set[str] = set()
        configs: list[str] = []
        for path in txt_files:
            try:
                raw = session.get(f"{GITHUB_RAW}/{repo}/HEAD/{path}", timeout=10)
                if raw.status_code != 200:
                    continue
                if is_vpn_file(path, raw.text):
                    for c in parse_configs_from_content(raw.text):
                        if c not in seen:
                            seen.add(c)
                            configs.append(c)
            except Exception as e:
                logger.debug(f"Skipped {repo}/{path}: {e}")
        return configs
    except Exception as e:
        logger.warning(f"Failed to process repo {repo}: {e}")
        return []


def fetch_all_configs(sources_file: Path) -> list[str]:
    import asyncio
    from vpn_collector.tg_source import fetch_all_tg_configs

    sources = load_sources(sources_file)
    seen: set[str] = set()
    all_configs: list[str] = []

    for source in sources:
        if source["type"] == "tg":
            continue  # handled separately below
        if source["type"] == "repo":
            configs = fetch_repo_configs(source["value"])
        else:
            configs = fetch_url_configs(source["value"])
        for c in configs:
            if c not in seen:
                seen.add(c)
                all_configs.append(c)

    tg_channels = [s["value"] for s in sources if s["type"] == "tg"]
    if tg_channels:
        tg_configs = asyncio.run(fetch_all_tg_configs(tg_channels))
        for c in tg_configs:
            if c not in seen:
                seen.add(c)
                all_configs.append(c)

    return all_configs
