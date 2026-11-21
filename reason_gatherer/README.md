# reason_gatherer

Two independent collectors for public VPN configs:

- `vpn_collector` gathers proxy links, checks TCP reachability, then tests tunnel speed and Claude.com access.
- `awg_collector` tests AmneziaWG configs and builds importable archives.

## Quick start

To run the main collector, use Python 3.10+ and install [sing-box](https://github.com/SagerNet/sing-box):

```bash
pip install -r requirements.txt
python -m vpn_collector.main --full
```

`--full` fetches sources, filters candidates by TCP, then tunnel-tests them. For step-by-step runs, use `--collect` and then `--test`.

## Ready-to-use results

| File | Description |
|---|---|
| [**known_good.txt**](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/known_good.txt) | All verified configs ever collected — use as subscription URL |
| [**subscriptions.txt**](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/subscriptions.txt) | Third-party subscription URLs with at least one verified working node |
| [subscription_configs_3.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/subscription_configs_3.txt) | Currently working configs from subscription row 3 |
| [subscription_configs_5.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/subscription_configs_5.txt) | Currently working configs from subscription row 5 |
| [subscription_configs_7.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/subscription_configs_7.txt) | Currently working configs from subscription row 7 |
| [run_2026-11-17.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/run_2026-11-17.txt) | Latest run |
| [run_2026-11-07.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/run_2026-11-07.txt) | Previous run |
| [run_2026-10-31.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/run_2026-10-31.txt) | Earlier run |
| [run_2026-10-22.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/run_2026-10-22.txt) | Earlier run |
| [run_2026-10-09.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/run_2026-10-09.txt) | Earlier run |
| [recheck_2026-11-19.txt](https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results/recheck_2026-11-19.txt) | Latest recheck (configs re-verified from known_good) |

Configs marked `+++` passed the Claude.com access check. `---` means the tunnel passed its speed test but Claude.com was blocked.

## VPN collector commands

### Run and test

```bash
# Complete collection and tunnel test
python -m vpn_collector.main --full

# Run the stages separately
python -m vpn_collector.main --collect
python -m vpn_collector.main --test

# Test remaining candidates through WARP's local SOCKS proxy
python -m vpn_collector.main --test-warp

# Run on a random sample
python -m vpn_collector.main --collect --sample 30000
python -m vpn_collector.main --full    --sample 50000

# Re-test known_good configs without changing known_good.txt
python -m vpn_collector.main --recheck
```

### Subscription feeds

```bash
# Find and validate subscription URLs in configured sources
python -m vpn_collector.main --subscriptions

# Test all saved subscriptions, or one numbered row
python -m vpn_collector.main --test-subscriptions
python -m vpn_collector.main --test-subscription 3
```

### Sources and Telegram

```bash
python -m vpn_collector.main --add-source user/repo
python -m vpn_collector.main --add-source https://example.com/sub.txt
python -m vpn_collector.main --add-source t.me/channelname
python -m vpn_collector.main --sync-stars <github_username>
python -m vpn_collector.main --setup-tg
```

Telegram is optional. For the one-time setup, install Telethon and authenticate with an API ID and hash from [my.telegram.org](https://my.telegram.org):

```bash
pip install telethon>=1.36
python -m vpn_collector.main --setup-tg
```

Credentials are stored under `~/.config/vpn_collector/`, outside the repository. Add public channels with `--add-source t.me/channelname`; accepted forms include `t.me/name`, `t.me/s/name`, and `https://t.me/name`. Each collection scans the latest 50 posts. Without Telegram setup, collection continues with the other sources.

Behind a proxy, set `ALL_PROXY` for Telegram setup:

```bash
ALL_PROXY=socks5://127.0.0.1:<port> python -m vpn_collector.main --setup-tg
```

### Diagnose and inspect

```bash
# Diagnose the broadest available recheck file
python -m vpn_collector.main --diagnose

# Diagnose a specific file, or use WARP SOCKS as an egress comparison
python -m vpn_collector.main --diagnose results/recheck_2026-11-04.txt
python -m vpn_collector.main --diagnose --proxy 127.0.0.1:40000

# Show result counts
python -m vpn_collector.main --stats
```

The diagnosis report labels each endpoint `blocked_by_isp`, `server_dead`, or `unknown`. `--proxy` uses SOCKS5 to distinguish an ISP block from a dead server. Keep WARP in proxy mode for honest direct tests; system-tunnel mode routes every probe through WARP.

## Results and workflow

The main collector works in two stages:

```text
Sources → TCP filter → candidates.txt → tunnel test → known_good.txt + run_YYYY-MM-DD.txt
```

| Path | Purpose |
|---|---|
| `results/known_good.txt` | Permanent list of verified configs; never overwritten |
| `results/run_YYYY-MM-DD.txt` | Dated test results; the 5 newest runs are kept |
| `results/candidates.txt` | Intermediate queue produced by `--collect` |
| `results/tcp_cache.txt` | Cached TCP-verified host:port pairs |
| `results/recheck_YYYY-MM-DD.txt` | Results from `--recheck` |
| `results/subscriptions.txt` | Validated third-party subscription URLs |
| `results/subscription_configs.txt` | Working configs from all saved subscriptions |
| `results/subscription_configs_N.txt` | Working configs from one subscription row |

Subscription outputs are snapshots and update only when the corresponding command completes successfully. Tunnel tests report failures by category, including certificate, handshake, speed, and unsupported transport errors. The current sing-box supports HTTPUpgrade but not XHTTP; XHTTP configs are skipped.

## Sources

The collector reads GitHub repositories, raw URLs, and optional Telegram channels. The active list includes the feeds below. Reported success rates come from their publishers; the collector re-tests configs from the local network.

<details>
<summary>Curated feeds and channels</summary>

Selected public posts from [@airfield1972](https://t.me/s/airfield1972?q=%23keys); checked 2026-11-20:

| Source | Feed type | Publisher-reported result |
|---|---|---|
| [ScarletDevil](https://raw.githubusercontent.com/Areral/ScarletDevil/refs/heads/main/sub_all.txt) | Raw subscription, about every 4 hours | 205/214 under 100 ms ([post](https://t.me/airfield1972/6660)) |
| [TelegaVPN](https://raw.githubusercontent.com/TelegaVPN/free-vpn-keys/refs/heads/main/sub/base64/all.txt) | Base64 subscription | 64/77 working ([post](https://t.me/airfield1972/6653)) |
| [Ariston gold](https://raw.githubusercontent.com/Edsel-Rahimi/Ariston/data/gold.txt) | VLESS feed | 249/311 passed speed test ([post](https://t.me/airfield1972/6686)) |
| [theakres/VPN](https://raw.githubusercontent.com/theakres/VPN/refs/heads/main/all) | Combined feed | 241/717 passed speed test ([post](https://t.me/airfield1972/6694)) |
| [zhangqiyang2-max](https://gist.githubusercontent.com/zhangqiyang2-max/47f1336a2e41af2e0f7f4313cc8c4bdc/raw/v2ray.txt) | V2Ray text | 70/87 across V2Ray and Clash feeds ([post](https://t.me/airfield1972/6718)) |
| [554mtntjch-code](https://gist.githubusercontent.com/554mtntjch-code/3a1a5e147050f64d72d5b8f5c6d4d61c/raw/v2ray.txt) | V2Ray text | 14/20 passed ([post](https://t.me/airfield1972/6727)) |
| [skysph-dev](https://gist.githubusercontent.com/skysph-dev/5b55986287442543485b30468db3eb65/raw/v2ray.txt) | V2Ray text | 15/21 in Throne; 20/21 in FLClash ([post](https://t.me/airfield1972/6746)) |
| [st0rer Hysteria2](https://gist.githubusercontent.com/st0rer/52759ee3f68c3d4b2f2d53c307867471/raw/hy2_nodes.txt) | Plain-text Hysteria2 | 18/25 in Throne ([post](https://t.me/airfield1972/6757)) |
| [December000](https://gist.githubusercontent.com/December000/fd23d2530ffc29264297a5e687a79ecd/raw/base64.txt) | Base64 feed | 12/13 working ([post](https://t.me/airfield1972/6697)) |
| [V2RayN-VPN-Source](https://raw.githubusercontent.com/ivanprochorov2022-debug/V2RayN-VPN-Source/refs/heads/main/live.txt) | Large live feed | 54 passed from 5,087 parsed ([post](https://t.me/airfield1972/6731)) |

These Telegram channels are also scanned across their latest 50 posts:

| Channel | Publisher-reported result |
|---|---|
| [@pass_net](https://t.me/s/pass_net) | 38/65 working ([post](https://t.me/airfield1972/6648)) |
| [@VPsave](https://t.me/s/VPsave) | 48/138 passed ([post](https://t.me/airfield1972/6664)) |
| [@configv2rayng](https://t.me/s/configv2rayng) | 197/592 passed speed checks ([post](https://t.me/airfield1972/6705)) |
| [@ex_proxies](https://t.me/s/ex_proxies) | 127/335 passed speed checks ([post](https://t.me/airfield1972/6736)) |
| [@FXxNET](https://t.me/s/FXxNET) | 202/215 under 100 ms ([post](https://t.me/airfield1972/6691)) |

Other recently checked feeds:

| Feed | Current contents and publisher's checks |
|---|---|
| [0xRadikal top 100](https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/top100.txt) | 100 configs; refreshed every 15 minutes; each verified config passes a proxied request in 3 runs ([details](https://github.com/0xRadikal/Free-v2ray-Configs/releases)) |
| [ProxyRift light](https://raw.githubusercontent.com/rekt0ro/ProxyRift/main/subscriptions/light.txt) | 136 configs; refreshed hourly; publisher reported over 80% working ([post](https://t.me/airfield1972/6570)) |
| [Danialsamadi/v2go](https://raw.githubusercontent.com/Danialsamadi/v2go/main/AllConfigsSub.txt) | 648 configs; publisher runs an Xray-core request to an HTTP 204 endpoint ([method](https://github.com/Danialsamadi/v2go#how-it-works), [recent runs](https://github.com/Danialsamadi/v2go/actions/workflows/update-configs.yml)) |

</details>

## AmneziaWG collector

The separate `awg_collector` tests AmneziaWG configs and builds archives for the Amnezia app. `all_configs.zip` contains up to 50 fastest configs with exit countries outside Russia; `all_configs_warp.zip` contains configs that exit through WARP anycast back into Russia and are useful for DPI bypass.

```bash
python -m awg_collector.main --collect
python -m awg_collector.main --recheck
python -m awg_collector.main --export
python -m awg_collector.main --stats
```

Import an archive in Amnezia: **Add VPN → From file**. Each included config passes a tunnel handshake and a speed test of at least 1 Mbit/s. Sources include Telegram [@amnezia_wg](https://t.me/amnezia_wg), [@vpnconfigsgive](https://t.me/vpnconfigsgive), and [Delta-Kronecker/WARP-Config](https://github.com/Delta-Kronecker/WARP-Config).

<details>
<summary>AWG installation requirements</summary>

Install `requests` and `telethon` from `requirements.txt`. Tunnel testing additionally needs Go 1.25+, `amneziawg-go`, and `awg`/`awg-quick` from [amneziawg-tools](https://github.com/amnezia-vpn/amneziawg-tools):

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

</details>

## WARP and network diagnosis

`--test-warp` tests candidates through the local WARP SOCKS5 proxy (`127.0.0.1:40000`) and stores results under `results/warp/`. Hysteria, Hysteria2, Hy2, and TUIC are skipped because this SOCKS proxy does not carry UDP. For ISP-block diagnosis, pass the same SOCKS address to `--diagnose --proxy`.

Use `warp-cli mode proxy` for these checks. Do not use `warp-cli mode warp`: system-tunnel mode routes direct probes through WARP and makes blocked endpoints appear reachable.

<details>
<summary>Host-specific setup: warp-cli, Throne, and zapret</summary>

### warp-cli

`warp-cli mode proxy` exposes SOCKS5 at `127.0.0.1:40000`. The protocol is MASQUE; check with `warp-cli settings`. To verify egress:

```bash
curl --socks5-hostname 127.0.0.1:40000 https://www.cloudflare.com/cdn-cgi/trace
```

### Throne

Throne's mixed system proxy listens at `127.0.0.1:2080`. Its built-in WARP can be configured in **Routing Settings → Warp**.

- **WARP egress:** select MASQUE, generate a WARP config, then enable it. The node connects directly; WARP changes the exit IP. This does not unblock ISP-blocked nodes.
- **WARP ingress:** add a SOCKS profile for `127.0.0.1:40000`, then choose it as the group's **Front Proxy**. WARP then carries the connection to the node while the exit IP remains the node's.

For headless control, enable Throne API in **Preferences → Integration Settings**. Example API operations are `thronectl settings set enable_warp=…` and `thronectl call POST /v1/warp/register`.

### zapret

The local zapret rule covers DPI inspection of the MASQUE hostname. It does not bypass a destination-IP block or per-IP throttling. The rule belongs at the start of `NFQWS_OPT` in `/opt/zapret/config`:

```
--filter-udp=443 --hostlist-domains=cloudflareclient.com --hostlist-exclude-domains=api.cloudflareclient.com --dpi-desync=fake --dpi-desync-repeats=6 --dpi-desync-fake-quic=/opt/zapret/files/fake/quic_6.bin --new
--filter-tcp=443 --hostlist-domains=cloudflareclient.com --hostlist-exclude-domains=api.cloudflareclient.com --dpi-desync=fake,multidisorder --dpi-desync-split-pos=1,midsld --dpi-desync-repeats=6 --dpi-desync-fake-tls=/opt/zapret/files/fake/tls_clienthello_www_google_com.bin --dpi-desync-fooling=badsum --new
```

Apply and verify; the config backup pattern is shown below:

```bash
sudo systemctl restart zapret
curl --socks5-hostname 127.0.0.1:40000 https://www.cloudflare.com/cdn-cgi/trace
sudo cp /opt/zapret/config.backup-warp-<timestamp> /opt/zapret/config && sudo systemctl restart zapret
```

</details>

## Configuration

Core settings are in `vpn_collector/config.py`. GitHub cache and request settings use environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | unset | Optional token for `api.github.com` |
| `VPN_COLLECTOR_CACHE_DIR` | `~/.cache/vpn_collector/github` | ETag and file-content cache |
| `VPN_COLLECTOR_GITHUB_API_DELAY_SECONDS` | `1.0` | Minimum gap between REST API calls |
| `VPN_COLLECTOR_TREE_REVALIDATE_SECONDS` | `3600` | Minimum interval between tree ETag checks |
| `VPN_COLLECTOR_STAR_SYNC_INTERVAL_SECONDS` | `86400` | Automatic starred-repository refresh interval |

The collector caches repository trees and files by Git blob SHA. It uses cached trees during a GitHub rate limit and reports `rate_used` / `rate_remaining` in API logs. Starred repositories are synced once per day; force an update with `--sync-stars USERNAME`.

| Setting | Default | Purpose |
|---|---|---|
| `TCP_CONCURRENCY` | 100 | Parallel TCP checks |
| `TCP_TIMEOUT` | 4.0s | TCP connection timeout |
| `TCP_BATCH_SIZE` | 5000 | Configs per checkpoint batch |
| `TUNNEL_CONCURRENCY` | 20 | Parallel sing-box tunnel tests |
| `MIN_SPEED_MBPS` | 1.0 | Minimum tunnel speed |
| `SINGBOX_STARTUP_TIMEOUT` | 3.0s | Wait for sing-box SOCKS port |
| `SPEEDTEST_EARLY_ABORT_AFTER` | 4.0s | Time before early speed-test abort |
| `SPEEDTEST_EARLY_ABORT_FACTOR` | 0.5 | Abort below this fraction of minimum speed |
| `SUBSCRIPTION_MAX_URLS` | 100 | Unique URLs checked per discovery run |
| `SUBSCRIPTION_MAX_NODES` | 30 | Nodes tested per subscription |
| `SUBSCRIPTION_NODE_BATCH_SIZE` | 10 | Stop after the first passing batch |
| `SUBSCRIPTION_REPO_FETCH_CONCURRENCY` | 10 | Parallel files fetched during subscription discovery |

## Updates and logs

Result files are pushed to this repository every two days by cron. Manually trigger a push with:

```bash
bash scripts/git_push_results.sh
```

Logs are in `logs/vpn_collector.log` and `logs/autopush.log`.
