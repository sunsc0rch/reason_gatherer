# reason_gatherer / vpn_collector

Scrapes free VPN configs from GitHub repositories, filters them by TCP reachability and tunnel quality (speed + Claude.com access), and saves verified configs to rotating result files.

## Verified configs (updated every 2–3 days)

| File | Description |
|---|---|
| [**known_good.txt**](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/known_good.txt) | All verified configs ever collected — use as subscription URL |
| [run_2026-07-13.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/run_2026-07-13.txt) | Latest run |
| [run_2026-07-09.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/run_2026-07-09.txt) | Previous run |
| [run_2026-07-06.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/run_2026-07-06.txt) | Earlier run |
| [run_2026-06-30.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/run_2026-06-30.txt) | Earlier run |
| [run_2026-06-24.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/run_2026-06-24.txt) | Earlier run |
| [recheck_2026-05-25.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/recheck_2026-05-25.txt) | Latest recheck (configs re-verified from known_good) |

Configs marked `+++` passed the Claude.com access check (unblocked from Russia). Configs marked `---` passed the speed test but Claude.com was blocked through them.

---

## AmneziaWG configs (for AmneziaVPN 1.0.1)

A separate collector scrapes and tunnel-tests AmneziaWG configs from community sources and packages the fastest ones for direct import into the Amnezia app.

| File | Description |
|---|---|
| [**all_configs.zip**](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results_awg/all_configs.zip) | Top 50 fastest AWG configs — import directly into AmneziaVPN |

**Import:** Amnezia app → Add VPN → From file → `all_configs.zip`

Each config is real-tunnel-tested (handshake verified + speed ≥ 1 Mbit/s). The full pool of verified configs (`results_awg/known_good/`) contains all passing configs; the archive is rebuilt to include only the 50 fastest after each run.

Sources: Telegram [@amnezia_wg](https://t.me/amnezia_wg), [@vpnconfigsgive](https://t.me/vpnconfigsgive), [Delta-Kronecker/WARP-Config](https://github.com/Delta-Kronecker/WARP-Config).

**Dependencies:**

| Dependency | Purpose |
|---|---|
| `requests` | HTTP fetching of configs and ZIP archives |
| `telethon` | Scraping Telegram channels (optional — skipped if absent) |
| `amneziawg-go` | Userspace AWG daemon for tunnel testing (binary, not pip) |
| `awg`, `awg-quick` | AWG CLI tools — part of [amneziawg-tools](https://github.com/amnezia-vpn/amneziawg-tools) |

```bash
# Python deps (already in requirements.txt)
pip install requests telethon

# amneziawg-go — build from source (requires Go 1.25+)
git clone https://github.com/amnezia-vpn/amneziawg-go
cd amneziawg-go && GOPROXY=https://goproxy.io,direct make && sudo cp amneziawg-go /usr/local/bin/

# awg / awg-quick — build from source
git clone https://github.com/amnezia-vpn/amneziawg-tools
cd amneziawg-tools && make && sudo make install

# Allow awg-quick to run without password (required for tunnel testing)
echo "$USER ALL=(ALL) NOPASSWD: /usr/local/bin/awg,/usr/local/bin/awg-quick,/usr/bin/ip,/usr/bin/curl" \
  | sudo tee /etc/sudoers.d/awg_collector
```

```bash
# Fetch + test all sources, update known_good pool
python -m awg_collector.main --collect

# Re-verify existing pool, remove dead configs
python -m awg_collector.main --recheck

# Rebuild archive from current pool (top 50 by speed)
python -m awg_collector.main --export

# Stats
python -m awg_collector.main --stats
```

---

## How it works

```
GitHub repos / raw URLs / Telegram channels
        ↓
  sync_stars + fetch_all_configs   — auto-syncs starred repos, deduplicates
        ↓
   TCP pre-filter                  — async TCP check per unique host:port
        ↓
   candidates.txt                  — checkpoint: survives interruption
        ↓
  sing-box tunnel test             — real tunnel: speedtest ≥ 1 Mbit/s + Claude.com check
        ↓
  known_good.txt                   — permanent log of all verified configs
  run_YYYY-MM-DD.txt               — dated run file (last 5 kept)
```

## Requirements

- Python 3.10+
- [sing-box](https://github.com/SagerNet/sing-box) binary (auto-discovered from common install paths)

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Full run: fetch → TCP filter → tunnel test
python -m vpn_collector.main --full

# Step by step:
python -m vpn_collector.main --collect        # fetch and TCP-filter → candidates.txt
python -m vpn_collector.main --test           # tunnel-test candidates.txt → known_good.txt

# Quick run on a random subset
python -m vpn_collector.main --collect --sample 30000
python -m vpn_collector.main --full    --sample 50000

# Re-verify existing known_good configs (check if still alive)
python -m vpn_collector.main --recheck        # → recheck_YYYY-MM-DD.txt (known_good untouched)

# Manage sources
python -m vpn_collector.main --add-source user/repo          # add GitHub repo
python -m vpn_collector.main --add-source https://example.com/sub.txt  # add raw URL
python -m vpn_collector.main --add-source t.me/channelname   # add Telegram channel
python -m vpn_collector.main --sync-stars <github_username>  # manually sync starred repos

# Telegram setup (one-time, requires api_id + api_hash from my.telegram.org)
python -m vpn_collector.main --setup-tg

# Stats
python -m vpn_collector.main --stats
```

## Output

```
results/
├── known_good.txt           # all verified configs ever found (never deleted)
├── run_YYYY-MM-DD.txt       # up to 5 dated run files (oldest auto-deleted)
├── recheck_YYYY-MM-DD.txt   # on-demand recheck results from known_good
├── candidates.txt           # TCP-passed queue (intermediate, not tracked in git)
└── tcp_cache.txt            # TCP-verified host:ports cache (not tracked in git)
```

`known_good.txt` is never overwritten. Paste the raw URL into Throne / Hiddify as a subscription source.

## Telegram sources

Telegram channels are an optional additional source of configs.

**One-time setup:**

```bash
pip install telethon>=1.36
python -m vpn_collector.main --setup-tg   # logs in via phone + SMS code
```

Credentials are stored in `~/.config/vpn_collector/tg_auth.json` (mode 600) and the session in `~/.config/vpn_collector/tg.session` — never inside the repo.

**Add channels:**

```bash
python -m vpn_collector.main --add-source t.me/channelname
```

Accepted formats: `t.me/name`, `t.me/s/name`, `https://t.me/name`. The last 50 posts per channel are scanned for VPN configs on every `--collect` run.

If Telethon is not installed or setup was not run, `--collect` continues normally without TG — no crash.

> **Behind a proxy:** Telethon reads `ALL_PROXY` / `HTTPS_PROXY` env vars automatically (`socks5://`, `socks4://`, `http://`). If your Throne/sing-box proxy is not in the environment, prefix the command: `ALL_PROXY=socks5://127.0.0.1:<port> python -m vpn_collector.main --setup-tg`

## Configuration

All tunable parameters are in `vpn_collector/config.py`:

| Parameter | Default | Description |
|---|---|---|
| `TCP_CONCURRENCY` | 100 | Parallel TCP checks |
| `TCP_TIMEOUT` | 4.0s | TCP connection timeout |
| `TCP_BATCH_SIZE` | 5000 | Configs per checkpoint batch |
| `TUNNEL_CONCURRENCY` | 20 | Parallel sing-box tunnel tests |
| `MIN_SPEED_MBPS` | 1.0 | Minimum acceptable tunnel speed |
| `SINGBOX_STARTUP_TIMEOUT` | 3.0s | Max wait for sing-box SOCKS port |
| `SPEEDTEST_EARLY_ABORT_AFTER` | 4.0s | Early abort speedtest after this many seconds |
| `SPEEDTEST_EARLY_ABORT_FACTOR` | 0.5 | Abort if speed < factor × MIN_SPEED_MBPS |

## Auto-push

Results are pushed to this repository automatically every 2 days via cron:

```bash
# Manually trigger push
bash scripts/git_push_results.sh
```

## Logs

```
logs/vpn_collector.log   # main log
logs/autopush.log        # auto-push cron log
```
