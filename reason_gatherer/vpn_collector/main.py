import argparse
import asyncio
import logging
import random as _random
import sys
from datetime import date
from pathlib import Path

_log = logging.getLogger(__name__)

from vpn_collector.config import (
    RESULTS_DIR, SOURCES_FILE, LOGS_DIR, MAX_RUN_FILES, SINGBOX_SEARCH_PATHS,
    TCP_BATCH_SIZE, PRIVILEGED_MIN_DAYS, PRIVILEGED_RECHECK_RETRIES,
)
from vpn_collector.parser import extract_host_port
from vpn_collector.sources import fetch_all_configs, add_source, sync_stars
from vpn_collector.tester import tcp_filter, tunnel_filter, find_singbox, test_config_tunnel
from vpn_collector.storage import (
    load_known_hosts, load_known_good_hp, load_known_good_configs,
    rewrite_known_good, load_tcp_cache, update_tcp_cache,
    is_duplicate, save_config, rotate_run_files, trim_candidates, get_stats,
    load_config_meta, save_config_meta, update_meta_first_seen,
    load_privileged, save_privileged,
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


def cmd_collect(sample: int | None = None) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    _log.info("Syncing starred repos for sunsc0rch...")
    try:
        added = sync_stars("sunsc0rch", SOURCES_FILE)
        if added:
            _log.info(f"Added {added} new repo(s) from stars")
    except Exception as e:
        _log.warning(f"Star sync failed (non-fatal): {e}")
    _log.info("Fetching configs from all sources...")
    configs = fetch_all_configs(SOURCES_FILE)
    _log.info(f"Collected {len(configs)} unique configs")

    if sample and sample < len(configs):
        configs = random.sample(configs, sample)
        _log.info(f"Sampled {sample} configs randomly")

    candidates_file = RESULTS_DIR / "candidates.txt"
    known_good_hp = load_known_good_hp(RESULTS_DIR)

    # One-time migration: seed tcp_cache.txt from existing candidates.txt so
    # that host:ports already TCP-verified in previous runs are not re-checked.
    if not (RESULTS_DIR / "tcp_cache.txt").exists() and candidates_file.exists():
        seed_hp: list[tuple] = []
        seen_seed: set[tuple] = set()
        for line in candidates_file.read_text().splitlines():
            line = line.strip()
            if line:
                hp = extract_host_port(line)
                if hp and hp not in seen_seed:
                    seen_seed.add(hp)
                    seed_hp.append(hp)
        if seed_hp:
            update_tcp_cache(RESULTS_DIR, seed_hp)
            _log.info(f"Seeded tcp_cache.txt with {len(seed_hp)} endpoints from existing candidates.txt")

    tcp_cache_hp = load_tcp_cache(RESULTS_DIR)

    # Drop configs whose server is already in known_good — no point retesting.
    before = len(configs)
    configs = [c for c in configs if extract_host_port(c) not in known_good_hp]
    _log.info(
        f"Skipped {before - len(configs)} source configs pointing to "
        f"{len(known_good_hp)} already-verified host:ports | {len(configs)} remain"
    )

    # Split: hosts with cached TCP pass (skip check) vs genuinely new hosts.
    pre_approved = [c for c in configs if extract_host_port(c) in tcp_cache_hp]
    to_check = [c for c in configs if extract_host_port(c) not in tcp_cache_hp]
    _log.info(
        f"TCP cache: {len(pre_approved)} pre-approved | "
        f"{len(to_check)} new endpoints to check"
    )

    # Rewrite candidates.txt: pre-approved first, then append new TCP results.
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
            # Persist newly TCP-verified host:ports (deduplicated) to the cache.
            seen: set[tuple] = set()
            new_hp: list[tuple] = []
            for cfg in passed:
                hp = extract_host_port(cfg)
                if hp and hp not in seen and hp not in tcp_cache_hp:
                    seen.add(hp)
                    new_hp.append(hp)
            update_tcp_cache(RESULTS_DIR, new_hp)
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
    _log.info(f"Candidates: {len(candidates)} | Already verified: {len(candidates) - len(new_candidates)} | To test: {len(new_candidates)}")

    run_date = date.today().isoformat()
    meta = load_config_meta(RESULTS_DIR)
    passed = [0]

    def save_immediately(config: str) -> None:
        save_config(config, RESULTS_DIR, known_hosts, run_date=run_date)
        passed[0] += 1
        _log.info(f"Saved: {config[:80]}...")

    passed_configs = asyncio.run(tunnel_filter(new_candidates, singbox_path, on_pass=save_immediately))
    for config in passed_configs:
        hp = extract_host_port(config)
        if hp:
            update_meta_first_seen(meta, f"{hp[0]}:{hp[1]}", run_date)
    save_config_meta(RESULTS_DIR, meta)
    rotate_run_files(RESULTS_DIR, MAX_RUN_FILES)
    _log.info(f"Done: {passed[0]} new configs saved → results/run_{run_date}.txt")

    if passed[0] > 0:
        removed = trim_candidates(candidates_file, load_known_good_hp(RESULTS_DIR))
        _log.info(f"Trimmed candidates.txt: removed {removed} now-verified configs")


def find_free_socks_port() -> int:
    from vpn_collector.config import SOCKS_PORT_RANGE
    return _random.randint(*SOCKS_PORT_RANGE)


def _update_privileged(
    results_dir: Path,
    survivors: list[str],
    dead_configs: list[str],
    singbox_path: str,
    meta: dict,
    today: str,
) -> None:
    from datetime import date as _date2
    privileged = load_privileged(results_dir)
    privileged_hp = set()
    for cfg in privileged:
        hp = extract_host_port(cfg)
        if hp:
            privileged_hp.add(f"{hp[0]}:{hp[1]}")

    # Продвигаем серверы, стабильно работающие >= PRIVILEGED_MIN_DAYS дней
    for cfg in survivors:
        hp = extract_host_port(cfg)
        if not hp:
            continue
        key = f"{hp[0]}:{hp[1]}"
        entry = meta.get(key)
        if not entry:
            continue
        try:
            days = (_date2.fromisoformat(today) - _date2.fromisoformat(entry["first_seen"])).days
        except ValueError:
            continue
        if days >= PRIVILEGED_MIN_DAYS and key not in privileged_hp:
            privileged.append(cfg)
            privileged_hp.add(key)
            _log.info(f"Promoted to privileged ({days}d): {cfg[:80]}")
        if key in privileged_hp:
            meta[key]["fail_streak"] = 0

    # Обрабатываем упавшие серверы из privileged
    for cfg in dead_configs:
        hp = extract_host_port(cfg)
        if not hp:
            continue
        key = f"{hp[0]}:{hp[1]}"
        if key not in privileged_hp:
            continue
        # Повторные проверки
        recovered = False
        for attempt in range(PRIVILEGED_RECHECK_RETRIES):
            port = find_free_socks_port()
            _log.info(f"Privileged retry {attempt + 1}/{PRIVILEGED_RECHECK_RETRIES}: {cfg[:60]}")
            result = test_config_tunnel(cfg, singbox_path, port)
            if result is not None:
                _log.info(f"Privileged server recovered on retry: {cfg[:60]}")
                meta[key]["fail_streak"] = 0
                recovered = True
                break
        if not recovered:
            privileged = [c for c in privileged if extract_host_port(c) != hp]
            privileged_hp.discard(key)
            meta[key]["fail_streak"] = 0
            _log.info(f"Removed from privileged after {PRIVILEGED_RECHECK_RETRIES} retries: {cfg[:60]}")

    save_privileged(results_dir, privileged)


def cmd_recheck(update_known_good: bool = False) -> None:
    """Re-test all configs in known_good.txt; update privileged.txt accordingly."""
    RESULTS_DIR.mkdir(exist_ok=True)
    if not (RESULTS_DIR / "known_good.txt").exists():
        print("No known_good.txt found. Nothing to recheck.")
        sys.exit(1)

    singbox_path = find_singbox()
    if not singbox_path:
        print("sing-box binary not found. Searched:")
        for p in SINGBOX_SEARCH_PATHS:
            print(f"  {p}")
        sys.exit(1)
    _log.info(f"Using sing-box: {singbox_path}")

    configs = load_known_good_configs(RESULTS_DIR)
    _log.info(f"Recheck: {len(configs)} configs loaded from known_good.txt")

    _log.info("TCP pre-filter...")
    tcp_alive = asyncio.run(tcp_filter(configs))
    _log.info(f"TCP: {len(tcp_alive)} alive | {len(configs) - len(tcp_alive)} unreachable")

    _log.info("Tunnel test...")
    recheck_date = date.today().isoformat()
    out_file = RESULTS_DIR / f"recheck_{recheck_date}.txt"
    survivors: list[str] = []

    original_by_base = {c.split("#")[0]: c for c in tcp_alive}

    def on_pass(config: str) -> None:
        original = original_by_base.get(config.split("#")[0], config)
        survivors.append(original)
        with open(out_file, "a") as f:
            f.write(original + "\n")
        _log.info(f"Still good: {original[:80]}...")

    asyncio.run(tunnel_filter(tcp_alive, singbox_path, on_pass=on_pass))

    survivors_hp = {extract_host_port(c) for c in survivors}
    dead_configs = [c for c in configs if extract_host_port(c) not in survivors_hp]

    meta = load_config_meta(RESULTS_DIR)
    _update_privileged(
        results_dir=RESULTS_DIR,
        survivors=survivors,
        dead_configs=dead_configs,
        singbox_path=singbox_path,
        meta=meta,
        today=recheck_date,
    )
    save_config_meta(RESULTS_DIR, meta)

    if update_known_good:
        rewrite_known_good(RESULTS_DIR, survivors)
        _log.info(f"known_good.txt updated: {len(survivors)} survivors, {len(dead_configs)} removed")

    _log.info(
        f"Recheck done: {len(survivors)}/{len(configs)} still working → {out_file.name}"
    )


def cmd_setup_tg() -> None:
    try:
        from telethon import TelegramClient
    except ImportError:
        print("Telethon not installed. Run: pip install telethon>=1.36")
        sys.exit(1)

    from vpn_collector.tg_source import load_tg_auth, save_tg_auth
    from vpn_collector.config import TG_SESSION_FILE

    auth = load_tg_auth()
    if auth is None:
        try:
            api_id = int(input("Enter your Telegram api_id: ").strip())
        except ValueError:
            print("api_id must be a number.")
            sys.exit(1)
        api_hash = input("Enter your Telegram api_hash: ").strip()
        save_tg_auth(api_id, api_hash)
        print("Auth saved to ~/.config/vpn_collector/tg_auth.json")
    else:
        api_id = auth["api_id"]
        api_hash = auth["api_hash"]
        print(f"Using existing auth (api_id={api_id})")

    import asyncio

    async def _setup():
        from vpn_collector.tg_source import _telethon_proxy
        proxy = _telethon_proxy()
        client = TelegramClient(str(TG_SESSION_FILE), api_id, api_hash, proxy=proxy)
        await client.start(
            phone=lambda: input("Phone number (e.g. +79991234567): ").strip(),
            code_callback=lambda: input("Enter the code you received: ").strip(),
            password=lambda: input("2FA password: ").strip(),
        )
        await client.disconnect()
        print("Setup complete. Add channels with: --add-source t.me/channelname")

    asyncio.run(_setup())


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
    mode.add_argument("--recheck", action="store_true", help="Re-test known_good.txt → recheck_YYYY-MM-DD.txt (known_good untouched)")
    mode.add_argument("--stats", action="store_true", help="Show counts per result file")
    mode.add_argument("--setup-tg", action="store_true", help="Authenticate Telegram (interactive)")
    parser.add_argument("--add-source", metavar="SOURCE", help="Add GitHub repo (user/repo) or raw URL")
    parser.add_argument("--sync-stars", metavar="USERNAME", help="Sync GitHub starred repos")
    parser.add_argument("--sample", type=int, metavar="N",
                        help="Randomly sample N configs before TCP filter (e.g. --sample 30000)")
    parser.add_argument(
        "--update-known-good",
        action="store_true",
        help="Used with --recheck: overwrite known_good.txt with only surviving configs",
    )
    args = parser.parse_args()

    if not any([args.collect, args.test, args.full, args.recheck, args.stats, args.add_source, args.sync_stars, args.setup_tg]):
        parser.print_help()
        return

    _setup_logging()

    if args.collect:
        cmd_collect(sample=args.sample)
    elif args.test:
        cmd_test()
    elif args.full:
        cmd_full(sample=args.sample)
    elif args.recheck:
        cmd_recheck(update_known_good=args.update_known_good)
    elif args.stats:
        cmd_stats()
    elif args.setup_tg:
        cmd_setup_tg()
    elif args.add_source:
        added = add_source(args.add_source, SOURCES_FILE)
        print("Added." if added else "Already exists.")
    elif args.sync_stars:
        count = sync_stars(args.sync_stars, SOURCES_FILE)
        print(f"Added {count} new repo(s) from stars.")


if __name__ == "__main__":
    main()
