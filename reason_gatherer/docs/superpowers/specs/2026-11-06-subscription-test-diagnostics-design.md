# Subscription test accuracy and diagnostics

## Intent

Make subscription scan results trustworthy: create sing-box configs for supported transports, reject unsupported transports explicitly, and distinguish connection/probe failures from measured low speed and TLS validation failures.

## Approach

Keep sing-box as the test engine. Add native HTTPUpgrade mapping. The installed upstream sing-box 1.13.11 does not support XHTTP, so report XHTTP as unsupported instead of silently treating it as TCP or pretending it passed. Preserve strict certificate validation for subscription checks.

Return a structured speed probe result internally while preserving the existing float helper. Capture sing-box stderr per node, classify failures, and report per-run counters and a few sanitized examples. Continue accepting only nodes that complete a real proxied transfer at the configured minimum speed.

## Constraints

- Do not weaken TLS validation or substitute one transport for another.
- Do not include credentials or full share URLs in diagnostic examples.
- Keep existing caller behavior for `test_config_tunnel()` and `speedtest_via_socks()` where practical.
- Add regression tests for HTTPUpgrade mapping, XHTTP rejection, probe error vs measured low speed, and certificate error classification.

## Alternatives considered

1. Map XHTTP to sing-box HTTP or HTTPUpgrade. Rejected because these are different wire protocols and would mis-test nodes.
2. Add an alternative Xray engine. Rejected for this change because no Xray binary is installed or configured; engine discovery and compatibility form a separate feature.
3. Keep the current all-purpose `too_slow` counter. Rejected because it hides whether a node is slow, its transport is unsupported, or the probe failed.
