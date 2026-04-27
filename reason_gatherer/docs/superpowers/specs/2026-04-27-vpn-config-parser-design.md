# VPN Config Parser — Design Spec
**Date:** 2026-04-27  
**Status:** Approved

---

## Overview

A modular Python tool that collects free VPN configurations from GitHub repositories and direct URLs, filters them through a two-stage test pipeline, deduplicates against historical results, and outputs a plain-text list ready to paste into Throne.

---

## Project Structure

```
vpn_collector/
├── main.py              # CLI entry point: --collect, --test, --full
├── config.py            # Constants: sources, thresholds, file paths
├── sources.py           # Fetches configs from GitHub repos and direct URLs
├── parser.py            # Protocol recognition, format validation, VPN-file detection
├── tester.py            # Two-stage testing: TCP + sing-box tunnel
├── storage.py           # 5-file FIFO rotation + known_good.txt, deduplication
├── results/
│   ├── candidates.txt   # TCP-passed configs (intermediate)
│   ├── known_good.txt   # Permanent file of all verified servers
│   └── run_YYYY-MM-DD.txt  # Up to 5 dated run files (FIFO rotation)
└── logs/
    └── vpn_collector.log
```

---

## Sources

**From user's starred GitHub repos:**
- `VP01596/vless-top15`
- `qopq1366/VlessConfig`
- `Vovo4ka000/V4kVPN`
- `MustafaBaqer/VestraNet-Nodes`
- `Mr-Meshky/vify`
- `kasesm/Free-Config`
- `igareck/vpn-configs-for-russia`
- `LalatinaHub/Mineral`
- `luxxuria/harvester`

**Additional quality public sources:**
- `mahdibland/V2RayAggregator`
- `barry-far/V2RayAggregator`
- `freefq/free`
- `peasoft/NoMoreVPN`

Each repo is scanned for files via GitHub raw content API. Files are filtered before processing (see Parser section).

---

## Module: `parser.py`

### VPN-File Detection

A file is treated as a VPN config list if **at least one** condition is met:
- Contains ≥3 lines matching a VPN protocol prefix (`vless://`, `vmess://`, `trojan://`, `ss://`, `hysteria://`, `hysteria2://`, `hy2://`, `tuic://`)
- Is a base64 string that after decoding contains such lines
- The file path contains words: `sub`, `config`, `proxy`, `nodes`, `mix`

Files are **skipped** if:
- Filename matches: `README*`, `requirements*`, `*.yml`, `*.yaml`, `*.json`, `*.md`, `LICENSE*`, `*.html`, `vercel.json`
- Content contains no VPN prefix after base64 decode attempt

### Supported Protocols

| Protocol | Prefix | Notes |
|----------|--------|-------|
| VLESS | `vless://` | |
| VMess | `vmess://` | base64-encoded JSON payload |
| Trojan | `trojan://` | |
| Shadowsocks | `ss://` | may be base64 |
| Hysteria | `hysteria://` | |
| Hysteria2 | `hysteria2://`, `hy2://` | |
| TUIC | `tuic://` | |

### Parsed Fields (internal use only)

From `proto://credentials@host:port?params#name`:
- `protocol`, `host`, `port`, `credentials`, `params`, `name`

Output files always contain the **original config string** with only the `#name` portion modified.

---

## Module: `tester.py`

### Stage 1 — TCP Pre-filter (fast)

- Async TCP connection attempt to `host:port`, timeout 5s
- Up to 50 concurrent connections via `asyncio`
- Output: `candidates.txt`

### Stage 2 — Tunnel Test via sing-box (thorough)

**sing-box discovery:** Auto-locate binary in Throne's installation directory (search common paths: `/opt/throne/`, `/usr/local/bin/`, `~/.local/share/throne/`, `~/throne/`).

**Per-config test sequence:**
1. Generate temporary `singbox_config_{port}.json` with SOCKS5 outbound on a random local port (10000–19999)
2. Launch sing-box subprocess, wait up to 3s for readiness
3. **Speedtest:** HTTP GET `http://speedtest.tele2.net/1MB.bin` via SOCKS5, measure throughput
   - Threshold: discard if speed < 1 Mbit/s
4. **Claude.com check** (only if speed passed): HTTP GET `https://claude.com/` via same SOCKS5
   - Check final URL after redirects for: `unavailable`, `blocked`, `region`, `restricted`
   - Check HTML body for: `app unavailable in region`, `not available in your region`, `unavailable in your country`, `access restricted`
   - Check HTTP status code `451`
   - Any match → mark `---`, otherwise `+++`
5. Kill sing-box subprocess, delete temporary config

**Parallelism:** Up to 5 concurrent tunnel tests (each on its own port).

**Failure handling:** Tunnel connection timeout/error → mark `---`, excluded from `known_good.txt`.

### Output Name Format

Original config string with modified `#name`:
```
vless://uuid@host:port?params#+++original_name    ← claude.com accessible
vless://uuid@host:port?params#---original_name    ← claude.com blocked/unreachable
```

---

## Module: `storage.py`

### Deduplication Key

`host:port` extracted from the config string. Prevents duplicates even when `#name` differs across sources.

### Write Logic

1. Extract `host:port` from new config
2. Check against `known_good.txt` + all existing `run_*.txt` files
3. If found → skip
4. If new → append to current `run_YYYY-MM-DD.txt` and `known_good.txt`

### File Rotation

- Maximum 5 `run_*.txt` files
- On creation of 6th → oldest deleted
- `known_good.txt` is **never deleted or rotated**

### `known_good.txt` Header

```
# Updated: 2026-04-27 14:32:11 | Total: 247
vless://...#+++name
trojan://...#---name
```

---

## Module: `main.py` — CLI

```
python main.py --collect          # Stage 1: fetch sources, TCP filter → candidates.txt
python main.py --test             # Stage 2: tunnel test candidates.txt → known_good.txt
python main.py --full             # Both stages sequentially
python main.py --stats            # Show counts per run file and known_good.txt
```

---

## Module: `config.py`

Key constants:
- `TCP_TIMEOUT = 5` (seconds)
- `TCP_CONCURRENCY = 50`
- `TUNNEL_CONCURRENCY = 5`
- `MIN_SPEED_MBPS = 1.0`
- `SINGBOX_SEARCH_PATHS = [...]`
- `MAX_RUN_FILES = 5`
- `RESULTS_DIR = "results/"`
- `SPEEDTEST_URL = "http://speedtest.tele2.net/1MB.bin"`
- `CLAUDE_CHECK_URL = "https://claude.com/"`
- `CLAUDE_BLOCK_KEYWORDS = ["app unavailable in region", "not available in your region", "unavailable in your country", "access restricted"]`
- `CLAUDE_BLOCK_URL_KEYWORDS = ["unavailable", "blocked", "region", "restricted"]`

---

## Error Handling

- Network errors during collection: log warning, skip source, continue
- sing-box binary not found: abort Stage 2 with clear error message showing searched paths
- sing-box startup failure for a config: mark as failed, continue to next
- Malformed config string (can't parse host:port): skip silently, log debug
- File write errors: log error, abort

---

## Dependencies

- Python 3.10+
- `aiohttp` — async HTTP requests
- `aiofiles` — async file I/O
- `requests` — sync HTTP for speedtest measurement
- `pysocks` — SOCKS5 proxy support
- `tqdm` — progress bars
- External binary: `sing-box` (bundled with Throne, auto-discovered)
