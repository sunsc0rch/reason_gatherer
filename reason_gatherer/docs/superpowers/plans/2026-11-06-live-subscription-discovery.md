# Live Subscription Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent `--subscriptions` command that discovers third-party subscription URLs in configured sources, validates them, and writes working URLs to `results/subscriptions.txt`.

**Architecture:** Add source-text retrieval for configured GitHub repositories, direct URLs, and Telegram channels; extract unique HTTP(S) links; fetch and parse candidate subscription bodies; use the existing tunnel tester with certificate verification enabled for this command only. The command replaces the dedicated output file and does not invoke static collection or recheck.

**Tech Stack:** Python 3.10+, requests, asyncio, existing VPN parser and sing-box tunnel tester, argparse.

**Spec:** `docs/superpowers/specs/2026-11-06-live-subscription-discovery-design.md`

## Global Constraints

- The entire operation runs only through `--subscriptions`.
- Include a URL only when its response parses into supported configs and at least one config passes the full tunnel test with valid TLS certificates.
- Store URLs, not expanded config lines, in `results/subscriptions.txt`.
- Rebuild the output file from current results and deduplicate URLs.
- Preserve existing static-config and recheck behavior.

## Review Focus

- Ordinary web links and malformed URLs must not be treated as subscriptions.
- Subscription responses may be base64 encoded or Clash YAML, as supported by the existing parser.
- A subscription with parseable nodes but no tunnel-tested survivors must be omitted.
- TLS certificate verification must be strict in this mode and not change existing collection/recheck modes.
- Telegram may be unconfigured or unavailable; this must not prevent GitHub and URL sources from being scanned.

---

## File Map

- `vpn_collector/sources.py`: expose source text retrieval for repositories and direct URL sources without changing `fetch_all_configs` behavior.
- `vpn_collector/tg_source.py`: expose recent Telegram post text for configured channels while preserving existing config-fetch API.
- `vpn_collector/tester.py`: allow callers to request strict TLS certificate validation; keep the current default for existing commands.
- `vpn_collector/subscriptions.py`: extract links, fetch and parse subscription bodies, test candidate nodes, and replace the URL output file.
- `vpn_collector/main.py`: add the mutually exclusive `--subscriptions` command and run the new collector.
- `scripts/git_push_results.sh`, `README.md`: publish and document the separate subscription URL list and command.

### Task 1: Retrieve source text for subscription discovery

**Files:** `vpn_collector/sources.py`, `vpn_collector/tg_source.py`

- [x] Add helpers to retrieve textual GitHub repository files and direct URL response bodies for the configured source list, retaining per-source error isolation.
- [x] Add a Telegram helper that returns the text of the latest configured-channel posts; return an empty result when Telegram is unavailable, unconfigured, or a channel fails.
- [x] Keep existing config-fetch functions and their behavior unchanged; the new CLI path will consume the source-text helpers.

### Task 2: Support strict TLS validation on demand

**Files:** `vpn_collector/tester.py`

- [x] Add an optional strict-certificate setting to sing-box config generation and tunnel-testing entry points. When enabled, TLS outbounds omit `insecure: true`; when disabled, preserve current behavior.
- [x] Thread the setting through `tunnel_filter` to individual tests without changing defaults used by current commands.

### Task 3: Discover, validate, and save subscriptions

**Files:** `vpn_collector/subscriptions.py`, `vpn_collector/config.py`, `vpn_collector/storage.py`

- [x] Add URL extraction that accepts only HTTP(S), removes trailing punctuation, and deduplicates candidate links across all source text.
- [x] Add a collector that fetches each candidate, parses its response with `parse_configs_from_content`, and tests its parsed nodes with strict TLS enabled. Mark the candidate valid if at least one node passes.
- [x] Bound per-subscription node checks to a documented implementation constant so oversized feeds cannot monopolize one run.
- [x] Replace `results/subscriptions.txt` with only validated, unique subscription URLs, including an empty file when no candidates pass.
- [x] Log counts for discovered URLs, fetched/parseable subscriptions, and validated subscriptions; isolate individual URL failures.

### Task 4: Add the isolated CLI entry point and publish the output

**Files:** `vpn_collector/main.py`, `scripts/git_push_results.sh`, `README.md`

- [x] Add `--subscriptions` to the mutually exclusive CLI modes and dispatch it to the new collector using `SOURCES_FILE`, `RESULTS_DIR`, and discovered sing-box.
- [x] Ensure this mode does not call `cmd_collect`, `cmd_test`, `cmd_full`, or `cmd_recheck`.
- [x] Add `results/subscriptions.txt` to the results push script and add a README entry explaining that it contains source subscription URLs vetted by the collector.
- [x] Document `python -m vpn_collector.main --subscriptions` as an independent command.
