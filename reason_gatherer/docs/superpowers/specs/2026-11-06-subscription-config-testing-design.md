# Design: test configs from saved subscriptions

## Intent

Provide a separate CLI mode that fetches the saved subscription URLs, tests the configs inside them, and writes currently working configs to a dedicated file. This gives the user a refreshable pool of verified nodes without mixing the URLs or configs with `known_good.txt`.

## Chosen approach

Add `--test-subscriptions`, separate from the existing `--subscriptions` discovery mode. Read URLs from `results/subscriptions.txt`, parse each available feed with the existing parser, deduplicate repeated configs across feeds, and run every unique config through `tunnel_filter` with TLS certificate validation enabled. Keep one copy of each passing config in `results/subscription_configs.txt`.

Also add `--test-subscription N` to test only the 1-based Nth URL in `subscriptions.txt`. Save that feed's passing configs to `results/subscription_configs_N.txt`, so an individual run does not overwrite the aggregate snapshot.

Write results to a temporary file while checking and replace `subscription_configs.txt` only after a completed run. A failed fetch for one URL is logged and skipped; other feeds continue. Do not update `known_good.txt`, `run_*.txt`, or `subscriptions.txt`.

## Alternatives considered

1. Add config testing to `--subscriptions`. Rejected because it combines URL discovery and node testing, which are separate operations.
2. Test only a small sample from each feed. Rejected because the requested output is a list of working configs, and a sample can miss working nodes later in a feed.

## Constraints and open implementation details

- Use existing URL fetch, parser, sing-box discovery, tunnel test, and result directory patterns.
- Require valid TLS certificates, matching the existing subscription URL validation mode.
- Test all unique configs; progress is logged so long runs remain observable.
- For a selected feed, validate that N is a valid 1-based row number and report the URL selected before testing.
- If `subscriptions.txt` is absent or contains no URLs, report that clearly and leave the previous config snapshot untouched.
- Register the new option in CLI help and document its command and output in README.
