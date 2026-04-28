# reason_gatherer / vpn_collector

Scrapes free VPN configs from GitHub repositories, filters them by TCP reachability and tunnel quality (speed + Claude.com access), and saves verified configs to rotating result files.

## How it works

```
GitHub repos / raw URLs
        ↓
  fetch_all_configs        — collects configs via GitHub Trees API, deduplicates
        ↓
   TCP pre-filter          — async TCP check per unique host:port (200 concurrent, 3s timeout)
        ↓
   candidates.txt          — checkpoint: survives interruption
        ↓
  sing-box tunnel test     — real tunnel: speedtest ≥ 1 Mbit/s + Claude.com reachability
        ↓
  known_good.txt           — permanent log of all verified configs
  run_YYYY-MM-DD.txt       — dated run file (last 5 kept)
```

Configs that pass Claude.com check are marked `#+++name`, blocked ones `#---name`.

## Requirements

- Python 3.10+
- [sing-box](https://github.com/SagerNet/sing-box) binary (used by Throne / Hiddify — auto-discovered)

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Full run: fetch → TCP filter → tunnel test
python -m vpn_collector.main --full

# Or step by step:
python -m vpn_collector.main --collect        # fetch and TCP-filter → candidates.txt
python -m vpn_collector.main --test           # tunnel-test candidates.txt → known_good.txt

# Quick run on a random subset (faster, good for daily use)
python -m vpn_collector.main --collect --sample 30000
python -m vpn_collector.main --full    --sample 50000

# Manage sources
python -m vpn_collector.main --add-source user/repo          # add GitHub repo
python -m vpn_collector.main --add-source https://example.com/sub.txt  # add raw URL
python -m vpn_collector.main --sync-stars <github_username>  # import starred repos

# Stats
python -m vpn_collector.main --stats
```

## Output

```
results/
├── candidates.txt        # TCP-passed configs (intermediate, overwritten each collect)
├── known_good.txt        # all verified configs ever found
└── run_YYYY-MM-DD.txt    # up to 5 dated run files (oldest auto-deleted)
```

`known_good.txt` is never deleted. Copy it into Throne/Hiddify as a subscription source.

## Configuration

All tunable parameters are in `vpn_collector/config.py`:

| Parameter | Default | Description |
|---|---|---|
| `TCP_CONCURRENCY` | 200 | Parallel TCP checks |
| `TCP_TIMEOUT` | 3.0s | TCP connection timeout |
| `TCP_BATCH_SIZE` | 5000 | Configs per checkpoint batch |
| `TUNNEL_CONCURRENCY` | 5 | Parallel sing-box tunnel tests |
| `MIN_SPEED_MBPS` | 1.0 | Minimum acceptable tunnel speed |

## Logs

```
logs/vpn_collector.log
```

Progress is printed to stdout during collection:
```
[1/53] Checking 1–5000...
[1/53] Batch: 312 passed | Total so far: 312 / 5000
```
