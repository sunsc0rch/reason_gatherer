import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from vpn_collector.sources import (
    load_sources, save_sources, add_source,
    sync_stars, fetch_url_configs, fetch_repo_configs, _is_fetchable,
)

VLESS1 = "vless://uuid1@1.2.3.4:443?type=tcp#Server1"
VLESS2 = "vless://uuid2@5.6.7.8:8080?type=tcp#Server2"
VLESS3 = "vless://uuid3@9.0.0.1:443?type=tcp#Server3"


@pytest.fixture
def sources_file(tmp_path):
    return tmp_path / "sources.json"


class TestLoadSaveSources:
    def test_load_creates_default_if_missing(self, sources_file):
        sources = load_sources(sources_file)
        assert len(sources) > 0
        assert all("type" in s and "value" in s for s in sources)

    def test_load_reads_existing(self, sources_file):
        data = [{"type": "repo", "value": "user/repo"}]
        sources_file.write_text(json.dumps(data))
        assert load_sources(sources_file) == data

    def test_save_writes_json(self, sources_file):
        data = [{"type": "repo", "value": "user/repo"}]
        save_sources(data, sources_file)
        assert json.loads(sources_file.read_text()) == data


class TestAddSource:
    def test_add_repo(self, sources_file):
        sources_file.write_text(json.dumps([]))
        assert add_source("newuser/newrepo", sources_file) is True
        sources = load_sources(sources_file)
        assert any(s["value"] == "newuser/newrepo" for s in sources)

    def test_add_url(self, sources_file):
        sources_file.write_text(json.dumps([]))
        assert add_source("https://example.com/sub.txt", sources_file) is True
        sources = load_sources(sources_file)
        assert any(s["value"] == "https://example.com/sub.txt" for s in sources)

    def test_no_duplicate(self, sources_file):
        sources_file.write_text(json.dumps([{"type": "repo", "value": "user/repo"}]))
        add_source("user/repo", sources_file)
        assert len([s for s in load_sources(sources_file) if s["value"] == "user/repo"]) == 1

    def test_returns_false_for_existing(self, sources_file):
        sources_file.write_text(json.dumps([{"type": "repo", "value": "user/repo"}]))
        assert add_source("user/repo", sources_file) is False

    def test_add_source_tme_url(self, sources_file):
        sources_file.write_text(json.dumps([]))
        assert add_source("t.me/channelname", sources_file) is True
        sources = load_sources(sources_file)
        assert any(s == {"type": "tg", "value": "channelname"} for s in sources)

    def test_add_source_tme_s_url(self, sources_file):
        sources_file.write_text(json.dumps([]))
        assert add_source("t.me/s/channelname", sources_file) is True
        sources = load_sources(sources_file)
        assert any(s == {"type": "tg", "value": "channelname"} for s in sources)

    def test_add_source_tme_https(self, sources_file):
        sources_file.write_text(json.dumps([]))
        assert add_source("https://t.me/channelname", sources_file) is True
        sources = load_sources(sources_file)
        assert any(s == {"type": "tg", "value": "channelname"} for s in sources)

    def test_add_source_tme_http(self, sources_file):
        sources_file.write_text(json.dumps([]))
        assert add_source("http://t.me/channelname", sources_file) is True
        sources = load_sources(sources_file)
        assert any(s == {"type": "tg", "value": "channelname"} for s in sources)

    def test_add_source_tme_no_duplicate(self, sources_file):
        sources_file.write_text(json.dumps([{"type": "tg", "value": "channelname"}]))
        assert add_source("t.me/channelname", sources_file) is False


class TestSyncStars:
    @patch("vpn_collector.sources._clean_session")
    def test_adds_new_repos(self, mock_clean_session, sources_file):
        sources_file.write_text(json.dumps([]))
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.side_effect = [
            [{"full_name": "user/vpn-repo1"}, {"full_name": "user/vpn-repo2"}],
            [],
        ]
        mock_resp.status_code = 200
        mock_session.get.return_value = mock_resp
        mock_clean_session.return_value = mock_session
        assert sync_stars("testuser", sources_file) == 2

    @patch("vpn_collector.sources._clean_session")
    def test_skips_existing(self, mock_clean_session, sources_file):
        sources_file.write_text(json.dumps([{"type": "repo", "value": "user/vpn-repo1"}]))
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.side_effect = [[{"full_name": "user/vpn-repo1"}], []]
        mock_resp.status_code = 200
        mock_session.get.return_value = mock_resp
        mock_clean_session.return_value = mock_session
        assert sync_stars("testuser", sources_file) == 0


class TestFetchUrlConfigs:
    @patch("vpn_collector.sources.requests.Session")
    def test_returns_configs(self, MockSession):
        mock_resp = MagicMock()
        mock_resp.text = f"{VLESS1}\n{VLESS2}\n{VLESS3}\n"
        mock_resp.status_code = 200
        mock_instance = MagicMock()
        mock_instance.get.return_value = mock_resp
        mock_instance.trust_env = True
        MockSession.return_value = mock_instance
        assert len(fetch_url_configs("https://example.com/sub.txt")) == 3

    @patch("vpn_collector.sources.requests.Session")
    def test_returns_empty_on_error(self, MockSession):
        mock_instance = MagicMock()
        mock_instance.get.side_effect = Exception("connection error")
        MockSession.return_value = mock_instance
        assert fetch_url_configs("https://example.com/sub.txt") == []


class TestIsFetchable:
    def test_txt_file_allowed(self):
        assert _is_fetchable("configs/nodes.txt") is True

    def test_no_extension_allowed(self):
        assert _is_fetchable("configs/sub") is True
        assert _is_fetchable("vmess") is True

    def test_skip_extensions_blocked(self):
        # yaml/yml now allowed (Clash configs live in yaml files)
        assert _is_fetchable("config.yml") is True
        assert _is_fetchable("config.yaml") is True
        assert _is_fetchable("config.json") is False
        assert _is_fetchable("README.md") is False
        assert _is_fetchable("install.sh") is False
        assert _is_fetchable("setup.py") is False

    def test_skip_filenames_blocked(self):
        assert _is_fetchable("readme.txt") is False
        assert _is_fetchable("LICENSE") is False
        assert _is_fetchable("changelog.md") is False

    def test_other_extensions_allowed(self):
        assert _is_fetchable("nodes.conf") is True
        assert _is_fetchable("subs.list") is True
        assert _is_fetchable("configs.csv") is True


class TestFetchRepoConfigs:
    @patch("vpn_collector.sources.requests.Session")
    def test_fetches_txt_and_extensionless_files(self, MockSession, tmp_path):
        tree_resp = MagicMock()
        tree_resp.status_code = 200
        tree_resp.json.return_value = {
            "tree": [
                {"type": "blob", "path": "sub.txt"},
                {"type": "blob", "path": "subdir/nodes"},   # no extension
                {"type": "blob", "path": "README.md"},      # skipped (.md)
                {"type": "blob", "path": "config.yml"},     # fetched (yaml allowed now)
                {"type": "tree", "path": "subdir"},
            ]
        }
        file_resp = MagicMock()
        file_resp.status_code = 200
        file_resp.text = f"{VLESS1}\n{VLESS2}\n{VLESS3}\n"
        mock_instance = MagicMock()
        # tree + 3 blob fetches (sub.txt, nodes, config.yml), README.md skipped
        mock_instance.get.side_effect = [tree_resp, file_resp, file_resp, file_resp]
        MockSession.return_value = mock_instance
        configs = fetch_repo_configs("user/repo")
        assert len(configs) == 3  # deduped across three identical files
