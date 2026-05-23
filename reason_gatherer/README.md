# reason_gatherer / vpn_collector

Scrapes free VPN configs from GitHub repositories, filters them by TCP reachability and tunnel quality (speed + Claude.com access), and saves verified configs to rotating result files.

## Verified configs (updated every 2–3 days)

| File | Description |
|---|---|
| [**known_good.txt**](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/known_good.txt) | All verified configs ever collected — use as subscription URL |
| [run_2026-05-22.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/run_2026-05-22.txt) | Latest run |
| [run_2026-05-18.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/run_2026-05-18.txt) | Previous run |
| [run_2026-05-15.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/run_2026-05-15.txt) | Earlier run |
| [run_2026-05-13.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/run_2026-05-13.txt) | Earlier run |
| [run_2026-05-07.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/run_2026-05-07.txt) | Earlier run |
| [recheck_2026-05-20.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/recheck_2026-05-20.txt) | Latest recheck (configs re-verified from known_good) |

Configs marked `+++` passed the Claude.com access check (unblocked from Russia). Configs marked `---` passed the speed test but Claude.com was blocked through them.

## How it works

```
GitHub repos / raw URLs
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
python -m vpn_collector.main --sync-stars <github_username>  # manually sync starred repos

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
