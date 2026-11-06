"""Discover and validate third-party subscription URLs in configured sources."""

import asyncio
import logging
import re
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from vpn_collector.config import (
    SUBSCRIPTION_MAX_NODES, SUBSCRIPTION_MAX_URLS,
    SUBSCRIPTION_NODE_BATCH_SIZE,
)
from vpn_collector.parser import parse_configs_from_content
from vpn_collector.sources import fetch_url_text
from vpn_collector.tester import tunnel_filter

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:!?\"'`]>}"
_NON_SUBSCRIPTION_HOSTS = {
    "t.me", "telegram.me", "img.shields.io", "badgen.net",
    "fonts.googleapis.com", "fonts.gstatic.com", "translate.yandex.ru",
}
_SUBSCRIPTION_HINTS = ("subscription", "subscribe", "sub", "vpn", "proxy", "clash", "mihomo", "feed", "provider", "config")
_SUBSCRIPTION_CONTEXT_HINTS = ("subscription", "subscribe", "sub url", "proxy provider", "订阅")


def _clean_candidate_url(raw_url: str) -> str | None:
    url = raw_url.strip().rstrip(_TRAILING_PUNCTUATION)
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1]
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return None
        _ = parsed.port  # Force validation of malformed port values.
    except ValueError:
        return None
    return url


def _looks_like_subscription_url(url: str, context: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host in _NON_SUBSCRIPTION_HOSTS:
        return False
    suffix = PurePosixPath(parsed.path.lower()).suffix
    if suffix in {".svg", ".png", ".jpg", ".jpeg", ".gif", ".css", ".js"}:
        return False
    url_text = f"{parsed.path} {parsed.query}".lower()
    if "tor-bridge" in url_text or "tor_bridge" in url_text:
        return False
    if host == "github.com" and suffix not in {".txt", ".yaml", ".yml", ".sub", ".conf", ".list", ".json"}:
        return False
    if any(hint in url_text for hint in _SUBSCRIPTION_HINTS):
        return True
    if suffix in {".txt", ".yaml", ".yml", ".sub", ".conf", ".list", ".json"}:
        return True
    return any(hint in context for hint in _SUBSCRIPTION_CONTEXT_HINTS)


def extract_subscription_urls(source_texts: list[str]) -> list[str]:
    """Extract unique HTTP(S) URLs from text, preserving their query strings."""
    urls: list[str] = []
    seen: set[str] = set()
    for text in source_texts:
        for match in _URL_RE.finditer(text):
            url = _clean_candidate_url(match.group(0))
            context = text[max(0, match.start() - 80):match.end() + 80].lower()
            if url and _looks_like_subscription_url(url, context) and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def fetch_subscription_configs(urls: list[str]) -> list[str]:
    """Fetch saved feeds and return unique parseable configs from all of them."""
    unique_urls = list(dict.fromkeys(urls))
    configs: list[str] = []
    seen: set[str] = set()
    for index, url in enumerate(unique_urls, 1):
        try:
            content = fetch_url_text(url)
            parsed = parse_configs_from_content(content) if content else []
            new_count = 0
            for config in parsed:
                # A different display name does not make the same node a new config.
                key = config.split("#", 1)[0]
                if key not in seen:
                    seen.add(key)
                    configs.append(config)
                    new_count += 1
            logger.info(
                "Subscription feed %d/%d: parsed %d configs, %d new: %s",
                index, len(unique_urls), len(parsed), new_count, url,
            )
        except Exception as exc:
            logger.warning("Could not parse subscription feed %s: %s", url, exc)
    return configs


def validate_subscription_urls(urls: list[str], singbox_path: str) -> list[str]:
    """Keep subscription URLs with at least one strictly tunnel-tested node."""
    unique_urls = list(dict.fromkeys(urls))
    candidates = unique_urls[:SUBSCRIPTION_MAX_URLS]
    if len(candidates) < len(unique_urls):
        logger.warning(
            "Checking the first %d of %d discovered URLs; increase SUBSCRIPTION_MAX_URLS to scan more",
            len(candidates), len(unique_urls),
        )
    valid: list[str] = []
    parseable = 0
    seen_feeds: set[tuple[str, ...]] = set()

    for index, url in enumerate(candidates, 1):
        try:
            content = fetch_url_text(url)
            configs = parse_configs_from_content(content) if content else []
            if not configs:
                logger.info("Subscription %d/%d has no supported configs: %s", index, len(candidates), url)
                continue
            parseable += 1
            feed_key = tuple(sorted({config.split("#", 1)[0] for config in configs}))
            if feed_key in seen_feeds:
                logger.info("Skipping duplicate subscription content: %s", url)
                continue
            seen_feeds.add(feed_key)
            nodes = list(dict.fromkeys(configs))[:SUBSCRIPTION_MAX_NODES]
            has_working_node = False
            for offset in range(0, len(nodes), SUBSCRIPTION_NODE_BATCH_SIZE):
                batch = nodes[offset:offset + SUBSCRIPTION_NODE_BATCH_SIZE]
                passed = asyncio.run(tunnel_filter(batch, singbox_path, verify_tls_cert=True))
                if passed:
                    has_working_node = True
                    break
            if has_working_node:
                valid.append(url)
                logger.info("Working subscription %d/%d: %s", index, len(candidates), url)
            else:
                logger.info("No working nodes in subscription %d/%d: %s", index, len(candidates), url)
        except Exception as exc:
            logger.warning("Subscription check failed for %s: %s", url, exc)

    logger.info(
        "Subscription scan: %d candidates | %d parseable | %d working",
        len(candidates), parseable, len(valid),
    )
    return valid
