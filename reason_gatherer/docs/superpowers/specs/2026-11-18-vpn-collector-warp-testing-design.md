# VPN Collector: direct and WARP testing design

## Intent

Keep `--test` as a direct test of candidate VPN endpoints, and add an explicit
`--test-warp` mode to find endpoints reachable only through the host's
`warp-cli` SOCKS5 proxy. This makes ISP-blocked endpoints testable without
mixing WARP-only results into the regular `known_good` pool.

## Goals and non-goals

- `--test` must continue to bypass HTTP/SOCKS proxy environment variables and
  must stop if `warp-cli` reports an active system-tunnel mode.
- `--test-warp` uses the local SOCKS5 proxy at `127.0.0.1:40000`, preflights a
  TCP CONNECT to `1.1.1.1:443`, and routes the candidate outbound through that
  SOCKS proxy with sing-box's `detour` field.
- WARP results live under `results/warp/` and never update direct `known_good`,
  direct run files, metadata, or `candidates.txt`.
- The WARP SOCKS proxy rejects SOCKS5 `UDP_ASSOCIATE` (observed reply `0x07`),
  so Hysteria/Hysteria2/Hy2 and TUIC candidates are recorded as
  `warp_udp_unsupported`, not as failed nodes. Other existing tunnel failure
  categories retain their current meanings.
- Fix Shadowsocks URL parsing when the share link has an empty query marker,
  e.g. `ss://…@host:26179?#name`.
- Do not change warp-cli mode or system routing as part of a collector run.

Non-goals: automatically running direct and WARP tests in one invocation,
changing WARP state, or migrating WARP-only configurations into the regular
pool.

## Approaches

1. **Separate `--test-warp` mode — selected.** The user chooses when to test
   through WARP; results remain isolated. This preserves a clear direct/WARP
   comparison and avoids making every normal test depend on WARP availability.
2. **Combined direct-then-WARP run.** Produces an A/B report in one command,
   but doubles the work and couples direct testing to WARP availability.

## Constraints and implementation choices

- The host currently reports `WarpProxy on port 40000`, MASQUE, and a
  successful TCP SOCKS CONNECT. Sing-box 1.13.11 accepts a config with a SOCKS
  outbound and a candidate outbound using `detour`.
- The WARP test validates the proxy before starting candidate tests. If the
  SOCKS endpoint is unavailable, the command exits before writing results.
- The WARP result store is `results/warp/known_good.txt` plus dated
  `results/warp/run_YYYY-MM-DD.txt` files. It has its own deduplication and run
  rotation; direct result loading must not treat these configs as direct
  successes.
- The direct-mode guard blocks only when `warp-cli` reports that WARP is
  connected in system-tunnel mode. Proxy mode remains valid for direct tests
  because the child sing-box process does not use the WARP SOCKS proxy.
- Regression tests cover proxy environment removal, the system-tunnel guard,
  the WARP SOCKS detour, UDP-only protocol classification, result isolation,
  and the empty-query Shadowsocks link.

## Acceptance checks

- Existing direct `--test` behavior and result files remain unchanged apart
  from the explicit system-WARP guard and the SS parsing fix.
- With the host's WARP SOCKS proxy active, `--test-warp` reaches a candidate
  through the proxy and stores passing results only in `results/warp/`.
- A missing or unusable WARP SOCKS proxy produces a clear error before tests
  begin; UDP-only candidates are reported as unsupported for this mode.
