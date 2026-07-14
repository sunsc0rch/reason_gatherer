import pytest
from pathlib import Path
from awg_collector.parser import parse_awg_configs, parse_awg_file

VALID_AWG = """[Interface]
PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
Address = 10.8.0.2/32
DNS = 1.1.1.1
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
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = 185.123.45.67:51820
PersistentKeepalive = 25"""

VALID_WG_ONLY = """[Interface]
PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
Address = 10.8.0.2/32

[Peer]
PublicKey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=
AllowedIPs = 0.0.0.0/0
Endpoint = 1.2.3.4:51820"""

MISSING_ENDPOINT = """[Interface]
PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
Jc = 4

[Peer]
PublicKey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=
AllowedIPs = 0.0.0.0/0"""


class TestParseAwgConfigs:
    def test_valid_awg_returns_one_config(self):
        results = parse_awg_configs(VALID_AWG)
        assert len(results) == 1

    def test_valid_awg_is_awg_true(self):
        results = parse_awg_configs(VALID_AWG)
        assert results[0]["is_awg"] is True

    def test_valid_awg_endpoint_extracted(self):
        results = parse_awg_configs(VALID_AWG)
        assert results[0]["endpoint"] == "185.123.45.67:51820"

    def test_valid_awg_filename_from_endpoint(self):
        results = parse_awg_configs(VALID_AWG)
        assert results[0]["filename"] == "185.123.45.67_51820.conf"

    def test_valid_awg_text_preserved(self):
        results = parse_awg_configs(VALID_AWG)
        assert "PrivateKey" in results[0]["text"]
        assert "Jc = 4" in results[0]["text"]

    def test_wg_only_is_awg_false(self):
        results = parse_awg_configs(VALID_WG_ONLY)
        assert len(results) == 1
        assert results[0]["is_awg"] is False

    def test_missing_endpoint_skipped(self):
        results = parse_awg_configs(MISSING_ENDPOINT)
        assert results == []

    def test_empty_text_returns_empty(self):
        assert parse_awg_configs("") == []

    def test_multiple_configs_in_text(self):
        two_configs = VALID_AWG + "\n\n" + VALID_AWG.replace("185.123.45.67:51820", "10.0.0.1:51820")
        results = parse_awg_configs(two_configs)
        assert len(results) == 2

    def test_domain_endpoint_accepted(self):
        conf = VALID_AWG.replace("185.123.45.67:51820", "vpn.example.com:51820")
        results = parse_awg_configs(conf)
        assert results[0]["endpoint"] == "vpn.example.com:51820"
        assert results[0]["filename"] == "vpn.example.com_51820.conf"

    def test_invalid_port_skipped(self):
        conf = VALID_AWG.replace("185.123.45.67:51820", "185.123.45.67:99999")
        assert parse_awg_configs(conf) == []

    def test_missing_private_key_skipped(self):
        conf = VALID_AWG.replace("PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=\n", "")
        assert parse_awg_configs(conf) == []


class TestParseAwgFile:
    def test_reads_file(self, tmp_path):
        p = tmp_path / "test.conf"
        p.write_text(VALID_AWG)
        results = parse_awg_file(p)
        assert len(results) == 1
        assert results[0]["endpoint"] == "185.123.45.67:51820"

    def test_missing_file_returns_empty(self, tmp_path):
        results = parse_awg_file(tmp_path / "nonexistent.conf")
        assert results == []
