import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import date

VLESS1 = "vless://uuid1@1.2.3.4:443?type=tcp#Server1"
VLESS2 = "vless://uuid2@5.6.7.8:8080?type=tcp#Server2"


@pytest.fixture
def results_dir(tmp_path):
    d = tmp_path / "results"
    d.mkdir()
    return d


class TestCmdTestUpdatesFirstSeen:
    def test_first_seen_written_on_pass(self, results_dir, tmp_path):
        """После успешного tunnel-теста first_seen должен быть записан в config_meta.json."""
        candidates_file = results_dir / "candidates.txt"
        candidates_file.write_text(f"{VLESS1}\n")

        with (
            patch("vpn_collector.main.RESULTS_DIR", results_dir),
            patch("vpn_collector.main.find_singbox", return_value="/fake/singbox"),
            patch("vpn_collector.main.tunnel_filter", return_value=[VLESS1]),
            patch("vpn_collector.main.load_known_hosts", return_value=set()),
            patch("vpn_collector.main.rotate_run_files"),
            patch("vpn_collector.main.trim_candidates", return_value=0),
            patch("vpn_collector.main.load_known_good_hp", return_value=set()),
            patch("vpn_collector.main.save_config"),
        ):
            from vpn_collector.main import cmd_test
            cmd_test()

        meta_file = results_dir / "config_meta.json"
        assert meta_file.exists()
        meta = json.loads(meta_file.read_text())
        assert "1.2.3.4:443" in meta
        assert meta["1.2.3.4:443"]["first_seen"] == date.today().isoformat()
        assert meta["1.2.3.4:443"]["fail_streak"] == 0

    def test_existing_first_seen_not_overwritten(self, results_dir):
        """Повторный тест не должен перезаписывать first_seen."""
        candidates_file = results_dir / "candidates.txt"
        candidates_file.write_text(f"{VLESS1}\n")
        meta_initial = {"1.2.3.4:443": {"first_seen": "2026-06-01", "fail_streak": 0}}
        (results_dir / "config_meta.json").write_text(json.dumps(meta_initial))

        with (
            patch("vpn_collector.main.RESULTS_DIR", results_dir),
            patch("vpn_collector.main.find_singbox", return_value="/fake/singbox"),
            patch("vpn_collector.main.tunnel_filter", return_value=[VLESS1]),
            patch("vpn_collector.main.load_known_hosts", return_value=set()),
            patch("vpn_collector.main.rotate_run_files"),
            patch("vpn_collector.main.trim_candidates", return_value=0),
            patch("vpn_collector.main.load_known_good_hp", return_value=set()),
            patch("vpn_collector.main.save_config"),
        ):
            from vpn_collector.main import cmd_test
            cmd_test()

        meta = json.loads((results_dir / "config_meta.json").read_text())
        assert meta["1.2.3.4:443"]["first_seen"] == "2026-06-01"
