import pytest
from pathlib import Path
from vpn_collector.storage import (
    load_known_hosts, is_duplicate, save_config,
    rotate_run_files, get_stats, update_known_good_header,
)

VLESS1 = "vless://uuid1@1.2.3.4:443?type=tcp#Server1"
VLESS2 = "vless://uuid2@5.6.7.8:8080?type=tcp#Server2"
VLESS3 = "vless://uuid3@9.10.11.12:443?type=tcp#Server3"


@pytest.fixture
def results_dir(tmp_path):
    d = tmp_path / "results"
    d.mkdir()
    return d


class TestLoadKnownHosts:
    def test_empty_dir(self, results_dir):
        assert load_known_hosts(results_dir) == set()

    def test_loads_from_known_good(self, results_dir):
        (results_dir / "known_good.txt").write_text(f"# header\n{VLESS1}\n{VLESS2}\n")
        hosts = load_known_hosts(results_dir)
        assert "1.2.3.4:443" in hosts
        assert "5.6.7.8:8080" in hosts

    def test_loads_from_run_files(self, results_dir):
        (results_dir / "run_2026-01-01.txt").write_text(f"{VLESS3}\n")
        hosts = load_known_hosts(results_dir)
        assert "9.10.11.12:443" in hosts

    def test_skips_comment_lines(self, results_dir):
        (results_dir / "known_good.txt").write_text("# Updated: 2026-01-01 | Total: 1\n")
        hosts = load_known_hosts(results_dir)
        assert len(hosts) == 0


class TestIsDuplicate:
    def test_detects_duplicate(self):
        assert is_duplicate(VLESS1, {"1.2.3.4:443"}) is True

    def test_not_duplicate(self):
        assert is_duplicate(VLESS1, {"9.9.9.9:80"}) is False

    def test_same_host_different_name_is_duplicate(self):
        config = "vless://otheruuid@1.2.3.4:443?type=tcp#DifferentName"
        assert is_duplicate(config, {"1.2.3.4:443"}) is True


class TestSaveConfig:
    def test_saves_to_known_good_and_run(self, results_dir):
        known: set[str] = set()
        save_config(VLESS1, results_dir, known, run_date="2026-04-27")
        assert (results_dir / "known_good.txt").exists()
        assert (results_dir / "run_2026-04-27.txt").exists()
        assert VLESS1 in (results_dir / "known_good.txt").read_text()
        assert VLESS1 in (results_dir / "run_2026-04-27.txt").read_text()

    def test_updates_known_hosts_set(self, results_dir):
        known: set[str] = set()
        save_config(VLESS1, results_dir, known, run_date="2026-04-27")
        assert "1.2.3.4:443" in known


class TestRotateRunFiles:
    def test_keeps_max_files(self, results_dir):
        for i in range(6):
            (results_dir / f"run_2026-01-0{i+1}.txt").write_text("x")
        rotate_run_files(results_dir, max_files=5)
        assert len(list(results_dir.glob("run_*.txt"))) == 5

    def test_removes_oldest(self, results_dir):
        for i in range(6):
            (results_dir / f"run_2026-01-0{i+1}.txt").write_text("x")
        rotate_run_files(results_dir, max_files=5)
        assert not (results_dir / "run_2026-01-01.txt").exists()
        assert (results_dir / "run_2026-01-06.txt").exists()

    def test_does_not_touch_known_good(self, results_dir):
        for i in range(6):
            (results_dir / f"run_2026-01-0{i+1}.txt").write_text("x")
        (results_dir / "known_good.txt").write_text("important")
        rotate_run_files(results_dir, max_files=5)
        assert (results_dir / "known_good.txt").exists()


class TestGetStats:
    def test_returns_counts(self, results_dir):
        (results_dir / "known_good.txt").write_text(f"# header\n{VLESS1}\n{VLESS2}\n")
        (results_dir / "run_2026-04-27.txt").write_text(f"{VLESS1}\n")
        stats = get_stats(results_dir)
        assert stats["known_good"] == 2
        assert stats["run_2026-04-27"] == 1
