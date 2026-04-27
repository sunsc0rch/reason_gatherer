import asyncio
import logging
import os

from vpn_collector.config import TCP_TIMEOUT, TCP_CONCURRENCY, PROXY_ENV_VARS
from vpn_collector.parser import extract_host_port

logger = logging.getLogger(__name__)


async def tcp_check(host: str, port: int, timeout: float = TCP_TIMEOUT) -> bool:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def tcp_filter(
    configs: list[str],
    concurrency: int = TCP_CONCURRENCY,
    timeout: float = TCP_TIMEOUT,
) -> list[str]:
    semaphore = asyncio.Semaphore(concurrency)

    async def check_one(config: str) -> str | None:
        hp = extract_host_port(config)
        if not hp:
            return None
        async with semaphore:
            return config if await tcp_check(hp[0], hp[1], timeout) else None

    results = await asyncio.gather(*[check_one(c) for c in configs])
    return [r for r in results if r is not None]
