import argparse
import asyncio
import logging
import random as _random
import subprocess
import sys
import csv
import os
import time
from collections import Counter
from datetime import date
from pathlib import Path

_log = logging.getLogger(__name__)
WARP_SOCKS_PROXY = ("127.0.0.1", 40000)

from vpn_collector.config import (
    RESULTS_DIR, SOURCES_FILE, LOGS_DIR, MAX_RUN_FILES, SINGBOX_SEARCH_PATHS,
    TCP_BATCH_SIZE, PRIVILEGED_MIN_DAYS, PRIVILEGED_RECHECK_RETRIES,
    GEMINI_TEST_MODEL, GEMINI_TEST_DEFAULT_SAMPLE, GEMINI_TEST_INTERVAL_SECONDS,
)
from vpn_collector.parser import extract_host_port, is_vpn_line
from vpn_collector.sources import (
    GitHubRateLimitError, add_source, fetch_all_configs, sync_stars,
)
from vpn_collector.sources import fetch_source_texts
from vpn_collector.subscriptions import (
    extract_subscription_urls, fetch_subscription_configs,
    validate_subscription_urls,
)
from vpn_collector.tester import (
    tcp_filter, tunnel_filter, find_singbox, test_config_tunnel,
    test_config_gemini,
    classify_endpoints, socks5_connect,
)
from vpn_collector.storage import (
    load_known_hosts, load_known_good_hp, load_known_good_configs,
    rewrite_known_good, load_tcp_cache, update_tcp_cache,
    is_duplicate, save_config, rotate_run_files, trim_candidates, get_stats,
    load_config_meta, save_config_meta, update_meta_first_seen,
    load_privileged, save_privileged,
    save_subscriptions, save_subscription_configs,
    split_configs_by_protocol,
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
    logging.getLogger("telethon").setLevel(logging.WARNING)


def cmd_collect(sample: int | None = None) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    _log.info("Syncing starred repos for sunsc0rch...")
    try:
        added = sync_stars("sunsc0rch", SOURCES_FILE)
        if added:
            _log.info(f"Added {added} new repo(s) from stars")
    except GitHubRateLimitError as e:
        _log.error("GitHub rate limit prevented source sync; aborting collection: %s", e)
        raise SystemExit(1) from e
    except Exception as e:
        _log.warning(f"Star sync failed (non-fatal): {e}")
    _log.info("Fetching configs from all sources...")
    try:
        configs = fetch_all_configs(SOURCES_FILE)
    except GitHubRateLimitError as e:
        _log.error("GitHub rate limit prevented a complete source fetch; aborting: %s", e)
        raise SystemExit(1) from e
    _log.info(f"Collected {len(configs)} unique configs")

    if sample and sample < len(configs):
        configs = _random.sample(configs, sample)
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
    if _warp_tunnel_active():
        raise SystemExit(
            "WARP is active in system-tunnel mode; switch to 'warp-cli mode proxy' "
            "to keep --test direct"
        )

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

    passed_configs = asyncio.run(tunnel_filter(
        new_candidates,
        singbox_path,
        on_pass=save_immediately,
        log_every=5,
        progress_label="--test",
    ))
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


def cmd_test_warp(proxy: tuple[str, int] = WARP_SOCKS_PROXY) -> None:
    """Test remaining candidates through the local WARP SOCKS proxy."""
    candidates_file = RESULTS_DIR / "candidates.txt"
    if not candidates_file.exists():
        print("No candidates.txt found. Run --collect first.")
        sys.exit(1)

    singbox_path = find_singbox()
    if not singbox_path:
        print("sing-box binary not found. Searched:")
        for path in SINGBOX_SEARCH_PATHS:
            print(f"  {path}")
        sys.exit(1)
    _log.info("Using sing-box: %s", singbox_path)

    if not asyncio.run(socks5_connect(proxy[0], proxy[1], "1.1.1.1", 443, 5.0)):
        raise SystemExit(
            f"WARP SOCKS5 proxy {proxy[0]}:{proxy[1]} is not reachable; "
            "start warp-cli in proxy mode"
        )

    warp_results_dir = RESULTS_DIR / "warp"
    warp_results_dir.mkdir(parents=True, exist_ok=True)
    candidates = [line for line in candidates_file.read_text().splitlines() if line.strip()]
    known_hosts = load_known_hosts(warp_results_dir)
    new_candidates = [candidate for candidate in candidates if not is_duplicate(candidate, known_hosts)]
    _log.info(
        "WARP candidates: %d | Already verified via WARP: %d | To test: %d",
        len(candidates), len(candidates) - len(new_candidates), len(new_candidates),
    )

    run_date = date.today().isoformat()
    passed = [0]

    def save_warp_immediately(config: str) -> None:
        save_config(config, warp_results_dir, known_hosts, run_date=run_date)
        passed[0] += 1
        _log.info("Saved via WARP: %s...", config[:80])

    asyncio.run(tunnel_filter(
        new_candidates,
        singbox_path,
        on_pass=save_warp_immediately,
        dialer_proxy=proxy,
        log_every=5,
        progress_label="--test-warp",
    ))
    rotate_run_files(warp_results_dir, MAX_RUN_FILES)
    part_counts = split_configs_by_protocol(
        warp_results_dir / "known_good.txt",
        warp_results_dir / "parts",
    )
    _log.info(
        "WARP copy parts: %d protocols | %d files → results/warp/parts/INDEX.md",
        len(part_counts), sum(part_counts.values()),
    )
    _log.info(
        "Done: %d new configs saved via WARP → results/warp/run_%s.txt",
        passed[0], run_date,
    )


def cmd_test_gemini(
    source_file: Path | None = None,
    sample: int | None = None,
    probe_only: bool = False,
) -> None:
    """Probe Gemini or check generation through previously verified configs."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(
            "GEMINI_API_KEY is not set. Export a Gemini API key before --test-gemini."
        )

    source_file = source_file or RESULTS_DIR / "known_good.txt"
    if not source_file.exists():
        raise SystemExit(f"Live config file not found: {source_file}")
    configs = [
        line.strip()
        for line in source_file.read_text(errors="replace").splitlines()
        if line.strip() and not line.strip().startswith("#") and is_vpn_line(line.strip())
    ]
    if not configs:
        raise SystemExit(f"No live configs found in {source_file}.")
    if sample is None:
        sample = min(GEMINI_TEST_DEFAULT_SAMPLE, len(configs))
        _log.info(
            "No --sample provided; selecting a random sample of %d configs",
            sample,
        )
    elif sample < 1:
        raise SystemExit("--sample must be a positive number")
    if sample and sample < len(configs):
        configs = _random.sample(configs, sample)
        _log.info("Sampled %d live configs for Gemini check", sample)

    singbox_path = find_singbox()
    if not singbox_path:
        raise SystemExit(
            "sing-box binary not found. Searched: " + ", ".join(SINGBOX_SEARCH_PATHS)
        )

    warp_pool_file = (RESULTS_DIR / "warp" / "known_good.txt").resolve()
    dialer_proxy = WARP_SOCKS_PROXY if source_file.resolve() == warp_pool_file else None
    if dialer_proxy is not None:
        if not asyncio.run(socks5_connect(
            dialer_proxy[0], dialer_proxy[1], "1.1.1.1", 443, 5.0,
        )):
            raise SystemExit(
                f"WARP SOCKS5 proxy {dialer_proxy[0]}:{dialer_proxy[1]} is not reachable; "
                "start warp-cli in proxy mode"
            )
        _log.info(
            "Gemini route: WARP SOCKS %s:%d → sing-box → live config",
            dialer_proxy[0], dialer_proxy[1],
        )
    else:
        _log.info("Gemini route: sing-box → live config (direct)")

    gemini_dir = RESULTS_DIR / "gemini"
    gemini_dir.mkdir(parents=True, exist_ok=True)
    run_date = date.today().isoformat()
    if source_file.resolve() == (RESULTS_DIR / "warp" / "known_good.txt").resolve():
        source_tag = "warp"
    elif source_file.resolve() == (RESULTS_DIR / "known_good.txt").resolve():
        source_tag = "direct"
    else:
        source_tag = "".join(c for c in source_file.stem if c.isalnum() or c in "-_") or "custom"
    report_prefix = "probe_report" if probe_only else "report"
    result_prefix = "api_reachable" if probe_only else "available"
    report_path = gemini_dir / f"{report_prefix}_{run_date}_{source_tag}.csv"
    available_path = gemini_dir / f"{result_prefix}_{run_date}_{source_tag}.txt"
    counts: Counter[str] = Counter()
    started = time.monotonic()
    stop_statuses = {"quota_limited", "api_key_error", "model_error", "account_denied"}

    progress_label = "--test-gemini-probe" if probe_only else "--test-gemini"
    _log.info(
        "%s: %d live configs from %s; model=%s; API interval=%ss",
        progress_label,
        len(configs), source_file, GEMINI_TEST_MODEL, GEMINI_TEST_INTERVAL_SECONDS,
    )
    with report_path.open("w", encoding="utf-8", newline="") as report, available_path.open(
        "w", encoding="utf-8"
    ) as available:
        writer = csv.writer(report)
        writer.writerow(("status", "http_status", "google_maps_center", "detail", "config"))
        report.flush()

        previous_finished: float | None = None
        for index, config in enumerate(configs, start=1):
            if previous_finished is not None:
                wait = GEMINI_TEST_INTERVAL_SECONDS - (time.monotonic() - previous_finished)
                if wait > 0:
                    time.sleep(wait)
            result = test_config_gemini(
                config, singbox_path, find_free_socks_port(), api_key,
                probe_only=probe_only, dialer_proxy=dialer_proxy,
            )
            previous_finished = time.monotonic()
            counts[result.status] += 1
            writer.writerow((
                result.status,
                result.http_status or "",
                result.google_center or "",
                result.detail,
                config,
            ))
            report.flush()
            success_status = "api_reachable" if probe_only else "available"
            if result.status == success_status:
                available.write(config + "\n")
                available.flush()

            _log.info(
                "%s [%d/%d] %s%s%s",
                progress_label, index, len(configs), result.status,
                f" (HTTP {result.http_status})" if result.http_status else "",
                f" — {result.detail}" if result.detail and result.status not in {
                    "available", "api_reachable",
                } else "",
            )
            if index % 5 == 0 or index == len(configs):
                summary = ", ".join(
                    f"{status}={amount}" for status, amount in sorted(counts.items())
                )
                _log.info(
                    "%s progress: %d/%d (%.0f%%) | %s | elapsed %.0fs",
                    progress_label, index, len(configs), 100 * index / len(configs), summary,
                    time.monotonic() - started,
                )
            if result.status in stop_statuses:
                _log.warning(
                    "Stopping Gemini checks after %s; remaining configs were not tested",
                    result.status,
                )
                break

    _log.info(
        "Gemini %s report: %s | configs: %s | statuses: %s",
        "probe" if probe_only else "generation",
        report_path, available_path,
        ", ".join(f"{status}={amount}" for status, amount in sorted(counts.items())) or "none",
    )


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


def cmd_subscriptions() -> None:
    """Discover source subscription links and replace the validated URL list."""
    RESULTS_DIR.mkdir(exist_ok=True)
    singbox_path = find_singbox()
    if not singbox_path:
        print("sing-box binary not found. Searched:")
        for path in SINGBOX_SEARCH_PATHS:
            print(f"  {path}")
        sys.exit(1)

    _log.info("Fetching source text for subscription URL discovery...")
    try:
        source_texts = fetch_source_texts(SOURCES_FILE)
    except GitHubRateLimitError as e:
        _log.error("GitHub rate limit prevented a complete source fetch; aborting: %s", e)
        raise SystemExit(1) from e
    urls = extract_subscription_urls(source_texts)
    _log.info("Discovered %d unique HTTP(S) URLs", len(urls))
    working_urls = validate_subscription_urls(urls, singbox_path)
    save_subscriptions(RESULTS_DIR, working_urls)
    _log.info("Saved %d working subscription URLs → results/subscriptions.txt", len(working_urls))


def cmd_test_subscriptions(subscription_index: int | None = None) -> None:
    """Test configs inside saved subscription URLs, without touching known_good."""
    subscriptions_file = RESULTS_DIR / "subscriptions.txt"
    if not subscriptions_file.exists():
        print("No subscriptions.txt found. Run --subscriptions first.")
        sys.exit(1)

    urls = [line.strip() for line in subscriptions_file.read_text(errors="replace").splitlines() if line.strip()]
    if not urls:
        print("subscriptions.txt contains no URLs.")
        sys.exit(1)

    if subscription_index is None:
        selected_urls = list(dict.fromkeys(urls))
    else:
        if subscription_index < 1 or subscription_index > len(urls):
            print(f"Subscription index must be between 1 and {len(urls)}.")
            sys.exit(2)
        selected_urls = [urls[subscription_index - 1]]
        _log.info("Testing subscription %d/%d: %s", subscription_index, len(urls), selected_urls[0])

    singbox_path = find_singbox()
    if not singbox_path:
        print("sing-box binary not found. Searched:")
        for path in SINGBOX_SEARCH_PATHS:
            print(f"  {path}")
        sys.exit(1)
    _log.info("Using sing-box: %s", singbox_path)

    configs = fetch_subscription_configs(selected_urls)
    if not configs:
        _log.warning("No parseable configs found; previous subscription config snapshot left unchanged")
        return

    _log.info("Tunnel-testing %d unique configs with strict TLS verification", len(configs))
    passed = asyncio.run(tunnel_filter(configs, singbox_path, verify_tls_cert=True))
    output = save_subscription_configs(RESULTS_DIR, passed, subscription_index)
    _log.info("Saved %d working configs → %s", len(passed), output)


def _warp_tunnel_active() -> bool:
    """True if WARP is connected in a *system-tunnel* mode (not SOCKS proxy).

    In `proxy` mode WARP only listens on a local SOCKS port, so probes still
    travel the normal ISP path and the diagnosis stays honest. In a tunnel
    mode every packet is carried out of the access network and every endpoint
    looks reachable, which silently invalidates the results.
    Best-effort: returns False when warp-cli is absent or errors out.
    """
    try:
        out = subprocess.run(
            ["warp-cli", "--accept-tos", "settings"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return False
    text = out.stdout + out.stderr
    if "Connected" not in subprocess.run(
        ["warp-cli", "--accept-tos", "status"],
        capture_output=True, text=True, timeout=5,
    ).stdout:
        return False
    mode_line = next((ln for ln in text.splitlines() if "Mode:" in ln), "")
    # "Mode: WarpProxy on port 40000" is harmless; "Warp", "Warp+doh", … tunnel.
    return bool(mode_line) and "Proxy" not in mode_line


def _parse_proxy(value: str | None) -> tuple[str, int] | None:
    """Parse "HOST:PORT" into a SOCKS5 endpoint; None when not given."""
    if not value:
        return None
    try:
        host, _, port = value.rpartition(":")
        return host.strip("[]"), int(port)
    except (ValueError, AttributeError):
        raise SystemExit(f"Invalid --proxy {value!r}: expected HOST:PORT")


def cmd_diagnose(
    sample: int | None = None,
    args_file: str | None = None,
    proxy: tuple[str, int] | None = None,
) -> None:
    """Split TCP-unreachable endpoints into ISP-blackholed vs dead servers.

    Reads candidates/known_good configs, TCP-checks them, then runs the
    TTL-capped ping probe on every endpoint that failed so the report can
    say "blocked by provider" instead of just "unreachable".
    """
    RESULTS_DIR.mkdir(exist_ok=True)
    configs: list[str] = []
    source: Path | None = Path(args_file) if args_file else None
    if source is None:
        # Prefer the broadest recheck baseline: the newest recheck usually
        # holds only survivors, which leaves nothing to diagnose.
        rechecks = [p for p in RESULTS_DIR.glob("recheck_*.txt") if p.stat().st_size]
        if rechecks:
            source = max(rechecks, key=lambda p: len(p.read_text().splitlines()))
        for fallback in ("known_good.txt", "candidates.txt"):
            if source is None:
                source = RESULTS_DIR / fallback
    if source and source.exists():
        configs = [ln for ln in source.read_text().splitlines() if ln.strip()]
    if configs:
        _log.info(f"Diagnose source: {source.name} ({len(configs)} configs)")
    else:
        print("No config file to diagnose (looked for recheck_*/known_good/candidates).")
        return
    if sample and sample < len(configs):
        configs = _random.sample(configs, sample)
        _log.info(f"Sampled {sample} configs randomly")

    by_endpoint: dict[tuple, list[str]] = {}
    for cfg in configs:
        hp = extract_host_port(cfg)
        if hp:
            by_endpoint.setdefault(hp, []).append(cfg)
    endpoints = list(by_endpoint)
    _log.info(f"TCP pre-filter over {len(endpoints)} unique endpoints...")

    alive = asyncio.run(tcp_filter(configs))
    alive_hp = {extract_host_port(c) for c in alive}
    unreachable = [hp for hp in endpoints if hp not in alive_hp]
    _log.info(f"TCP: {len(alive_hp)} alive | {len(unreachable)} unreachable")

    if not unreachable:
        print("All endpoints reachable — nothing to diagnose.")
        return

    evidence = "TTL-capped ping (silent at 5/8/12 = dropped inside access network)"
    if proxy is not None:
        _log.info(
            f"SOCKS5 egress {proxy[0]}:{proxy[1]} — an endpoint that answers "
            "through it but not directly is ISP-blocked (definitive)"
        )
        if not asyncio.run(socks5_connect(proxy[0], proxy[1], "1.1.1.1", 443, 5.0)):
            _log.warning("SOCKS egress is not usable; falling back to ping probes")
            proxy = None
        else:
            evidence = (
                f"SOCKS5 egress {proxy[0]}:{proxy[1]} reachable while direct times out "
                "(definitive); ping probe as fallback"
            )
    _log.info(f"Evidence: {evidence}")
    if _warp_tunnel_active():
        _log.warning(
            "WARP is active in system-tunnel mode — probes will ride the tunnel "
            "and every endpoint will look reachable. Use 'warp-cli mode proxy' "
            "or disconnect WARP for an honest diagnosis."
        )
    verdicts = asyncio.run(classify_endpoints(unreachable, proxy=proxy))

    counts: Counter = Counter(verdicts.values())
    tag = Path(source).stem  # e.g. "recheck_2026-11-04"
    out_file = RESULTS_DIR / f"diagnose_{tag}_{date.today().isoformat()}.txt"
    with open(out_file, "w") as fh:
        fh.write(f"# blackhole diagnosis {source.name} {date.today().isoformat()}\n")
        fh.write(f"# evidence: {evidence}\n")
        fh.write("# blocked_by_isp = the packet never leaves our access network:\n")
        fh.write("#   unreachable *from here* regardless of server state — a host may be\n")
        fh.write("#   blackholed locally AND dead at the same time (check abroad to separate).\n")
        fh.write("# server_dead    = a router answered, so the route is clear and the host\n")
        fh.write("#   or port simply does not answer.\n")
        for status in ("blocked_by_isp", "server_dead", "unknown"):
            for hp, v in sorted(verdicts.items(), key=lambda kv: (kv[1], kv[0])):
                if v != status:
                    continue
                fh.write(f"{status}\t{hp[0]}:{hp[1]}\n")
    summary = ", ".join(f"{k}={v}" for k, v in counts.most_common())
    _log.info(f"Diagnosis: {len(verdicts)} endpoints → {summary}")
    print(f"\n{summary}\nreport: {out_file}")


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
    mode.add_argument("--test-warp", action="store_true",
                      help="Tunnel test candidates.txt through warp-cli SOCKS → results/warp/")
    mode.add_argument("--test-gemini", nargs="?", const=str(RESULTS_DIR / "known_good.txt"),
                      metavar="FILE",
                      help="Test Gemini API through live configs (default: results/known_good.txt)")
    mode.add_argument("--test-gemini-probe", nargs="?",
                      const=str(RESULTS_DIR / "known_good.txt"), metavar="FILE",
                      help="Check Gemini API with countTokens (no model inference)")
    mode.add_argument("--full", action="store_true", help="Run --collect then --test")
    mode.add_argument("--recheck", action="store_true", help="Re-test known_good.txt → recheck_YYYY-MM-DD.txt (known_good untouched)")
    mode.add_argument("--subscriptions", action="store_true", help="Discover and validate subscription URLs from configured sources")
    mode.add_argument("--test-subscriptions", action="store_true", help="Test every config from saved subscription URLs → subscription_configs.txt")
    mode.add_argument("--test-subscription", type=int, metavar="INDEX", help="Test one 1-based URL row from subscriptions.txt → subscription_configs_INDEX.txt")
    mode.add_argument("--stats", action="store_true", help="Show counts per result file")
    mode.add_argument("--diagnose", nargs="?", const="", metavar="FILE",
                      help="Split TCP-unreachable endpoints into ISP-blackholed vs dead servers "
                           "(TTL ping probe); optional FILE, defaults to the broadest recheck")
    mode.add_argument("--setup-tg", action="store_true", help="Authenticate Telegram (interactive)")
    parser.add_argument("--add-source", metavar="SOURCE", help="Add GitHub repo (user/repo) or raw URL")
    parser.add_argument("--sync-stars", metavar="USERNAME", help="Sync GitHub starred repos")
    parser.add_argument("--sample", type=int, metavar="N",
                        help="Randomly sample N configs (--test-gemini defaults to 10)")
    parser.add_argument("--proxy", metavar="HOST:PORT",
                        help="--diagnose only: SOCKS5 egress to prove an endpoint is "
                             "ISP-blocked rather than dead (e.g. WARP 127.0.0.1:40000)")
    parser.add_argument(
        "--update-known-good",
        action="store_true",
        help="Used with --recheck: overwrite known_good.txt with only surviving configs",
    )
    args = parser.parse_args()

    if not any([args.collect, args.test, args.test_warp, args.test_gemini,
                args.test_gemini_probe, args.full, args.recheck, args.subscriptions,
                args.test_subscriptions, args.test_subscription is not None,
                args.stats, args.diagnose is not None, args.add_source, args.sync_stars, args.setup_tg]):
        parser.print_help()
        return

    _setup_logging()

    if args.collect:
        cmd_collect(sample=args.sample)
    elif args.test:
        cmd_test()
    elif args.test_warp:
        cmd_test_warp()
    elif args.test_gemini:
        cmd_test_gemini(source_file=Path(args.test_gemini), sample=args.sample)
    elif args.test_gemini_probe:
        cmd_test_gemini(
            source_file=Path(args.test_gemini_probe), sample=args.sample, probe_only=True,
        )
    elif args.full:
        cmd_full(sample=args.sample)
    elif args.recheck:
        cmd_recheck(update_known_good=args.update_known_good)
    elif args.subscriptions:
        cmd_subscriptions()
    elif args.test_subscriptions:
        cmd_test_subscriptions()
    elif args.test_subscription is not None:
        cmd_test_subscriptions(subscription_index=args.test_subscription)
    elif args.stats:
        cmd_stats()
    elif args.diagnose is not None:
        cmd_diagnose(sample=args.sample, args_file=args.diagnose or None,
                     proxy=_parse_proxy(args.proxy))
    elif args.setup_tg:
        cmd_setup_tg()
    elif args.add_source:
        added = add_source(args.add_source, SOURCES_FILE)
        print("Added." if added else "Already exists.")
    elif args.sync_stars:
        try:
            count = sync_stars(args.sync_stars, SOURCES_FILE, force=True)
        except GitHubRateLimitError as e:
            _log.error("GitHub star sync stopped after rate-limit retries: %s", e)
            raise SystemExit(1) from e
        print(f"Added {count} new repo(s) from stars.")


if __name__ == "__main__":
    main()
