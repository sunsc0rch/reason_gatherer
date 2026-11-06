# Subscription Test Accuracy and Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make subscription checks accurately configure supported transports and explain failures.

**Architecture:** Keep sing-box as the engine, add HTTPUpgrade mapping, and fail clearly on upstream-unsupported XHTTP. Use structured probe results and captured sing-box errors to produce per-run failure categories without changing the successful-node output format.

**Tech Stack:** Python, sing-box 1.13.11, pytest.

**Spec:** `docs/superpowers/specs/2026-11-06-subscription-test-diagnostics-design.md`

## Global Constraints

- Strict TLS validation remains enabled in subscription modes.
- XHTTP must not be mapped to another transport; mark it unsupported by the selected sing-box engine.
- Never include credentials or full share links in diagnostic examples.
- Keep the existing float speed-test helper and config-test return shape compatible.

## Review Focus

- `type=xhttp`: must be reported unsupported rather than tested as TCP.
- `type=httpupgrade`: must preserve path and HTTP Host value.
- Failed speed-test requests: must not be called low-speed measurements.
- TLS certificate failures: must be surfaced from sing-box output.
- Repeated tunnel-filter calls: counters must reset per run.

### Task 1: Transport support and unsupported transport reporting

**Files:** `vpn_collector/tester.py`, `tests/test_tester.py`

- [x] Add failing tests for HTTPUpgrade mapping and explicit XHTTP rejection.
- [x] Run those tests and confirm failure.
- [x] Add HTTPUpgrade mapping and a dedicated unsupported-transport exception.
- [x] Run focused transport tests.

### Task 2: Probe outcomes and per-run failure diagnostics

**Files:** `vpn_collector/tester.py`, `tests/test_tester.py`

- [x] Add failing tests distinguishing a request failure from a measured low-speed result, plus TLS error classification.
- [x] Run those tests and confirm failure.
- [x] Add structured internal probe outcomes, capture per-process sing-box stderr, classify failures, and keep compatibility wrappers.
- [x] Run focused tester and subscription tests. Full-suite `pytest -x -q` stops at an unrelated AWG archive extension assertion; see ledger.

### Task 3: Recheck the affected feed

**Files:** `results/subscription_configs_5.txt` (generated output only)

- [x] Run `--test-subscription 5` with the improved diagnostics.
- [x] Report counts by failure cause and the resulting passing-node count.
