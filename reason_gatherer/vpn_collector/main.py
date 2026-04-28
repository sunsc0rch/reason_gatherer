import argparse
import asyncio
import logging
import random
import sys
from datetime import date

_log = logging.getLogger(__name__)

from vpn_collector.config import (
    RESULTS_DIR, SOURCES_FILE, LOGS_DIR, MAX_RUN_FILES, SINGBOX_SEARCH_PATHS,
    TCP_BATCH_SIZE,
)
from vpn_collector.parser import extract_host_port
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


def _load_candidates_hp(candidates_file) -> set[tuple]:
    """Return host:port pairs already present in candidates.txt."""
    if not candidates_file.exists():
        return set()
    known: set[tuple] = set()
    for line in candidates_file.read_text().splitlines():
        line = line.strip()
        if line:
            hp = extract_host_port(line)
            if hp:
                known.add(hp)
    return known


def cmd_collect(sample: int | None = None) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    _log.info("Fetching configs from all sources...")
    configs = fetch_all_configs(SOURCES_FILE)
    _log.info(f"Collected {len(configs)} unique configs")

    if sample and sample < len(configs):
        configs = random.sample(configs, sample)
        _log.info(f"Sampled {sample} configs randomly")

    candidates_file = RESULTS_DIR / "candidates.txt"

    # Skip TCP check for host:ports that already passed in a previous run.
    known_hp = _load_candidates_hp(candidates_file)
    if known_hp:
        pre_approved = [c for c in configs if extract_host_port(c) in known_hp]
        to_check = [c for c in configs if extract_host_port(c) not in known_hp]
        _log.info(
            f"Skipping TCP for {len(pre_approved)} pre-approved endpoints | "
            f"Checking {len(to_check)} new"
        )
    else:
        pre_approved = []
        to_check = configs

    # Rewrite the file: pre-approved first, then append new results batch by batch.
    with open(candidates_file, "w") as fh:
        if pre_approved:
            fh.write("\n".join(pre_approved) + "\n")

    total_passed = len(pre_approved)
    total = len(to_check)
    num_batches = max(1, (total + TCP_BATCH_SIZE - 1) // TCP_BATCH_SIZE)

    if total > 0:
        _log.info(f"TCP pre-filter: {total} configs → {num_batches} batches of {TCP_BATCH_SIZE}")

    for batch_idx, offset in enumerate(range(0, total, TCP_BATCH_SIZE), 1):
        batch = to_check[offset:offset + TCP_BATCH_SIZE]
        batch_end = min(offset + TCP_BATCH_SIZE, total)
        _log.info(f"[{batch_idx}/{num_batches}] Checking {offset + 1}–{batch_end}...")
        passed = asyncio.run(tcp_filter(batch))
        total_passed += len(passed)
        if passed:
            with open(candidates_file, "a") as fh:
                fh.write("\n".join(passed) + "\n")
        _log.info(
            f"[{batch_idx}/{num_batches}] Batch: {len(passed)} passed | "
            f"Total so far: {total_passed}"
        )

    _log.info(f"TCP filter done: {total_passed} total candidates → {candidates_file}")


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
    _log.info(f"Using sing-box: {singbox_path}")

    candidates = [line for line in candidates_file.read_text().splitlines() if line.strip()]
    known_hosts = load_known_hosts(RESULTS_DIR)
    new_candidates = [c for c in candidates if not is_duplicate(c, known_hosts)]
    _log.info(f"Candidates: {len(candidates)} | New (not in history): {len(new_candidates)}")

    tested = asyncio.run(tunnel_filter(new_candidates, singbox_path))
    _log.info(f"Passed all tests: {len(tested)}")

    run_date = date.today().isoformat()
    for config in tested:
        save_config(config, RESULTS_DIR, known_hosts, run_date=run_date)
    rotate_run_files(RESULTS_DIR, MAX_RUN_FILES)
    _log.info(f"Results saved to results/run_{run_date}.txt and results/known_good.txt")


def cmd_full(sample: int | None = None) -> None:
    cmd_collect(sample=sample)
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
    parser.add_argument("--sample", type=int, metavar="N",
                        help="Randomly sample N configs before TCP filter (e.g. --sample 30000)")
    args = parser.parse_args()

    if not any([args.collect, args.test, args.full, args.stats, args.add_source, args.sync_stars]):
        parser.print_help()
        return

    _setup_logging()

    if args.collect:
        cmd_collect(sample=args.sample)
    elif args.test:
        cmd_test()
    elif args.full:
        cmd_full(sample=args.sample)
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
