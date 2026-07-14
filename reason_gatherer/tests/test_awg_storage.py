import json
import zipfile
import pytest
from pathlib import Path
from unittest.mock import patch

SAMPLE_CONF = """[Interface]
PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
Jc = 4

[Peer]
PublicKey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=
Endpoint = 185.123.45.67:51820
AllowedIPs = 0.0.0.0/0"""

ENDPOINT = "185.123.45.67:51820"


@pytest.fixture()
def tmp_dirs(tmp_path, monkeypatch):
    results_dir = tmp_path / "results_awg"
    known_good_dir = results_dir / "known_good"
    import awg_collector.storage as stor
    monkeypatch.setattr(stor, "RESULTS_AWG_DIR", results_dir)
    monkeypatch.setattr(stor, "KNOWN_GOOD_DIR", known_good_dir)
    return results_dir, known_good_dir


class TestSaveLoadKnownGood:
    def test_save_creates_file(self, tmp_dirs):
        from awg_collector.storage import save_known_good
        results_dir, known_good_dir = tmp_dirs
        path = save_known_good(SAMPLE_CONF, ENDPOINT)
        assert path.exists()
        assert path.name == "185.123.45.67_51820.conf"

    def test_save_writes_content(self, tmp_dirs):
        from awg_collector.storage import save_known_good
        save_known_good(SAMPLE_CONF, ENDPOINT)
        results_dir, known_good_dir = tmp_dirs
        content = (known_good_dir / "185.123.45.67_51820.conf").read_text()
        assert "Jc = 4" in content

    def test_load_returns_saved(self, tmp_dirs):
        from awg_collector.storage import save_known_good, load_known_good
        save_known_good(SAMPLE_CONF, ENDPOINT)
        configs = load_known_good()
        assert len(configs) == 1
        assert configs[0]["endpoint"] == ENDPOINT
        assert "Jc = 4" in configs[0]["text"]

    def test_load_empty_when_no_dir(self, tmp_dirs):
        from awg_collector.storage import load_known_good
        configs = load_known_good()
        assert configs == []

    def test_remove_deletes_file(self, tmp_dirs):
        from awg_collector.storage import save_known_good, remove_known_good, load_known_good
        save_known_good(SAMPLE_CONF, ENDPOINT)
        remove_known_good(ENDPOINT)
        assert load_known_good() == []

    def test_remove_nonexistent_no_error(self, tmp_dirs):
        from awg_collector.storage import remove_known_good
        remove_known_good("1.2.3.4:51820")  # should not raise


class TestBuildVpnArchive:
    def test_creates_zip(self, tmp_dirs):
        from awg_collector.storage import save_known_good, build_vpn_archive
        save_known_good(SAMPLE_CONF, ENDPOINT)
        archive = build_vpn_archive()
        assert archive.exists()
        assert archive.suffix == ".vpn"

    def test_zip_contains_conf(self, tmp_dirs):
        from awg_collector.storage import save_known_good, build_vpn_archive
        save_known_good(SAMPLE_CONF, ENDPOINT)
        archive = build_vpn_archive()
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
        assert "185.123.45.67_51820.conf" in names

    def test_zip_conf_content_correct(self, tmp_dirs):
        from awg_collector.storage import save_known_good, build_vpn_archive
        save_known_good(SAMPLE_CONF, ENDPOINT)
        archive = build_vpn_archive()
        with zipfile.ZipFile(archive) as zf:
            content = zf.read("185.123.45.67_51820.conf").decode()
        assert "Jc = 4" in content

    def test_empty_known_good_creates_empty_zip(self, tmp_dirs):
        from awg_collector.storage import build_vpn_archive
        results_dir, known_good_dir = tmp_dirs
        known_good_dir.mkdir(parents=True)
        archive = build_vpn_archive()
        with zipfile.ZipFile(archive) as zf:
            assert zf.namelist() == []


class TestConfigMeta:
    def test_load_returns_empty_when_no_file(self, tmp_dirs):
        from awg_collector.storage import load_config_meta
        assert load_config_meta() == {}

    def test_save_and_load_roundtrip(self, tmp_dirs):
        from awg_collector.storage import save_config_meta, load_config_meta
        meta = {ENDPOINT: {"first_seen": "2026-07-14", "fail_streak": 0}}
        save_config_meta(meta)
        loaded = load_config_meta()
        assert loaded == meta

    def test_update_first_seen_sets_entry(self, tmp_dirs):
        from awg_collector.storage import update_meta_first_seen
        meta = {}
        update_meta_first_seen(meta, ENDPOINT, "2026-07-14")
        assert meta[ENDPOINT]["first_seen"] == "2026-07-14"
        assert meta[ENDPOINT]["fail_streak"] == 0

    def test_update_first_seen_does_not_overwrite(self, tmp_dirs):
        from awg_collector.storage import update_meta_first_seen
        meta = {ENDPOINT: {"first_seen": "2026-07-01", "fail_streak": 0}}
        update_meta_first_seen(meta, ENDPOINT, "2026-07-14")
        assert meta[ENDPOINT]["first_seen"] == "2026-07-01"


class TestCandidates:
    def test_save_and_load_roundtrip(self, tmp_dirs):
        from awg_collector.storage import save_candidates, load_candidates
        configs = [{"text": SAMPLE_CONF, "endpoint": ENDPOINT, "filename": "x.conf"}]
        save_candidates(configs)
        loaded = load_candidates()
        assert len(loaded) == 1
        assert "Jc = 4" in loaded[0]

    def test_load_empty_when_no_file(self, tmp_dirs):
        from awg_collector.storage import load_candidates
        assert load_candidates() == []
