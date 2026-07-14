import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from awg_collector.sources import add_source, load_sources, fetch_all_configs

SAMPLE_CONF = """[Interface]
PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
Jc = 4
Jmin = 40
Jmax = 70
S1 = 0
S2 = 0
H1 = 1
H2 = 2
H3 = 3
H4 = 4

[Peer]
PublicKey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=
AllowedIPs = 0.0.0.0/0
Endpoint = 185.123.45.67:51820
PersistentKeepalive = 25"""


@pytest.fixture()
def sources_file(tmp_path):
    return tmp_path / "sources_awg.json"


class TestAddSource:
    def test_add_github_repo(self, sources_file):
        assert add_source("owner/repo", sources_file) is True
        sources = load_sources(sources_file)
        assert {"type": "github", "value": "owner/repo"} in sources

    def test_add_url(self, sources_file):
        assert add_source("https://example.com/config.conf", sources_file) is True
        sources = load_sources(sources_file)
        assert {"type": "url", "value": "https://example.com/config.conf"} in sources

    def test_add_telegram_url(self, sources_file):
        assert add_source("https://t.me/somechannel", sources_file) is True
        sources = load_sources(sources_file)
        assert {"type": "tg", "value": "somechannel"} in sources

    def test_duplicate_not_added(self, sources_file):
        add_source("owner/repo", sources_file)
        assert add_source("owner/repo", sources_file) is False
        assert len(load_sources(sources_file)) == 1

    def test_creates_file_if_missing(self, sources_file):
        assert not sources_file.exists()
        add_source("owner/repo", sources_file)
        assert sources_file.exists()


class TestFetchAllConfigs:
    def test_deduplicates_by_endpoint(self, sources_file, tmp_path):
        sources_file.write_text(json.dumps([
            {"type": "url", "value": "https://example.com/a.conf"},
            {"type": "url", "value": "https://example.com/b.conf"},
        ]))
        # Both URLs return same endpoint
        with patch("awg_collector.sources._fetch_url") as mock_fetch:
            mock_fetch.return_value = SAMPLE_CONF
            result = fetch_all_configs(sources_file)
        assert len(result) == 1
        assert result[0]["endpoint"] == "185.123.45.67:51820"

    def test_skips_non_awg_configs(self, sources_file):
        wg_only = SAMPLE_CONF.replace("Jc = 4\nJmin = 40\nJmax = 70\nS1 = 0\nS2 = 0\nH1 = 1\nH2 = 2\nH3 = 3\nH4 = 4\n", "")
        sources_file.write_text(json.dumps([{"type": "url", "value": "https://x.com/c.conf"}]))
        with patch("awg_collector.sources._fetch_url") as mock_fetch:
            mock_fetch.return_value = wg_only
            result = fetch_all_configs(sources_file)
        assert result == []

    def test_fetch_error_skipped(self, sources_file):
        sources_file.write_text(json.dumps([{"type": "url", "value": "https://x.com/c.conf"}]))
        with patch("awg_collector.sources._fetch_url", side_effect=Exception("network error")):
            result = fetch_all_configs(sources_file)
        assert result == []
