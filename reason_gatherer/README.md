# reason_gatherer / vpn_collector

Scrapes free VPN configs from GitHub repositories, filters them by TCP reachability and tunnel quality (speed + Claude.com access), and saves verified configs to rotating result files.

## Verified configs (updated every 2–3 days)

| File | Description |
|---|---|
| [**known_good.txt**](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/known_good.txt) | All verified configs ever collected — use as subscription URL |
| [**subscriptions.txt**](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/subscriptions.txt) | Third-party subscription URLs with at least one verified working node |
| [subscription_configs_3.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/subscription_configs_3.txt) | Currently working configs from subscription row 3 |
| [subscription_configs_5.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/subscription_configs_5.txt) | Currently working configs from subscription row 5 |
| [subscription_configs_7.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/subscription_configs_7.txt) | Currently working configs from subscription row 7 |
| [run_2026-11-07.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/run_2026-11-07.txt) | Latest run |
| [run_2026-10-31.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/run_2026-10-31.txt) | Previous run |
| [run_2026-10-22.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/run_2026-10-22.txt) | Earlier run |
| [run_2026-10-09.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/run_2026-10-09.txt) | Earlier run |
| [run_2026-10-05.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/run_2026-10-05.txt) | Earlier run |
| [recheck_2026-11-13.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/recheck_2026-11-13.txt) | Latest recheck (configs re-verified from known_good) |

Configs marked `+++` passed the Claude.com access check (unblocked from Russia). Configs marked `---` passed the speed test but Claude.com was blocked through them.

---

## AmneziaWG configs (for AmneziaVPN 1.0.1)

A separate collector scrapes and tunnel-tests AmneziaWG configs from community sources and packages the fastest ones for direct import into the Amnezia app.

| Path | Description |
|---|---|
| [**results_awg/all_configs.zip**](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results_awg/all_configs.zip) | Import this into the Amnezia app — the 50 fastest configs that change your exit country, capped at 5 per /24 subnet |
| `results_awg/known_good/*.conf` | Full pool of currently-passing configs that exit outside Russia (one file per endpoint) |
| [results_awg/all_configs_warp.zip](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results_awg/all_configs_warp.zip) | Configs that pass handshake+speed but exit through Cloudflare WARP anycast back into Russia — still useful for DPI bypass, just no geo change |
| `results_awg/known_good_warp/*.conf` | Full pool of the WARP-anycast configs above |

**Import:** Amnezia app → Add VPN → From file → `all_configs.zip` (or `all_configs_warp.zip` if you only need DPI bypass, not a geo change)

Each config is real-tunnel-tested (handshake verified + speed ≥ 1 Mbit/s). Configs are split by exit country: those landing outside Russia go to `known_good/`, those landing back in Russia (typically WARP anycast routing to the nearest edge) go to `known_good_warp/` instead of being discarded. Both pools are rebuilt to include only the 50 fastest configs (capped per /24) after each run; `--recheck` also moves a config between the two pools if its exit country changes.

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

### Why "unreachable" needs a diagnosis

A plain TCP timeout means three different things: a dead server, a closed
port, or the ISP swallowing the packet by destination IP. They are told apart
by `--diagnose`, which reports `blocked_by_isp` vs `server_dead` per endpoint:

- **TTL-capped ping** — a live-but-ICMP-silent host still yields a
  *Time-to-live-exceeded* answer from an intermediate router at TTL 5, while a
  blackholed IP stays silent at TTL 5/8/12: the packet dies inside the access
  network, before the first hop that would answer. Evidence is inferred.
- **SOCKS5 egress (`--proxy`)** — the same endpoint that times out directly
  and completes a TCP CONNECT through a proxy cannot be dead. Evidence is
  conclusive, and it is ~2× faster than the ping sweep.

The diagnosis is local: `blocked_by_isp` says nothing about whether the host
is alive — it may be blackholed *and* dead at the same time. Check from
another network (or via check-host.net) to separate those.

WARP note: `warp-cli mode warp` routes the whole system through the tunnel, so
every probe looks alive and the report degenerates. `warp-cli mode proxy`
keeps traffic direct while exposing a local SOCKS5 (default
`127.0.0.1:40000`), which is exactly what `--proxy` wants.

## WARP integration: warp-cli, Throne, zapret

Three independent pieces on this box; they run side by side.

### warp-cli — SOCKS egress for probing

- `warp-cli mode proxy` → local SOCKS5 `127.0.0.1:40000`, consumed by
  `--proxy`. Transport is MASQUE (QUIC/HTTP3, UDP 443 → Cloudflare anycast),
  not WireGuard: `warp-cli settings` shows `WARP tunnel protocol: MASQUE`.
- Honest A/B on one 227-config pool, one-minute interval: **8 configs /
  6 endpoints direct vs 147 / 13 through WARP**. All 12 revived endpoints
  were `blocked_by_isp`; 5 of the 17 stayed dead even via WARP (blackholed
  *and* dead at once).

### Throne — system proxy with built-in WARP

Throne serves the system proxy (mixed inbound `127.0.0.1:2080`,
`system_proxy_enabled=true`) and ships its own WARP client (Routing
Settings → Warp tab, setting `enable_warp`; upstream
[throneproj/Throne](https://github.com/throneproj/Throne)). Two different
uses — pick by what you need:

1. **WARP as egress (whitening).** Warp tab → Mode **MASQUE** →
   *Generate Warp Config* (registers a Cloudflare device; the MASQUE
   identity is separate from the WireGuard one already stored) →
   *Enable Warp*. Generated topology is `app → node → WARP → target`:
   `generate.cpp` prepends the synthetic warp profile and points the node
   outbound's `detour` at it, so the **node dial stays direct** and only
   the exit IP becomes Cloudflare. Does *not* unblock `blocked_by_isp`
   nodes.
2. **WARP as ingress (reach blackholed nodes).** Add a profile of type
   `socks` → `127.0.0.1:40000` (warp-cli proxy mode), then
   Group → Edit Group → **Front Proxy** → select it. The front proxy is
   appended after the main hop and becomes its dialer:
   `local → WARP(SOCKS) → node → target`. The node becomes reachable
   through the blackhole while the exit IP stays the node's. A native
   `masque` profile (profile editor → *Register a new Cloudflare WARP
   device*) can replace the warp-cli SOCKS hop if you don't want a second
   WARP client.

For headless control turn on the Throne API (Preferences → Integration
Settings) and drive it with `thronectl` (`settings set enable_warp=…`,
`call POST /v1/warp/register`, …). It is off by default and `thronectl`
refuses to work without an API key.

### zapret — fuse for the WARP transport

zapret already queues this box's own UDP/443 (nft `postnat`:
`udp dport 443 ct original packets 1-9 … queue to 200`), so warp-svc's
MASQUE packets were reaching nfqws all along — only a matching rule was
missing. Added to the head of `NFQWS_OPT` in `/opt/zapret/config`
(backup `config.backup-warp-20261108-*`):

```
--filter-udp=443 --hostlist-domains=cloudflareclient.com --hostlist-exclude-domains=api.cloudflareclient.com --dpi-desync=fake --dpi-desync-repeats=6 --dpi-desync-fake-quic=/opt/zapret/files/fake/quic_6.bin --new
--filter-tcp=443 --hostlist-domains=cloudflareclient.com --hostlist-exclude-domains=api.cloudflareclient.com --dpi-desync=fake,multidisorder --dpi-desync-split-pos=1,midsld --dpi-desync-repeats=6 --dpi-desync-fake-tls=/opt/zapret/files/fake/tls_clienthello_www_google_com.bin --dpi-desync-fooling=badsum --new
```

`sudo systemctl restart zapret` picks it up. Verified after the restart:
`curl --socks5-hostname 127.0.0.1:40000 https://www.cloudflare.com/cdn-cgi/trace`
still answers `warp=on`, Throne's inbound still returns 204, direct
traffic unaffected.

What the fuse covers — and what it does not:

| Block vector | zapret |
|---|---|
| DPI parses the QUIC Initial / TLS ClientHello and bans SNI `*.cloudflareclient.com` | **defeated** — fake QUIC/TLS packets poison DPI state before the real SNI is readable |
| destination-IP blackhole of `engage.cloudflareclient.com` (documented in the wild, e.g. `162.159.192.0/23`) | **not covered** — the packet dies before nfqws; change the endpoint (`warp_masque_ep` / `warp_api_hosts`) or carry WARP over another proxy |
| per-IP throttling (RU ISPs have throttled Cloudflare to 16 KB/conn since 2025-06-09) | **not covered** — measured on this box: 10 MB through WARP 3.17 MB/s vs 3.25 MB/s direct, so the tunnel is not throttled yet |

Revert: `sudo cp /opt/zapret/config.backup-warp-<timestamp> /opt/zapret/config && sudo systemctl restart zapret`.

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

# Discover third-party subscription URLs in configured sources and keep only those with a working node
python -m vpn_collector.main --subscriptions

# Test all configs from saved subscription URLs (strict TLS) → subscription_configs.txt
python -m vpn_collector.main --test-subscriptions

# Test one 1-based row from subscriptions.txt → subscription_configs_3.txt
python -m vpn_collector.main --test-subscription 3

# Step by step:
python -m vpn_collector.main --collect        # fetch and TCP-filter → candidates.txt
python -m vpn_collector.main --test           # tunnel-test candidates.txt → known_good.txt

# Quick run on a random subset
python -m vpn_collector.main --collect --sample 30000
python -m vpn_collector.main --full    --sample 50000

# Re-verify existing known_good configs (check if still alive)
python -m vpn_collector.main --recheck        # → recheck_YYYY-MM-DD.txt (known_good untouched)

# Diagnose WHY endpoints are unreachable: ISP destination-IP block vs dead server
python -m vpn_collector.main --diagnose                              # broadest recheck file
python -m vpn_collector.main --diagnose results/recheck_2026-11-04.txt
python -m vpn_collector.main --diagnose --proxy 127.0.0.1:40000      # SOCKS5 egress → proof
# → results/diagnose_<source>_<date>.txt with a status per endpoint:
#   blocked_by_isp  packet never leaves the access network (blackholed destination IP)
#   server_dead     route is clear, host/port just does not answer
#   unknown         neither probe could decide (no ping / bad name)

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
├── subscriptions.txt        # discovered third-party subscription URLs with live nodes
├── subscription_configs.txt # current working configs from all saved subscriptions
├── subscription_configs_N.txt # current working configs from one selected subscription
├── run_YYYY-MM-DD.txt       # up to 5 dated run files (oldest auto-deleted)
├── recheck_YYYY-MM-DD.txt   # on-demand recheck results from known_good
├── candidates.txt           # TCP-passed queue (intermediate, not tracked in git)
└── tcp_cache.txt            # TCP-verified host:ports cache (not tracked in git)
```

`known_good.txt` is never overwritten. Paste the raw URL into Throne / Hiddify as a subscription source.
`subscriptions.txt` contains external subscription URLs discovered in the configured sources and validated through at least one working tunnel. Refresh it independently with `python -m vpn_collector.main --subscriptions`.
`--test-subscriptions` downloads every saved feed, tests all unique parsed configs with TLS certificate validation enabled, and replaces `subscription_configs.txt` with the passing configs. To test only one entry, pass its 1-based row number from `subscriptions.txt` to `--test-subscription`; that run writes `subscription_configs_N.txt` and leaves the aggregate file alone. These outputs are snapshots, refreshed only when the corresponding flag completes successfully.
Tunnel scan progress now separates certificate, Reality handshake, transport handshake, endpoint connection, speed-probe, measured-low-speed, and unsupported-transport failures. Upstream sing-box supports HTTPUpgrade but not XHTTP; XHTTP links are reported as unsupported and are not tested as TCP. See the [sing-box V2Ray transport reference](https://sing-box.sagernet.org/configuration/shared/v2ray-transport/).

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
| `SUBSCRIPTION_MAX_URLS` | 100 | Check at most the first 100 unique HTTP(S) URLs found per `--subscriptions` run |
| `SUBSCRIPTION_MAX_NODES` | 30 | Tunnel-test at most the first 30 parsed nodes from each subscription |
| `SUBSCRIPTION_NODE_BATCH_SIZE` | 10 | Stop checking a subscription after its first passing group of 10 nodes |
| `SUBSCRIPTION_REPO_FETCH_CONCURRENCY` | 10 | Parallel GitHub text-file fetches during subscription discovery |

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
