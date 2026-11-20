import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote

import requests

from vpn_collector.config import (
    DEFAULT_SOURCES, SOURCES_FILE, SUBSCRIPTION_REPO_FETCH_CONCURRENCY,
)
from vpn_collector.parser import parse_configs_from_content, is_vpn_file

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"
GITHUB_API_MIN_INTERVAL_SECONDS = 1.0
GITHUB_STAR_SYNC_INTERVAL_SECONDS = 24 * 60 * 60
GITHUB_PRIMARY_LIMIT_RETRIES = 1
GITHUB_SECONDARY_LIMIT_RETRIES = 5


_use_proxy = False  # learned for the lifetime of the process once direct access fails
_github_api_request_lock = threading.Lock()
_last_github_api_request_at = 0.0


class GitHubRateLimitError(RuntimeError):
    """Raised when the GitHub API remains rate-limited after scheduled retries."""


def _github_cache_dir() -> Path:
    configured = os.environ.get("VPN_COLLECTOR_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()

    cache_home = os.environ.get("XDG_CACHE_HOME")
    root = Path(cache_home).expanduser() if cache_home else Path.home() / ".cache"
    return root / "vpn_collector" / "github"


def _cache_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
        temporary_path.replace(path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _atomic_write_json(path: Path, payload: dict) -> None:
    _atomic_write_text(path, json.dumps(payload, separators=(",", ":")))


def _read_json_cache(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _get_api_request_delay() -> float:
    raw = os.environ.get("VPN_COLLECTOR_GITHUB_API_DELAY_SECONDS")
    if raw is None:
        return GITHUB_API_MIN_INTERVAL_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning(
            "Invalid VPN_COLLECTOR_GITHUB_API_DELAY_SECONDS=%r; using %.1fs",
            raw, GITHUB_API_MIN_INTERVAL_SECONDS,
        )
        return GITHUB_API_MIN_INTERVAL_SECONDS


def _pace_github_api_request() -> None:
    global _last_github_api_request_at
    with _github_api_request_lock:
        delay = _get_api_request_delay()
        remaining = delay - (time.monotonic() - _last_github_api_request_at)
        if remaining > 0:
            time.sleep(remaining)
        _last_github_api_request_at = time.monotonic()


def _clean_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def _github_headers() -> dict:
    """Authorization header for api.github.com calls only — never attach this
    to raw.githubusercontent.com or arbitrary source URLs, or the token leaks
    to whatever host those point at."""
    token = os.environ.get("GITHUB_TOKEN")
    return {"Authorization": f"token {token}"} if token else {}


def _safe_github_detail(value: object, limit: int = 400) -> str:
    """Make a short, single-line response detail safe for collector logs."""
    text = str(value)
    text = "".join(char for char in text if char.isprintable() or char.isspace())
    text = re.sub(r"<[^>]*>", " ", text)
    text = " ".join(text.split())
    # GitHub's rate-limit message can include the caller's public IP.
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<ip>", text)
    return text[:limit]


def _github_error_payload(resp: requests.Response) -> dict:
    try:
        payload = resp.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _log_github_api_error(resp: requests.Response, operation: str) -> None:
    """Log response metadata useful for distinguishing limits from access blocks.

    Never log the Authorization value; only record whether the request carried
    an authorization header.
    """
    headers = resp.headers
    request = getattr(resp, "request", None)
    request_headers = getattr(request, "headers", {}) or {}
    auth_mode = "token-header" if request_headers.get("Authorization") else "anonymous"
    details = [
        f"status={resp.status_code}",
        f"auth={auth_mode}",
        f"rate_limit={headers.get('X-RateLimit-Limit', '-')}",
        f"rate_remaining={headers.get('X-RateLimit-Remaining', '-')}",
        f"rate_reset={headers.get('X-RateLimit-Reset', '-')}",
        f"rate_resource={headers.get('X-RateLimit-Resource', '-')}",
        f"retry_after={headers.get('Retry-After', '-')}",
        f"request_id={headers.get('X-GitHub-Request-Id', '-')}",
        f"content_type={headers.get('Content-Type', '-')}",
    ]

    payload = _github_error_payload(resp)
    if payload.get("message"):
        details.append(f"message={_safe_github_detail(payload['message'])!r}")
        if payload.get("errors"):
            details.append(f"errors={_safe_github_detail(json.dumps(payload['errors']))!r}")
    else:
        body = _safe_github_detail(resp.text)
        if body:
            details.append(f"body={body!r}")

    logger.warning("GitHub API %s: %s", operation, " ".join(details))


def _is_github_rate_limited(resp: requests.Response) -> bool:
    if resp.status_code not in (403, 429):
        return False
    if resp.headers.get("X-RateLimit-Remaining") == "0":
        return True
    if resp.headers.get("Retry-After"):
        return True
    message = str(_github_error_payload(resp).get("message", "")).lower()
    return "rate limit" in message


def _github_retry_delay(resp: requests.Response, retry_number: int) -> float:
    delays: list[float] = []
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            delays.append(max(1.0, float(retry_after)))
        except ValueError:
            pass

    if resp.headers.get("X-RateLimit-Remaining") == "0":
        try:
            reset_at = int(resp.headers["X-RateLimit-Reset"])
            delays.append(max(1.0, reset_at - time.time() + 1.0))
        except (KeyError, TypeError, ValueError):
            pass

    if delays:
        return max(delays)
    return min(60.0 * (2 ** retry_number), 15 * 60.0)


def _github_api_request(
    session: requests.Session,
    method: str,
    url: str,
    *,
    operation: str,
    **kwargs,
) -> requests.Response:
    primary_waits = 0
    secondary_waits = 0

    while True:
        _pace_github_api_request()
        resp = _request(session, method, url, **kwargs)
        if resp.status_code in (200, 304):
            return resp

        _log_github_api_error(resp, operation)
        if not _is_github_rate_limited(resp):
            return resp

        is_primary_limit = resp.headers.get("X-RateLimit-Remaining") == "0"
        if is_primary_limit:
            if primary_waits >= GITHUB_PRIMARY_LIMIT_RETRIES:
                raise GitHubRateLimitError(
                    f"GitHub primary rate limit remained exhausted after waiting: {operation}"
                )
            retry_number = primary_waits
            primary_waits += 1
            limit_kind = "primary"
        else:
            if secondary_waits >= GITHUB_SECONDARY_LIMIT_RETRIES:
                raise GitHubRateLimitError(
                    f"GitHub secondary rate limit remained active after retries: {operation}"
                )
            retry_number = secondary_waits
            secondary_waits += 1
            limit_kind = "secondary"

        delay = _github_retry_delay(resp, retry_number)
        logger.warning(
            "GitHub %s rate limit for %s; pausing %.0f seconds before retry %d",
            limit_kind, operation, delay,
            primary_waits if is_primary_limit else secondary_waits,
        )
        time.sleep(delay)


def _stars_sync_cache_path(username: str, sources_file: Path) -> Path:
    identity = f"{username}\0{sources_file.resolve()}"
    return _github_cache_dir() / "stars" / f"{_cache_key(identity)}.json"


def _stars_sync_interval() -> float:
    raw = os.environ.get("VPN_COLLECTOR_STAR_SYNC_INTERVAL_SECONDS")
    if raw is None:
        return float(GITHUB_STAR_SYNC_INTERVAL_SECONDS)
    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning(
            "Invalid VPN_COLLECTOR_STAR_SYNC_INTERVAL_SECONDS=%r; using 24 hours",
            raw,
        )
        return float(GITHUB_STAR_SYNC_INTERVAL_SECONDS)


def _tree_cache_path(repo: str) -> Path:
    return _github_cache_dir() / "trees" / f"{_cache_key(repo.lower())}.json"


def _fetch_repo_tree(
    session: requests.Session,
    repo: str,
    operation: str,
) -> list[dict] | None:
    cache_path = _tree_cache_path(repo)
    cache = _read_json_cache(cache_path)
    cached_tree = cache.get("tree") if cache else None
    headers = _github_headers()
    etag = cache.get("etag") if cache else None
    if isinstance(etag, str) and etag:
        headers["If-None-Match"] = etag

    url = f"{GITHUB_API}/repos/{repo}/git/trees/HEAD"
    request_args = {"params": {"recursive": "1"}, "timeout": 15}
    resp = _github_api_request(
        session, "GET", url, operation=operation, headers=headers, **request_args
    )

    if resp.status_code == 304:
        if isinstance(cached_tree, list):
            logger.info("GitHub tree unchanged for %s; using ETag cache", repo)
            return cached_tree
        logger.warning("GitHub returned 304 for %s without a usable tree cache; retrying", repo)
        headers.pop("If-None-Match", None)
        resp = _github_api_request(
            session, "GET", url, operation=f"{operation} cache-miss retry",
            headers=headers, **request_args,
        )

    if resp.status_code != 200:
        return None

    payload = resp.json()
    tree = payload.get("tree") if isinstance(payload, dict) else None
    if not isinstance(tree, list):
        logger.warning("GitHub returned an invalid tree payload for %s", repo)
        return None

    if payload.get("truncated"):
        logger.warning(
            "GitHub returned a truncated recursive tree for %s; some files may be missing",
            repo,
        )
    else:
        response_etag = resp.headers.get("ETag")
        if isinstance(response_etag, str) and response_etag:
            try:
                _atomic_write_json(cache_path, {"etag": response_etag, "tree": tree})
            except OSError as e:
                logger.warning("Could not save GitHub tree cache for %s: %s", repo, e)

    return tree


def _blob_cache_path(sha: object) -> Path | None:
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", sha):
        return None
    normalized = sha.lower()
    return _github_cache_dir() / "blobs" / normalized[:2] / f"{normalized}.txt"


def _fetch_repo_blob(
    session: requests.Session,
    repo: str,
    item: dict,
    timeout: float,
) -> str | None:
    path = item.get("path")
    if not isinstance(path, str) or not path:
        return None

    cache_path = _blob_cache_path(item.get("sha"))
    if cache_path and cache_path.is_file():
        try:
            return cache_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.debug("Could not read cached GitHub blob %s: %s", item.get("sha"), e)

    url = f"{GITHUB_RAW}/{repo}/HEAD/{quote(path, safe='/')}"
    max_attempts = 4
    for attempt in range(max_attempts):
        try:
            resp = _request(session, "GET", url, timeout=timeout)
        except requests.RequestException as e:
            if attempt + 1 == max_attempts:
                logger.warning("Unable to fetch GitHub raw file %s/%s: %s", repo, path, e)
                return None
            delay = min(2 ** attempt, 8)
            logger.warning(
                "GitHub raw request failed for %s/%s; retrying in %ds (%d/%d)",
                repo, path, delay, attempt + 1, max_attempts - 1,
            )
            time.sleep(delay)
            continue

        if resp.status_code == 200:
            content = resp.text
            if cache_path:
                try:
                    _atomic_write_text(cache_path, content)
                except OSError as e:
                    logger.warning("Could not save GitHub blob cache for %s/%s: %s", repo, path, e)
            return content

        retryable = resp.status_code in (429, 502, 503, 504)
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            retryable = True
        if not retryable or attempt + 1 == max_attempts:
            logger.warning(
                "GitHub raw file %s/%s returned HTTP %s after %d attempt(s)",
                repo, path, resp.status_code, attempt + 1,
            )
            return None

        retry_after = resp.headers.get("Retry-After")
        try:
            delay = max(1, int(retry_after)) if retry_after else min(2 ** (attempt + 1), 16)
        except ValueError:
            delay = min(2 ** (attempt + 1), 16)
        logger.warning(
            "GitHub raw file %s/%s returned HTTP %s; retrying in %ds (%d/%d)",
            repo, path, resp.status_code, delay, attempt + 1, max_attempts - 1,
        )
        time.sleep(delay)

    return None


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
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
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


def sync_stars(username: str, sources_file: Path, force: bool = False) -> int:
    sources = load_sources(sources_file)
    auth_mode = "token configured" if os.environ.get("GITHUB_TOKEN") else "anonymous"
    logger.info("GitHub API auth mode: %s", auth_mode)
    sync_cache_path = _stars_sync_cache_path(username, sources_file)
    sync_cache = _read_json_cache(sync_cache_path)
    last_success = sync_cache.get("last_success") if sync_cache else None
    if not force and isinstance(last_success, (int, float)):
        elapsed = time.time() - last_success
        interval = _stars_sync_interval()
        if 0 <= elapsed < interval:
            remaining = interval - elapsed
            logger.info(
                "Skipping starred-repo sync; last complete sync was %.1f hours ago "
                "(next refresh in %.1f hours)",
                elapsed / 3600, remaining / 3600,
            )
            return 0

    existing_values = {s["value"] for s in sources}
    added = 0
    page = 1
    complete = False
    while True:
        try:
            resp = _github_api_request(
                _clean_session(), "GET",
                f"{GITHUB_API}/users/{username}/starred",
                operation=f"starred repos page {page} for {username}",
                params={"per_page": 100, "page": page},
                timeout=10, headers=_github_headers(),
            )
            if resp.status_code != 200:
                break
            repos = resp.json()
            if not repos:
                complete = True
                break
            if not isinstance(repos, list):
                logger.warning("Unexpected GitHub response for starred repos page %d", page)
                break
            for repo in repos:
                full_name = repo["full_name"]
                if full_name not in existing_values:
                    sources.append({"type": "repo", "value": full_name})
                    existing_values.add(full_name)
                    added += 1
            page += 1
        except GitHubRateLimitError:
            raise
        except Exception as e:
            logger.warning(f"Failed to fetch stars page {page}: {e}")
            break
    save_sources(sources, sources_file)
    if complete:
        try:
            _atomic_write_json(sync_cache_path, {"last_success": time.time()})
        except OSError as e:
            logger.warning("Could not save GitHub starred-repo sync time: %s", e)
    else:
        logger.warning("Starred-repo sync did not finish; it will be retried on the next run")
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
        resp = _request(_clean_session(), "GET", url, timeout=15)
        return parse_configs_from_content(resp.text)
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return []


def fetch_url_text(url: str) -> str | None:
    """Fetch a successful HTTP response body, or return None for failed URLs."""
    try:
        resp = _request(_clean_session(), "GET", url, timeout=15)
        if resp.status_code != 200:
            logger.debug(f"URL {url} returned HTTP {resp.status_code}")
            return None
        return resp.text
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None


def _is_text_source_path(path: str) -> bool:
    """Keep docs and files whose names suggest links, providers, or sources."""
    from pathlib import PurePosixPath

    file_path = PurePosixPath(path)
    suffix = file_path.suffix.lower()
    name = file_path.name.lower()
    if suffix in {".md", ".html", ".rst"} or name.startswith("readme"):
        return True
    if suffix not in {".txt", ".yaml", ".yml", ".json", ".conf", ".list", ".sub", ".toml"}:
        return False
    hints = ("sub", "source", "url", "link", "provider", "index", "config")
    return any(hint in file_path.stem.lower() for hint in hints)


def fetch_repo_texts(repo: str) -> list[str]:
    """Fetch likely text files from a GitHub repo for link discovery."""
    try:
        session = _clean_session()
        tree = _fetch_repo_tree(session, repo, f"Trees API for {repo}")
        if tree is None:
            return []

        items = [
            item for item in tree
            if isinstance(item, dict)
            and item.get("type") == "blob"
            and _is_text_source_path(str(item.get("path", "")))
        ]
        logger.info("Subscription discovery: fetching %d text files from %s", len(items), repo)

        def fetch_text(item: dict) -> str | None:
            try:
                with _clean_session() as file_session:
                    return _fetch_repo_blob(file_session, repo, item, timeout=10)
            except Exception as e:
                logger.debug("Skipped %s/%s: %s", repo, item.get("path", "?"), e)

        from concurrent.futures import ThreadPoolExecutor
        texts: list[str] = []
        with ThreadPoolExecutor(max_workers=SUBSCRIPTION_REPO_FETCH_CONCURRENCY) as executor:
            for index, text in enumerate(executor.map(fetch_text, items), 1):
                if text:
                    texts.append(text)
                if index % 100 == 0 or index == len(items):
                    logger.info(
                        "Subscription discovery: %s files %d/%d fetched",
                        repo, index, len(items),
                    )
        return texts
    except GitHubRateLimitError:
        raise
    except Exception as e:
        logger.warning(f"Failed to retrieve text from repo {repo}: {e}")
        return []


def fetch_source_texts(sources_file: Path) -> list[str]:
    """Fetch source bodies for the independent subscription discovery mode."""
    import asyncio
    from vpn_collector.tg_source import fetch_all_tg_texts

    sources = load_sources(sources_file)
    texts: list[str] = []
    channels: list[str] = []
    for source in sources:
        if source["type"] == "tg":
            channels.append(source["value"])
        elif source["type"] == "repo":
            texts.extend(fetch_repo_texts(source["value"]))
        else:
            text = fetch_url_text(source["value"])
            if text:
                texts.append(text)

    if channels:
        texts.extend(asyncio.run(fetch_all_tg_texts(channels)))
    return texts


def fetch_repo_configs(repo: str) -> list[str]:
    try:
        session = _clean_session()
        tree = _fetch_repo_tree(session, repo, f"Trees API for {repo}")
        if tree is None:
            return []
        txt_files = [
            item for item in tree
            if isinstance(item, dict)
            and item.get("type") == "blob"
            and _is_fetchable(str(item.get("path", "")))
        ]
        seen: set[str] = set()
        configs: list[str] = []
        for item in txt_files:
            path = str(item.get("path", ""))
            try:
                content = _fetch_repo_blob(session, repo, item, timeout=10)
                if content is None:
                    continue
                if is_vpn_file(path, content):
                    for c in parse_configs_from_content(content):
                        if c not in seen:
                            seen.add(c)
                            configs.append(c)
            except Exception as e:
                logger.debug(f"Skipped {repo}/{path}: {e}")
        return configs
    except GitHubRateLimitError:
        raise
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
        try:
            tg_configs = asyncio.run(fetch_all_tg_configs(tg_channels))
        except Exception as e:
            logger.warning("Telegram source failed; skipping Telegram and continuing: %s", e)
            tg_configs = []
        for c in tg_configs:
            if c not in seen:
                seen.add(c)
                all_configs.append(c)

    return all_configs
