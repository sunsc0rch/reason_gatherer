# VPN Collector WARP Testing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Keep `--test` on the direct route and add `--test-warp` through the local warp-cli SOCKS5 proxy with isolated output.

**Architecture:** Parameterize sing-box config generation and tunnel testing with an optional SOCKS dialer outbound. Keep direct testing's clean environment and add a system-WARP guard; run WARP tests only after a working SOCKS preflight, skip UDP-only protocols with an explicit category, and persist results under `results/warp/`.

**Tech Stack:** Python 3, argparse, asyncio, sing-box 1.13.11, pytest.

**Spec:** `docs/superpowers/specs/2026-11-18-vpn-collector-warp-testing-design.md`

## Global Constraints

- `--test` bypasses HTTP/SOCKS proxy environment variables and stops if `warp-cli` reports a connected system-tunnel mode.
- `--test-warp` uses `127.0.0.1:40000`, checks TCP CONNECT to `1.1.1.1:443` before testing, and never changes WARP mode or system routes.
- WARP results are confined to `results/warp/`; WARP tests do not update direct result files, metadata, or `candidates.txt`.
- Hysteria, Hysteria2, Hy2, and TUIC are reported as `warp_udp_unsupported` because the local WARP SOCKS5 service rejects UDP_ASSOCIATE.
- A Shadowsocks URL with an empty query marker after its port, such as `ss://…@host:26179?#name`, parses as port `26179`.

## Review Focus

- WARP proxy unavailable: preflight exits before candidate testing or result writes (Task 4).
- System WARP tunnel active: direct `--test` exits before testing; `WarpProxy` mode remains allowed (Task 2).
- Proxy variables in upper- and lowercase: sing-box's direct child environment contains none of them (Task 2).
- UDP-only protocols in WARP mode: they receive `warp_udp_unsupported` without starting sing-box (Task 3).
- WARP successes already saved in `results/warp/` must not make direct candidates look verified (Task 4).

---

### Task 1: Fix empty-query Shadowsocks port parsing

**Files:**
- Modify: `vpn_collector/tester.py:_parse_ss`
- Test: `tests/test_tester.py`

**Interfaces:**
- Consumes: existing `generate_singbox_config(config_line, socks_port, verify_tls_cert=False)`.
- Produces: unchanged interface; `_parse_ss` handles an empty query marker while preserving decoded method, password, host, and port.

- [x] **Step 1: Add `test_ss_url_with_empty_query_marker_parses_port`** using `ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTo3OGI2ZTkzZTU0MjI1ODAz@51.75.168.50:26179?#name`; assert server is `51.75.168.50`, port is `26179`, method is `chacha20-ietf-poly1305`, and the password is preserved.
- [x] **Step 2: Run the new test and confirm it fails with `ValueError` for `'26179?'`.**
- [x] **Step 3: Update `_parse_ss` to use the parsed URL host and port for standard share links, retaining support for existing encoded and plain user-info forms.**
- [x] **Step 4: Run the new test and the existing Shadowsocks parser tests.**

### Task 2: Enforce direct routing for `--test`

**Files:**
- Modify: `vpn_collector/main.py:cmd_test`
- Test: `tests/test_tester.py`
- Test: `tests/test_main_privileged.py` or a focused `tests/test_main_test_modes.py`

**Interfaces:**
- Consumes: existing `_warp_tunnel_active()` and `PROXY_ENV_VARS` handling in `test_config_tunnel`.
- Produces: `cmd_test()` refuses to run when WARP reports a connected system-tunnel mode; proxy mode remains allowed.

- [x] **Step 1: Add a test that sets all proxy environment variables, runs a successful mocked `test_config_tunnel`, captures `subprocess.Popen`'s `env`, and asserts all names in `PROXY_ENV_VARS` are absent.**
- [x] **Step 2: Run the environment test and confirm it passes against the current clean child environment.**
- [x] **Step 3: Add a test that makes `_warp_tunnel_active()` return true and asserts `cmd_test()` exits before finding sing-box or invoking `tunnel_filter`; add the complementary case that proxy mode does not trigger the guard.**
- [x] **Step 4: Run the new guard test and confirm the active-tunnel case fails because the guard is missing.**
- [x] **Step 5: Add the guard at the start of `cmd_test()` before creating or modifying result files; keep `test_config_tunnel`'s clean child environment intact.**
- [x] **Step 6: Run the focused direct-route tests and existing `cmd_test` metadata tests.**

### Task 3: Add WARP dialer support and UDP-only classification

**Files:**
- Modify: `vpn_collector/tester.py:generate_singbox_config`
- Modify: `vpn_collector/tester.py:test_config_tunnel`
- Modify: `vpn_collector/tester.py:tunnel_filter`
- Test: `tests/test_tester.py`

**Interfaces:**
- Consumes: local WARP SOCKS endpoint as `dialer_proxy: tuple[str, int] | None`.
- Produces: `generate_singbox_config(..., dialer_proxy=None)` retains the current one-outbound shape; when supplied, it adds a SOCKS outbound tagged `warp-dialer` and sets the candidate outbound's `detour` to that tag. `test_config_tunnel` and `tunnel_filter` accept and forward the same optional endpoint.

- [x] **Step 1: Add a config-generation test that passes `dialer_proxy=("127.0.0.1", 40000)` and asserts the candidate outbound has `detour="warp-dialer"` and a SOCKS5 outbound targets that endpoint.**
- [x] **Step 2: Run the test and confirm it fails because the optional dialer behavior is missing.**
- [x] **Step 3: Add a `test_config_tunnel` test that passes each of `hysteria://`, `hysteria2://`, `hy2://`, and `tuic://` with a dialer proxy; assert `on_failure` receives `warp_udp_unsupported` and `subprocess.Popen` is never called.**
- [x] **Step 4: Run the UDP test and confirm it fails before implementation.**
- [x] **Step 5: Implement the optional SOCKS outbound/detour and record UDP-only skips through the existing failure diagnostics.**
- [x] **Step 6: Validate a generated WARP config with the installed sing-box 1.13.11, then run focused tunnel/parser tests.**

### Task 4: Add `--test-warp` and isolated result storage

**Files:**
- Modify: `vpn_collector/main.py:cmd_test` and `main`
- Modify: `vpn_collector/storage.py` only if an existing helper cannot safely write to a supplied result directory
- Test: `tests/test_main_test_modes.py`

**Interfaces:**
- Consumes: `tunnel_filter(..., dialer_proxy=...)` from Task 3 and existing `save_config`, `load_known_hosts`, and `rotate_run_files`.
- Produces: `cmd_test_warp(proxy=("127.0.0.1", 40000))`; `--test-warp` calls it as a mutually exclusive mode. It reads `results/candidates.txt`, checks WARP-local duplicates, and writes only under `results/warp/`.

- [x] **Step 1: Add a CLI test that `--test-warp` is mutually exclusive with `--test`.**
- [x] **Step 2: Add a command test where SOCKS preflight fails; assert no tunnel test starts and no file is written under the WARP result directory.**
- [x] **Step 3: Add a success-path test; assert pass results are written to `results/warp/known_good.txt` and `results/warp/run_<date>.txt`, with direct files, metadata, and `candidates.txt` unchanged.**
- [x] **Step 4: Add a deduplication test proving WARP-known endpoints are skipped on a later WARP run but remain eligible for direct testing.**
- [x] **Step 5: Implement `cmd_test_warp(proxy=("127.0.0.1", 40000))`: create the WARP directory only after preflight succeeds, load its own known hosts, forward the dialer proxy, persist passes with the existing storage helpers against the WARP directory, and rotate only WARP run files.**
- [x] **Step 6: Add `--test-warp` to the mutually exclusive argparse group and dispatch it from `main()`.**
- [x] **Step 7: Run focused CLI and storage tests, then run an actual one-candidate TCP smoke test through the already-active local WARP SOCKS proxy.**

### Task 5: Document the two test routes and verify the suite

**Files:**
- Modify: `README.md`
- Test: `tests/test_tester.py`
- Test: `tests/test_main_test_modes.py`

**Interfaces:**
- Consumes: shipped command names and output paths from Tasks 2–4.
- Produces: README usage for direct `--test` and WARP `--test-warp`, including output separation and unsupported UDP-only protocols.

- [x] **Step 1: Add a short README section and command example describing when to run `--test-warp` and where its results are stored.**
- [x] **Step 2: Document that the WARP SOCKS proxy must be in proxy mode and that Hysteria/Hysteria2/Hy2/TUIC are skipped because UDP_ASSOCIATE is unsupported.**
- [x] **Step 3: Run focused tests for all changed behaviors and the full pytest suite.**
- [x] **Step 4: Run `git diff --check` and inspect the final diff to confirm no result data or unrelated user changes were modified.**
