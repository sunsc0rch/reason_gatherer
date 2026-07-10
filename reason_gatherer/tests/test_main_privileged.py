import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import date

from vpn_collector.main import _update_privileged
from vpn_collector.storage import load_privileged, save_privileged, load_config_meta, save_config_meta

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


class TestUpdatePrivileged:
    def test_promotes_old_server(self, results_dir):
        """Сервер с first_seen >7 дней назад и прошедший recheck → в privileged."""
        meta = {"1.2.3.4:443": {"first_seen": "2026-07-01", "fail_streak": 0}}
        save_config_meta(results_dir, meta)

        with patch("vpn_collector.main.PRIVILEGED_MIN_DAYS", 7):
            _update_privileged(
                results_dir=results_dir,
                survivors=[VLESS1],
                dead_configs=[],
                singbox_path="/fake/singbox",
                meta=meta,
                today="2026-07-10",
            )

        assert VLESS1 in load_privileged(results_dir)

    def test_does_not_promote_new_server(self, results_dir):
        """Сервер с first_seen <7 дней назад не попадает в privileged."""
        meta = {"1.2.3.4:443": {"first_seen": "2026-07-09", "fail_streak": 0}}
        save_config_meta(results_dir, meta)

        _update_privileged(
            results_dir=results_dir,
            survivors=[VLESS1],
            dead_configs=[],
            singbox_path="/fake/singbox",
            meta=meta,
            today="2026-07-10",
        )

        assert VLESS1 not in load_privileged(results_dir)

    def test_removes_dead_after_retries(self, results_dir):
        """Сервер в privileged, не прошедший recheck и повторные проверки → удалить."""
        save_privileged(results_dir, [VLESS1])
        meta = {"1.2.3.4:443": {"first_seen": "2026-07-01", "fail_streak": 0}}
        save_config_meta(results_dir, meta)

        with (
            patch("vpn_collector.main.PRIVILEGED_RECHECK_RETRIES", 2),
            patch("vpn_collector.main.test_config_tunnel", return_value=None),
            patch("vpn_collector.main.find_free_socks_port", return_value=15000),
        ):
            _update_privileged(
                results_dir=results_dir,
                survivors=[],
                dead_configs=[VLESS1],
                singbox_path="/fake/singbox",
                meta=meta,
                today="2026-07-10",
            )

        assert VLESS1 not in load_privileged(results_dir)

    def test_keeps_privileged_if_retry_passes(self, results_dir):
        """Сервер упал в recheck, но прошёл повторную проверку → остаётся в privileged."""
        save_privileged(results_dir, [VLESS1])
        meta = {"1.2.3.4:443": {"first_seen": "2026-07-01", "fail_streak": 0}}
        save_config_meta(results_dir, meta)

        with (
            patch("vpn_collector.main.PRIVILEGED_RECHECK_RETRIES", 2),
            patch("vpn_collector.main.test_config_tunnel", return_value=VLESS1),
            patch("vpn_collector.main.find_free_socks_port", return_value=15000),
        ):
            _update_privileged(
                results_dir=results_dir,
                survivors=[],
                dead_configs=[VLESS1],
                singbox_path="/fake/singbox",
                meta=meta,
                today="2026-07-10",
            )

        assert VLESS1 in load_privileged(results_dir)
        assert meta["1.2.3.4:443"]["fail_streak"] == 0

    def test_does_not_add_duplicate_to_privileged(self, results_dir):
        """Повторный вызов не дублирует запись в privileged."""
        save_privileged(results_dir, [VLESS1])
        meta = {"1.2.3.4:443": {"first_seen": "2026-07-01", "fail_streak": 0}}
        save_config_meta(results_dir, meta)

        _update_privileged(
            results_dir=results_dir,
            survivors=[VLESS1],
            dead_configs=[],
            singbox_path="/fake/singbox",
            meta=meta,
            today="2026-07-10",
        )

        assert load_privileged(results_dir).count(VLESS1) == 1
