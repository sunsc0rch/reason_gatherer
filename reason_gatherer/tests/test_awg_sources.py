import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

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


# ---------------------------------------------------------------------------
# tg_source unit tests
# ---------------------------------------------------------------------------

TG_SAMPLE_CONF = """[Interface]
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
Endpoint = 10.0.0.1:51820
PersistentKeepalive = 25"""


class TestIsTgConfigured:
    def test_returns_false_when_files_missing(self, tmp_path):
        from awg_collector import tg_source
        with (
            patch.object(tg_source, "TG_AUTH_FILE", tmp_path / "tg_auth.json"),
            patch.object(tg_source, "TG_SESSION_FILE", tmp_path / "tg"),
        ):
            assert tg_source.is_tg_configured() is False

    def test_returns_false_when_only_auth_exists(self, tmp_path):
        from awg_collector import tg_source
        auth = tmp_path / "tg_auth.json"
        auth.write_text("{}")
        with (
            patch.object(tg_source, "TG_AUTH_FILE", auth),
            patch.object(tg_source, "TG_SESSION_FILE", tmp_path / "tg"),
        ):
            assert tg_source.is_tg_configured() is False

    def test_returns_false_when_only_session_exists(self, tmp_path):
        from awg_collector import tg_source
        session = tmp_path / "tg.session"
        session.write_text("")
        with (
            patch.object(tg_source, "TG_AUTH_FILE", tmp_path / "tg_auth.json"),
            patch.object(tg_source, "TG_SESSION_FILE", tmp_path / "tg"),
        ):
            assert tg_source.is_tg_configured() is False

    def test_returns_true_when_both_exist(self, tmp_path):
        from awg_collector import tg_source
        auth = tmp_path / "tg_auth.json"
        auth.write_text("{}")
        session = tmp_path / "tg.session"
        session.write_text("")
        with (
            patch.object(tg_source, "TG_AUTH_FILE", auth),
            patch.object(tg_source, "TG_SESSION_FILE", tmp_path / "tg"),
        ):
            assert tg_source.is_tg_configured() is True


class TestLoadTgAuth:
    def test_returns_none_when_file_missing(self, tmp_path):
        from awg_collector import tg_source
        with patch.object(tg_source, "TG_AUTH_FILE", tmp_path / "tg_auth.json"):
            assert tg_source.load_tg_auth() is None

    def test_returns_dict_when_file_exists(self, tmp_path):
        from awg_collector import tg_source
        auth = tmp_path / "tg_auth.json"
        auth.write_text(json.dumps({"api_id": 123, "api_hash": "abc"}))
        with patch.object(tg_source, "TG_AUTH_FILE", auth):
            result = tg_source.load_tg_auth()
        assert result == {"api_id": 123, "api_hash": "abc"}


class TestTelethonProxy:
    PROXY_VARS = ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy")

    def _clear_proxy_env(self, monkeypatch):
        for var in self.PROXY_VARS:
            monkeypatch.delenv(var, raising=False)

    def test_returns_none_when_no_env_vars(self, monkeypatch):
        from awg_collector import tg_source
        self._clear_proxy_env(monkeypatch)
        assert tg_source._telethon_proxy() is None

    def test_returns_none_when_env_vars_empty(self, monkeypatch):
        from awg_collector import tg_source
        self._clear_proxy_env(monkeypatch)
        monkeypatch.setenv("ALL_PROXY", "")
        assert tg_source._telethon_proxy() is None

    def test_returns_tuple_for_socks5_proxy(self, monkeypatch):
        from awg_collector import tg_source
        self._clear_proxy_env(monkeypatch)
        monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:1080")
        try:
            import socks  # noqa: F401
        except ImportError:
            pytest.skip("PySocks not installed")
        result = tg_source._telethon_proxy()
        assert result is not None
        assert isinstance(result, tuple)
        assert len(result) == 3
        _proxy_type, host, port = result
        assert host == "127.0.0.1"
        assert port == 1080

    def test_returns_tuple_for_http_proxy(self, monkeypatch):
        from awg_collector import tg_source
        self._clear_proxy_env(monkeypatch)
        monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.com:8080")
        try:
            import socks  # noqa: F401
        except ImportError:
            pytest.skip("PySocks not installed")
        result = tg_source._telethon_proxy()
        assert result is not None
        _proxy_type, host, port = result
        assert host == "proxy.example.com"
        assert port == 8080


class TestFetchTgChannelConfigs:
    def _make_text_msg(self, text: str):
        msg = MagicMock()
        msg.text = text
        msg.document = None
        return msg

    def _make_doc_msg(self, file_name: str, content: str):
        msg = MagicMock()
        msg.text = None
        attr = MagicMock()
        attr.file_name = file_name
        msg.document.attributes = [attr]
        return msg, content.encode("utf-8")

    def test_parses_interface_block_from_text(self):
        from awg_collector.tg_source import fetch_tg_channel_configs

        msg = self._make_text_msg(TG_SAMPLE_CONF)
        client = MagicMock()
        client.get_messages = AsyncMock(return_value=[msg])

        result = asyncio.run(fetch_tg_channel_configs(client, "testchannel", 10))
        assert len(result) == 1
        assert result[0]["endpoint"] == "10.0.0.1:51820"
        assert result[0]["is_awg"] is True

    def test_skips_messages_without_interface_block(self):
        from awg_collector.tg_source import fetch_tg_channel_configs

        msg = self._make_text_msg("Just some random text without config")
        client = MagicMock()
        client.get_messages = AsyncMock(return_value=[msg])

        result = asyncio.run(fetch_tg_channel_configs(client, "testchannel", 10))
        assert result == []

    def test_skips_none_messages(self):
        from awg_collector.tg_source import fetch_tg_channel_configs

        client = MagicMock()
        client.get_messages = AsyncMock(return_value=[None, None])

        result = asyncio.run(fetch_tg_channel_configs(client, "testchannel", 10))
        assert result == []

    def test_parses_conf_attachment(self):
        from awg_collector.tg_source import fetch_tg_channel_configs

        msg, content_bytes = self._make_doc_msg("config.conf", TG_SAMPLE_CONF)
        msg.text = None
        client = MagicMock()
        client.get_messages = AsyncMock(return_value=[msg])
        client.download_media = AsyncMock(return_value=content_bytes)

        result = asyncio.run(fetch_tg_channel_configs(client, "testchannel", 10))
        assert len(result) == 1
        assert result[0]["endpoint"] == "10.0.0.1:51820"

    def test_ignores_non_conf_attachment(self):
        from awg_collector.tg_source import fetch_tg_channel_configs

        msg, content_bytes = self._make_doc_msg("readme.txt", TG_SAMPLE_CONF)
        msg.text = None
        client = MagicMock()
        client.get_messages = AsyncMock(return_value=[msg])
        client.download_media = AsyncMock(return_value=content_bytes)

        result = asyncio.run(fetch_tg_channel_configs(client, "testchannel", 10))
        assert result == []

    def test_returns_empty_on_client_exception(self):
        from awg_collector.tg_source import fetch_tg_channel_configs

        client = MagicMock()
        client.get_messages = AsyncMock(side_effect=Exception("connection refused"))

        result = asyncio.run(fetch_tg_channel_configs(client, "testchannel", 10))
        assert result == []

    def test_attribute_iteration_finds_filename(self):
        """Verify that file_name is found even if it's not the last attribute."""
        from awg_collector.tg_source import fetch_tg_channel_configs

        msg = MagicMock()
        msg.text = None
        # First attr has no file_name, second does
        attr1 = MagicMock(spec=[])  # no file_name attr
        attr2 = MagicMock()
        attr2.file_name = "config.conf"
        msg.document.attributes = [attr1, attr2]

        client = MagicMock()
        client.get_messages = AsyncMock(return_value=[msg])
        client.download_media = AsyncMock(return_value=TG_SAMPLE_CONF.encode())

        result = asyncio.run(fetch_tg_channel_configs(client, "testchannel", 10))
        assert len(result) == 1
