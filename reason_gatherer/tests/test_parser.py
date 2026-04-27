import base64
import pytest
from vpn_collector.parser import (
    is_vpn_line, extract_host_port, extract_name, set_name,
    parse_configs_from_content, is_vpn_file,
)

VLESS = "vless://some-uuid@1.2.3.4:443?type=tcp&security=tls#MyServer"
VMESS_PAYLOAD = '{"v":"2","ps":"vmess_server","add":"5.6.7.8","port":"8080","id":"uuid123","aid":"0","net":"tcp","type":"none","host":"","path":"","tls":""}'
VMESS = "vmess://" + base64.b64encode(VMESS_PAYLOAD.encode()).decode()
TROJAN = "trojan://password123@9.10.11.12:443?sni=example.com#TrojanServer"
SS = "ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ=@13.14.15.16:8388#SSServer"
HY2 = "hy2://mypassword@17.18.19.20:443?sni=test.com#HysteriaServer"
TUIC = "tuic://myuuid:mypass@21.22.23.24:443?sni=tuic.com#TuicServer"


class TestIsVpnLine:
    def test_vless(self):
        assert is_vpn_line(VLESS) is True

    def test_vmess(self):
        assert is_vpn_line(VMESS) is True

    def test_trojan(self):
        assert is_vpn_line(TROJAN) is True

    def test_ss(self):
        assert is_vpn_line(SS) is True

    def test_hy2(self):
        assert is_vpn_line(HY2) is True

    def test_tuic(self):
        assert is_vpn_line(TUIC) is True

    def test_plain_text(self):
        assert is_vpn_line("This is a readme line") is False

    def test_empty(self):
        assert is_vpn_line("") is False

    def test_comment(self):
        assert is_vpn_line("# comment") is False


class TestExtractHostPort:
    def test_vless(self):
        assert extract_host_port(VLESS) == ("1.2.3.4", 443)

    def test_trojan(self):
        assert extract_host_port(TROJAN) == ("9.10.11.12", 443)

    def test_ss(self):
        assert extract_host_port(SS) == ("13.14.15.16", 8388)

    def test_hy2(self):
        assert extract_host_port(HY2) == ("17.18.19.20", 443)

    def test_tuic(self):
        assert extract_host_port(TUIC) == ("21.22.23.24", 443)

    def test_vmess(self):
        assert extract_host_port(VMESS) == ("5.6.7.8", 8080)

    def test_invalid_returns_none(self):
        assert extract_host_port("not-a-config") is None


class TestExtractSetName:
    def test_extract_name(self):
        assert extract_name(VLESS) == "MyServer"

    def test_extract_name_no_fragment(self):
        assert extract_name("vless://uuid@host:443?type=tcp") == ""

    def test_set_name_replaces_existing(self):
        result = set_name(VLESS, "+++MyServer")
        assert result.endswith("#+++MyServer")
        assert result.startswith("vless://")

    def test_set_name_no_existing_name(self):
        config = "vless://uuid@host:443?type=tcp"
        result = set_name(config, "+++NewName")
        assert result.endswith("#+++NewName")


class TestParseConfigsFromContent:
    def test_plain_list(self):
        content = f"{VLESS}\n{TROJAN}\nsome random line\n{SS}"
        result = parse_configs_from_content(content)
        assert len(result) == 3
        assert VLESS in result

    def test_base64_encoded_list(self):
        raw = f"{VLESS}\n{TROJAN}\n{SS}"
        encoded = base64.b64encode(raw.encode()).decode()
        result = parse_configs_from_content(encoded)
        assert len(result) == 3

    def test_empty_content(self):
        assert parse_configs_from_content("") == []

    def test_deduplicates(self):
        content = f"{VLESS}\n{VLESS}\n{TROJAN}"
        result = parse_configs_from_content(content)
        assert len(result) == 2


class TestIsVpnFile:
    def test_detects_plain_vpn_file(self):
        content = f"{VLESS}\n{TROJAN}\n{SS}\n"
        assert is_vpn_file("sub.txt", content) is True

    def test_skips_readme(self):
        content = f"{VLESS}\n{TROJAN}\n{SS}\n"
        assert is_vpn_file("README.md", content) is False

    def test_skips_requirements(self):
        assert is_vpn_file("requirements.txt", "requests==2.31.0\naiohttp==3.9.5\n") is False

    def test_skips_yaml(self):
        assert is_vpn_file("workflow.yml", f"{VLESS}\n{TROJAN}\n{SS}") is False

    def test_rejects_non_vpn_content(self):
        assert is_vpn_file("data.txt", "hello world\nfoo bar\nbaz qux") is False

    def test_fewer_than_3_configs_not_vpn_file(self):
        assert is_vpn_file("sub.txt", f"{VLESS}\n{TROJAN}") is False
