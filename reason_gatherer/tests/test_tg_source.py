import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from vpn_collector.tg_source import load_tg_auth, save_tg_auth, is_tg_configured


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
