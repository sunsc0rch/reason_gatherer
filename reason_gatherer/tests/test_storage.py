import json
import pytest
from pathlib import Path
from vpn_collector.storage import (
    load_known_hosts, load_known_good_hp, load_tcp_cache, update_tcp_cache,
    trim_candidates, is_duplicate, save_config,
    rotate_run_files, get_stats, update_known_good_header,
    load_config_meta, save_config_meta, update_meta_first_seen,
    load_privileged, save_privileged,
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


class TestLoadKnownGoodHp:
    def test_empty(self, results_dir):
        assert load_known_good_hp(results_dir) == set()

    def test_returns_tuples(self, results_dir):
        (results_dir / "known_good.txt").write_text(f"# header\n{VLESS1}\n{VLESS2}\n")
        hp = load_known_good_hp(results_dir)
        assert ("1.2.3.4", 443) in hp
        assert ("5.6.7.8", 8080) in hp

    def test_skips_comments(self, results_dir):
        (results_dir / "known_good.txt").write_text("# Updated: 2026-01-01 | Total: 0\n")
        assert load_known_good_hp(results_dir) == set()


class TestTcpCache:
    def test_empty(self, results_dir):
        assert load_tcp_cache(results_dir) == set()

    def test_roundtrip(self, results_dir):
        update_tcp_cache(results_dir, [("1.2.3.4", 443), ("5.6.7.8", 8080)])
        cache = load_tcp_cache(results_dir)
        assert ("1.2.3.4", 443) in cache
        assert ("5.6.7.8", 8080) in cache

    def test_appends_on_second_call(self, results_dir):
        update_tcp_cache(results_dir, [("1.2.3.4", 443)])
        update_tcp_cache(results_dir, [("5.6.7.8", 8080)])
        cache = load_tcp_cache(results_dir)
        assert len(cache) == 2

    def test_not_loaded_as_known_hosts(self, results_dir):
        update_tcp_cache(results_dir, [("1.2.3.4", 443)])
        assert load_known_hosts(results_dir) == set()


class TestTrimCandidates:
    def test_removes_verified_configs(self, results_dir):
        cfile = results_dir / "candidates.txt"
        cfile.write_text(f"{VLESS1}\n{VLESS2}\n{VLESS3}\n")
        known_good_hp = {("1.2.3.4", 443)}
        removed = trim_candidates(cfile, known_good_hp)
        assert removed == 1
        remaining = cfile.read_text().splitlines()
        assert VLESS1 not in remaining
        assert VLESS2 in remaining
        assert VLESS3 in remaining

    def test_no_op_when_nothing_matches(self, results_dir):
        cfile = results_dir / "candidates.txt"
        cfile.write_text(f"{VLESS1}\n{VLESS2}\n")
        removed = trim_candidates(cfile, {("9.9.9.9", 80)})
        assert removed == 0
        assert VLESS1 in cfile.read_text()

    def test_handles_missing_file(self, results_dir):
        removed = trim_candidates(results_dir / "candidates.txt", {("1.2.3.4", 443)})
        assert removed == 0


class TestGetStats:
    def test_returns_counts(self, results_dir):
        (results_dir / "known_good.txt").write_text(f"# header\n{VLESS1}\n{VLESS2}\n")
        (results_dir / "run_2026-04-27.txt").write_text(f"{VLESS1}\n")
        stats = get_stats(results_dir)
        assert stats["known_good"] == 2
        assert stats["run_2026-04-27"] == 1


class TestConfigMeta:
    def test_load_missing_returns_empty(self, results_dir):
        assert load_config_meta(results_dir) == {}

    def test_roundtrip(self, results_dir):
        meta = {"1.2.3.4:443": {"first_seen": "2026-07-01", "fail_streak": 0}}
        save_config_meta(results_dir, meta)
        assert load_config_meta(results_dir) == meta

    def test_update_first_seen_new_entry(self, results_dir):
        meta = {}
        update_meta_first_seen(meta, "1.2.3.4:443", "2026-07-10")
        assert meta["1.2.3.4:443"]["first_seen"] == "2026-07-10"
        assert meta["1.2.3.4:443"]["fail_streak"] == 0

    def test_update_first_seen_does_not_overwrite(self, results_dir):
        meta = {"1.2.3.4:443": {"first_seen": "2026-07-01", "fail_streak": 0}}
        update_meta_first_seen(meta, "1.2.3.4:443", "2026-07-10")
        assert meta["1.2.3.4:443"]["first_seen"] == "2026-07-01"


class TestPrivileged:
    def test_load_missing_returns_empty(self, results_dir):
        assert load_privileged(results_dir) == []

    def test_roundtrip(self, results_dir):
        configs = [VLESS1, VLESS2]
        save_privileged(results_dir, configs)
        assert load_privileged(results_dir) == configs

    def test_save_writes_header(self, results_dir):
        save_privileged(results_dir, [VLESS1])
        text = (results_dir / "privileged.txt").read_text()
        assert text.startswith("# Updated:")
        assert "Total: 1" in text

    def test_skips_comment_lines_on_load(self, results_dir):
        (results_dir / "privileged.txt").write_text(
            f"# Updated: 2026-07-10 | Total: 1\n{VLESS1}\n"
        )
        result = load_privileged(results_dir)
        assert result == [VLESS1]

    def test_save_empty_list(self, results_dir):
        save_privileged(results_dir, [])
        assert load_privileged(results_dir) == []
        assert "Total: 0" in (results_dir / "privileged.txt").read_text()
