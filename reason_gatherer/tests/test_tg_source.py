import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from vpn_collector.tg_source import load_tg_auth, save_tg_auth, is_tg_configured, fetch_tg_channel_configs, fetch_all_tg_configs


class TestLoadTgAuth:
    def test_returns_none_when_file_missing(self, tmp_path):
        auth_file = tmp_path / "tg_auth.json"
        with patch("vpn_collector.tg_source.TG_AUTH_FILE", auth_file):
            assert load_tg_auth() is None

    def test_returns_dict_when_file_present(self, tmp_path):
        auth_file = tmp_path / "tg_auth.json"
        auth_file.write_text(json.dumps({"api_id": 123, "api_hash": "abc"}))
        with patch("vpn_collector.tg_source.TG_AUTH_FILE", auth_file):
            result = load_tg_auth()
        assert result == {"api_id": 123, "api_hash": "abc"}


class TestSaveTgAuth:
    def test_creates_dir_and_writes_file(self, tmp_path):
        auth_file = tmp_path / "subdir" / "tg_auth.json"
        with patch("vpn_collector.tg_source.TG_AUTH_FILE", auth_file):
            save_tg_auth(99999, "myhash")
        data = json.loads(auth_file.read_text())
        assert data["api_id"] == 99999
        assert data["api_hash"] == "myhash"


class TestIsTgConfigured:
    def test_false_when_auth_missing(self, tmp_path):
        auth_file = tmp_path / "tg_auth.json"
        with patch("vpn_collector.tg_source.TG_AUTH_FILE", auth_file), \
             patch("vpn_collector.tg_source.TG_SESSION_FILE", tmp_path / "tg"):
            assert is_tg_configured() is False

    def test_false_when_session_missing(self, tmp_path):
        auth_file = tmp_path / "tg_auth.json"
        auth_file.write_text(json.dumps({"api_id": 1, "api_hash": "h"}))
        with patch("vpn_collector.tg_source.TG_AUTH_FILE", auth_file), \
             patch("vpn_collector.tg_source.TG_SESSION_FILE", tmp_path / "tg"):
            assert is_tg_configured() is False

    def test_true_when_both_present(self, tmp_path):
        auth_file = tmp_path / "tg_auth.json"
        auth_file.write_text(json.dumps({"api_id": 1, "api_hash": "h"}))
        session_file = tmp_path / "tg.session"
        session_file.write_text("session")
        with patch("vpn_collector.tg_source.TG_AUTH_FILE", auth_file), \
             patch("vpn_collector.tg_source.TG_SESSION_FILE", tmp_path / "tg"):
            assert is_tg_configured() is True


class TestFetchTgChannelConfigs:
    async def test_parses_vpn_configs_from_posts(self):
        VLESS = "vless://uuid@1.2.3.4:443?type=tcp#Server"
        mock_message = MagicMock()
        mock_message.text = f"Check this config:\n{VLESS}\nEnjoy!"

        async def fake_get_messages(channel, limit):
            return [mock_message]

        mock_client = MagicMock()
        mock_client.get_messages = fake_get_messages

        result = await fetch_tg_channel_configs(mock_client, "testchannel", limit=10)
        assert VLESS in result

    async def test_skips_posts_without_configs(self):
        mock_message = MagicMock()
        mock_message.text = "Just a regular post with no VPN configs here."

        async def fake_get_messages(channel, limit):
            return [mock_message]

        mock_client = MagicMock()
        mock_client.get_messages = fake_get_messages

        result = await fetch_tg_channel_configs(mock_client, "testchannel", limit=10)
        assert result == []

    async def test_returns_empty_on_access_error(self):
        async def fake_get_messages(channel, limit):
            raise Exception("channel not found")

        mock_client = MagicMock()
        mock_client.get_messages = fake_get_messages

        result = await fetch_tg_channel_configs(mock_client, "privatechannel", limit=10)
        assert result == []


class TestFetchAllTgConfigs:
    async def test_returns_empty_when_auth_missing(self, tmp_path):
        auth_file = tmp_path / "tg_auth.json"
        with patch("vpn_collector.tg_source.TG_AUTH_FILE", auth_file):
            result = await fetch_all_tg_configs(["channel1"])
        assert result == []

    async def test_returns_empty_when_session_missing(self, tmp_path):
        auth_file = tmp_path / "tg_auth.json"
        auth_file.write_text(json.dumps({"api_id": 1, "api_hash": "h"}))
        with patch("vpn_collector.tg_source.TG_AUTH_FILE", auth_file), \
             patch("vpn_collector.tg_source.TG_SESSION_FILE", tmp_path / "tg"):
            result = await fetch_all_tg_configs(["channel1"])
        assert result == []
