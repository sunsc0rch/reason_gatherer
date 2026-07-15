import argparse
import asyncio
import concurrent.futures
import logging
import sys
from datetime import date

from awg_collector.config import (
    RESULTS_AWG_DIR, SOURCES_AWG_FILE, LOGS_DIR,
    AWG_TUNNEL_CONCURRENCY, AWG_RECHECK_RETRIES, TCP_CONCURRENCY, TCP_TIMEOUT,
    TOP_N_CONFIGS,
)
from awg_collector.parser import parse_awg_configs
from awg_collector.sources import fetch_all_configs, add_source
from awg_collector.storage import (
    save_known_good, load_known_good, remove_known_good, build_vpn_archive,
    load_config_meta, save_config_meta, update_meta_entry,
    save_candidates,
)
from awg_collector.tester import tcp_check, test_awg_tunnel, passes_speed

_log = logging.getLogger(__name__)


def _setup_logging() -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOGS_DIR / "awg_collector.log"),
            logging.StreamHandler(sys.stdout),
        ],
    )


async def _tcp_filter(configs: list[dict]) -> list[dict]:
    by_endpoint: dict[str, list[dict]] = {}
    for cfg in configs:
        ep = cfg["endpoint"]
        by_endpoint.setdefault(ep, []).append(cfg)

    sem = asyncio.Semaphore(TCP_CONCURRENCY)

    async def check(ep: str) -> str | None:
        host, _, port = ep.rpartition(":")
        async with sem:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, int(port)), timeout=TCP_TIMEOUT
                )
                writer.close()
                await writer.wait_closed()
                return ep
            except Exception:
                return None

    endpoints = list(by_endpoint)
    results = await asyncio.gather(*[check(ep) for ep in endpoints])
    passing = {ep for ep in results if ep}
    return [cfg for ep, cfgs in by_endpoint.items() if ep in passing for cfg in cfgs]


def _tunnel_test_batch(configs: list[dict]) -> list[dict]:
    """Return passing configs with 'speed' key (bytes/s) attached."""
    passing = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=AWG_TUNNEL_CONCURRENCY) as pool:
        futures = {pool.submit(test_awg_tunnel, cfg["text"]): cfg for cfg in configs}
        for future, cfg in futures.items():
            try:
                speed = future.result()
                if speed is not None and passes_speed(speed):
                    passing.append({**cfg, "speed": speed})
                    _log.info(f"PASS {cfg['endpoint']} {speed/125000:.1f} Mbps")
                else:
                    _log.info(f"FAIL {cfg['endpoint']}")
            except Exception as e:
                _log.warning(f"Error testing {cfg['endpoint']}: {e}")
    return passing


def cmd_collect() -> None:
    RESULTS_AWG_DIR.mkdir(exist_ok=True)
    today = date.today().isoformat()

    _log.info("Fetching AWG configs from all sources...")
    configs = fetch_all_configs(SOURCES_AWG_FILE)
    _log.info(f"Collected {len(configs)} unique AWG configs")

    if not configs:
        _log.warning("No configs collected. Check sources_awg.json.")
        return

    save_candidates(configs)

    # AWG uses UDP — TCP pre-filter is not applicable; go straight to tunnel test
    _log.info(f"Tunnel testing {len(configs)} configs (concurrency={AWG_TUNNEL_CONCURRENCY})...")
    passing = _tunnel_test_batch(configs)
    _log.info(f"Passed tunnel test: {len(passing)} (archive will contain top {TOP_N_CONFIGS} by speed)")

    meta = load_config_meta()
    for cfg in passing:
        save_known_good(cfg["text"], cfg["endpoint"])
        update_meta_entry(meta, cfg["endpoint"], today, cfg["speed"])

    save_config_meta(meta)
    archive = build_vpn_archive(meta)
    total = len(load_known_good())
    _log.info(f"known_good: {total} configs | archive (top {TOP_N_CONFIGS}): {archive}")


def cmd_recheck() -> None:
    today = date.today().isoformat()
    configs = load_known_good()
    _log.info(f"Rechecking {len(configs)} known_good configs...")

    meta = load_config_meta()
    removed = 0

    for cfg in configs:
        ep = cfg["endpoint"]
        best_speed = None
        for attempt in range(AWG_RECHECK_RETRIES + 1):
            speed = test_awg_tunnel(cfg["text"])
            if speed is not None and passes_speed(speed):
                _log.info(f"PASS {ep} {speed/125000:.1f} Mbps")
                best_speed = speed
                break
            _log.info(f"FAIL attempt {attempt+1}/{AWG_RECHECK_RETRIES+1} {ep}")

        if best_speed is not None:
            update_meta_entry(meta, ep, today, best_speed)
        else:
            _log.info(f"Removing {ep} from known_good")
            remove_known_good(ep)
            meta.pop(ep, None)
            removed += 1

    save_config_meta(meta)
    archive = build_vpn_archive(meta)
    remaining = len(load_known_good())
    _log.info(f"Recheck done: removed={removed} remaining={remaining} | archive (top {TOP_N_CONFIGS}): {archive}")


def cmd_export() -> None:
    meta = load_config_meta()
    archive = build_vpn_archive(meta)
    total = len(load_known_good())
    _log.info(f"known_good: {total} | exported top {TOP_N_CONFIGS} to {archive}")


def cmd_stats() -> None:
    configs = load_known_good()
    meta = load_config_meta()
    with_speed = sum(1 for ep in meta if "speed" in meta[ep])
    print(f"known_good: {len(configs)} configs")
    print(f"config_meta entries: {len(meta)} ({with_speed} with speed)")
    archive = RESULTS_AWG_DIR / "all_configs.zip"
    if archive.exists():
        size_kb = archive.stat().st_size // 1024
        print(f"all_configs.zip: {size_kb} KB (top {TOP_N_CONFIGS} by speed)")


def main() -> None:
    _setup_logging()
    parser = argparse.ArgumentParser(description="AWG config collector")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--collect",    action="store_true", help="Fetch + test configs, save all to known_good")
    group.add_argument("--recheck",    action="store_true", help="Recheck known_good, remove dead configs")
    group.add_argument("--export",     action="store_true", help=f"Rebuild all_configs.zip (top {TOP_N_CONFIGS} by speed)")
    group.add_argument("--add-source", metavar="URL",        help="Add source to sources_awg.json")
    group.add_argument("--stats",      action="store_true", help="Print statistics")
    args = parser.parse_args()

    if args.collect:
        cmd_collect()
    elif args.recheck:
        cmd_recheck()
    elif args.export:
        cmd_export()
    elif args.add_source:
        added = add_source(args.add_source, SOURCES_AWG_FILE)
        print("Added." if added else "Already exists.")
    elif args.stats:
        cmd_stats()


if __name__ == "__main__":
    main()
