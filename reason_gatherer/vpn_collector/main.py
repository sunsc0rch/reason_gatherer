import argparse
import asyncio
import logging
import sys
from datetime import date

from vpn_collector.config import (
    RESULTS_DIR, SOURCES_FILE, LOGS_DIR, MAX_RUN_FILES, SINGBOX_SEARCH_PATHS,
)
from vpn_collector.sources import fetch_all_configs, add_source, sync_stars
from vpn_collector.tester import tcp_filter, tunnel_filter, find_singbox
from vpn_collector.storage import (
    load_known_hosts, is_duplicate, save_config,
    rotate_run_files, get_stats,
)


def _setup_logging() -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOGS_DIR / "vpn_collector.log"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def cmd_collect() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    print("Fetching configs from all sources...")
    configs = fetch_all_configs(SOURCES_FILE)
    print(f"Collected {len(configs)} unique configs")

    print("Running TCP pre-filter...")
    candidates = asyncio.run(tcp_filter(configs))
    print(f"TCP passed: {len(candidates)}")

    (RESULTS_DIR / "candidates.txt").write_text("\n".join(candidates))
    print("Saved to results/candidates.txt")


def cmd_test() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    candidates_file = RESULTS_DIR / "candidates.txt"
    if not candidates_file.exists():
        print("No candidates.txt found. Run --collect first.")
        sys.exit(1)

    singbox_path = find_singbox()
    if not singbox_path:
        print("sing-box binary not found. Searched:")
        for p in SINGBOX_SEARCH_PATHS:
            print(f"  {p}")
        sys.exit(1)
    print(f"Using sing-box: {singbox_path}")

    candidates = [line for line in candidates_file.read_text().splitlines() if line.strip()]
    known_hosts = load_known_hosts(RESULTS_DIR)
    new_candidates = [c for c in candidates if not is_duplicate(c, known_hosts)]
    print(f"Candidates: {len(candidates)} | New (not in history): {len(new_candidates)}")

    tested = asyncio.run(tunnel_filter(new_candidates, singbox_path))
    print(f"Passed all tests: {len(tested)}")

    run_date = date.today().isoformat()
    for config in tested:
        save_config(config, RESULTS_DIR, known_hosts, run_date=run_date)
    rotate_run_files(RESULTS_DIR, MAX_RUN_FILES)
    print(f"Results saved to results/run_{run_date}.txt and results/known_good.txt")


def cmd_full() -> None:
    cmd_collect()
    cmd_test()


def cmd_stats() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    stats = get_stats(RESULTS_DIR)
    if not stats:
        print("No result files found.")
        return
    for name, count in sorted(stats.items()):
        print(f"  {name}: {count} configs")


def main() -> None:
    parser = argparse.ArgumentParser(description="VPN Config Collector and Tester")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--collect", action="store_true", help="Fetch configs, TCP filter → candidates.txt")
    mode.add_argument("--test", action="store_true", help="Tunnel test candidates.txt → known_good.txt")
    mode.add_argument("--full", action="store_true", help="Run --collect then --test")
    mode.add_argument("--stats", action="store_true", help="Show counts per result file")
    parser.add_argument("--add-source", metavar="SOURCE", help="Add GitHub repo (user/repo) or raw URL")
    parser.add_argument("--sync-stars", metavar="USERNAME", help="Sync GitHub starred repos")
    args = parser.parse_args()

    if not any([args.collect, args.test, args.full, args.stats, args.add_source, args.sync_stars]):
        parser.print_help()
        return

    _setup_logging()

    if args.collect:
        cmd_collect()
    elif args.test:
        cmd_test()
    elif args.full:
        cmd_full()
    elif args.stats:
        cmd_stats()
    elif args.add_source:
        added = add_source(args.add_source, SOURCES_FILE)
        print("Added." if added else "Already exists.")
    elif args.sync_stars:
        count = sync_stars(args.sync_stars, SOURCES_FILE)
        print(f"Added {count} new repo(s) from stars.")


if __name__ == "__main__":
    main()
