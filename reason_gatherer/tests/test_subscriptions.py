from vpn_collector.storage import save_subscriptions
from vpn_collector.subscriptions import extract_subscription_urls, validate_subscription_urls


VLESS = "vless://uuid@node.example:443?type=tcp&security=tls&sni=node.example#Node"


def test_extract_subscription_urls_deduplicates_and_removes_markdown_punctuation():
    text = "[feed](https://feed.example/sub?token=abc), and https://feed.example/sub?token=abc. ftp://bad.example/sub"

    assert extract_subscription_urls([text]) == ["https://feed.example/sub?token=abc"]


def test_extract_subscription_urls_skips_ordinary_links_and_keeps_labeled_feed():
    text = (
        "Join https://t.me/channel and see https://img.shields.io/badge/status-ok. "
        "Docs: https://github.com/2dust/v2rayNG and "
        "https://raw.githubusercontent.com/user/repo/main/TOR_BRIDGES_TOP100.txt. "
        "Subscription URL: https://provider.example/opaque-token?key=abc"
    )

    assert extract_subscription_urls([text]) == [
        "https://provider.example/opaque-token?key=abc"
    ]


def test_validation_keeps_only_parseable_subscription_with_a_passing_node(monkeypatch):
    bodies = {
        "https://working.example/sub": VLESS,
        "https://empty.example/sub": "This page has no proxy configs.",
    }
    tested = []

    monkeypatch.setattr(
        "vpn_collector.subscriptions.fetch_url_text",
        lambda url: bodies[url],
    )

    async def pass_only_tls_verified_nodes(configs, singbox_path, **kwargs):
        tested.append((configs, singbox_path, kwargs.get("verify_tls_cert")))
        return configs if kwargs.get("verify_tls_cert") else []

    monkeypatch.setattr("vpn_collector.subscriptions.tunnel_filter", pass_only_tls_verified_nodes)

    result = validate_subscription_urls(
        ["https://working.example/sub", "https://empty.example/sub"],
        "/usr/bin/sing-box",
    )

    assert result == ["https://working.example/sub"]
    assert tested == [([VLESS], "/usr/bin/sing-box", True)]


def test_validation_stops_testing_a_feed_after_first_passing_batch(monkeypatch):
    configs = [f"vless://uuid@node-{index}.example:443?type=tcp#Node{index}" for index in range(5)]
    calls = []
    monkeypatch.setattr("vpn_collector.subscriptions.SUBSCRIPTION_NODE_BATCH_SIZE", 2, raising=False)
    monkeypatch.setattr("vpn_collector.subscriptions.fetch_url_text", lambda url: "\n".join(configs))

    async def first_batch_passes(nodes, singbox_path, **kwargs):
        calls.append(nodes)
        return nodes[:1]

    monkeypatch.setattr("vpn_collector.subscriptions.tunnel_filter", first_batch_passes)

    result = validate_subscription_urls(["https://provider.example/sub"], "/usr/bin/sing-box")

    assert result == ["https://provider.example/sub"]
    assert calls == [configs[:2]]


def test_save_subscriptions_replaces_output_with_unique_urls_only(tmp_path):
    save_subscriptions(tmp_path, ["https://one.example/sub", "https://one.example/sub", " "])

    assert (tmp_path / "subscriptions.txt").read_text() == "https://one.example/sub\n"
