# Plan: test configs from saved subscriptions

## Files

- Modify `vpn_collector/subscriptions.py` to fetch and parse configs from selected subscription URLs and deduplicate equivalent lines before tunnel testing.
- Modify `vpn_collector/storage.py` to atomically replace aggregate or per-feed config snapshots.
- Modify `vpn_collector/main.py` to add mutually exclusive `--test-subscriptions` and `--test-subscription N` commands. Both test every unique parsed node with `verify_tls_cert=True`; the second selects the 1-based URL row from `results/subscriptions.txt`.
- Modify `README.md` with command examples and output semantics.
- Modify `scripts/git_push_results.sh` to stage `subscription_configs*.txt` and publish the aggregate output in the results table.

## Behavior

- Full run reads every nonempty URL from `subscriptions.txt`, continues past individual fetch failures, deduplicates configs across feeds, and tests all remaining nodes.
- Single run validates the requested 1-based index and tests only that URL. It writes to `subscription_configs_N.txt`; the full run writes to `subscription_configs.txt`.
- Each completed run atomically replaces its own snapshot with only passing configs. An absent URL list, invalid index, or wholly unparseable input leaves existing snapshots untouched.
- Do not add passing configs to `known_good.txt` or dated run files.

## Implementation steps

1. Add a subscription-feed fetch/parse helper and key-based deduplication, keeping network errors isolated to the failed URL.
2. Add a storage helper that writes the selected snapshot through a temporary sibling file and atomic rename.
3. Add both CLI modes, sing-box lookup, strict TLS tunnel testing, progress logs, and per-mode output paths.
4. Document the flags and outputs, and include output snapshots in the results push script.
5. Verify command help and inspect the diff for unrelated changes.
