import base64
import json
import pytest

from vpn_collector.clash_parser import parse_clash_yaml, is_clash_yaml
from vpn_collector.parser import parse_configs_from_content


def _yaml(proxies_block: str) -> str:
    return f"proxies:\n{proxies_block}"


class TestIsClashYaml:
    def test_detects_proxies_at_start(self):
        assert is_clash_yaml("proxies:\n- type: ss")

    def test_detects_proxies_with_leading_whitespace(self):
        assert is_clash_yaml("  proxies:\n- type: ss")

    def test_rejects_plain_vpn_lines(self):
        assert not is_clash_yaml("vless://uuid@host:443#name")

    def test_rejects_base64_blob(self):
        assert not is_clash_yaml("dmxlc3M6Ly8=")


class TestSsUrl:
    def test_basic(self):
        yaml = _yaml(
            "- type: ss\n"
            "  name: myss\n"
            "  server: 1.2.3.4\n"
            "  port: 8388\n"
            "  cipher: chacha20-ietf-poly1305\n"
            "  password: secret\n"
        )
        result = parse_clash_yaml(yaml)
        assert len(result) == 1
        url = result[0]
        assert url.startswith("ss://")
        assert "1.2.3.4:8388" in url
        assert url.endswith("#myss")
        # userinfo is base64(cipher:password)
        userinfo = url.split("ss://")[1].split("@")[0]
        decoded = base64.b64decode(userinfo + "==").decode()
        assert decoded == "chacha20-ietf-poly1305:secret"

    def test_missing_password_skipped(self):
        yaml = _yaml(
            "- type: ss\n"
            "  server: 1.2.3.4\n"
            "  port: 8388\n"
            "  cipher: aes-128-gcm\n"
        )
        assert parse_clash_yaml(yaml) == []


class TestTrojanUrl:
    def test_basic(self):
        yaml = _yaml(
            "- type: trojan\n"
            "  name: mytrojan\n"
            "  server: example.com\n"
            "  port: 443\n"
            "  password: pass123\n"
            "  sni: example.com\n"
        )
        result = parse_clash_yaml(yaml)
        assert len(result) == 1
        url = result[0]
        assert url.startswith("trojan://")
        assert "example.com:443" in url
        assert "sni=" in url

    def test_ws_network(self):
        yaml = _yaml(
            "- type: trojan\n"
            "  name: t\n"
            "  server: h.com\n"
            "  port: 443\n"
            "  password: pw\n"
            "  network: ws\n"
            "  ws-opts:\n"
            "    path: /path\n"
            "    headers:\n"
            "      Host: h.com\n"
        )
        url = parse_clash_yaml(yaml)[0]
        assert "type=ws" in url
        assert "path=" in url


class TestVmessUrl:
    def test_basic(self):
        uuid = "f836c736-87fc-4fde-aabc-00857ecdff3e"
        yaml = _yaml(
            f"- type: vmess\n"
            f"  name: myvm\n"
            f"  server: 1.2.3.4\n"
            f"  port: 1234\n"
            f"  uuid: {uuid}\n"
            f"  alterId: 0\n"
            f"  cipher: auto\n"
            f"  network: tcp\n"
        )
        result = parse_clash_yaml(yaml)
        assert len(result) == 1
        url = result[0]
        assert url.startswith("vmess://")
        encoded = url[8:]
        data = json.loads(base64.b64decode(encoded + "==").decode())
        assert data["id"] == uuid
        assert data["add"] == "1.2.3.4"
        assert data["ps"] == "myvm"

    def test_ws_network(self):
        uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        yaml = _yaml(
            f"- type: vmess\n"
            f"  name: ws\n"
            f"  server: s.com\n"
            f"  port: 443\n"
            f"  uuid: {uuid}\n"
            f"  alterId: 0\n"
            f"  network: ws\n"
            f"  tls: true\n"
            f"  servername: s.com\n"
            f"  ws-opts:\n"
            f"    path: /ws\n"
            f"    headers:\n"
            f"      Host: s.com\n"
        )
        url = parse_clash_yaml(yaml)[0]
        data = json.loads(base64.b64decode(url[8:] + "==").decode())
        assert data["net"] == "ws"
        assert data["path"] == "/ws"
        assert data["tls"] == "tls"


class TestVlessUrl:
    def test_reality(self):
        uuid = "48ff2b70-e180-582f-8866-d9a2edeed5f5"
        yaml = _yaml(
            f"- type: vless\n"
            f"  name: reality\n"
            f"  server: 1.2.3.4\n"
            f"  port: 23576\n"
            f"  uuid: {uuid}\n"
            f"  tls: true\n"
            f"  flow: xtls-rprx-vision\n"
            f"  servername: www.google.com\n"
            f"  client-fingerprint: chrome\n"
            f"  reality-opts:\n"
            f"    public-key: PUBKEY123\n"
            f"    short-id: \"01\"\n"
            f"  network: tcp\n"
        )
        url = parse_clash_yaml(yaml)[0]
        assert url.startswith("vless://")
        assert uuid in url
        assert "security=reality" in url
        assert "pbk=PUBKEY123" in url
        assert "sid=01" in url
        assert "flow=xtls-rprx-vision" in url

    def test_tls_ws(self):
        uuid = "37d31b7e-818e-4981-91c9-23174d194910"
        yaml = _yaml(
            f"- type: vless\n"
            f"  name: ws\n"
            f"  server: 1.2.3.4\n"
            f"  port: 443\n"
            f"  uuid: {uuid}\n"
            f"  tls: true\n"
            f"  servername: cf.example.com\n"
            f"  network: ws\n"
            f"  ws-opts:\n"
            f"    path: /vless-ws\n"
            f"    headers:\n"
            f"      Host: cf.example.com\n"
        )
        url = parse_clash_yaml(yaml)[0]
        assert "security=tls" in url
        assert "type=ws" in url
        assert "path=" in url


class TestHysteria2Url:
    def test_basic(self):
        yaml = _yaml(
            "- type: hysteria2\n"
            "  name: h2\n"
            "  server: h2.com\n"
            "  port: 443\n"
            "  password: mypass\n"
            "  sni: h2.com\n"
            "  skip-cert-verify: true\n"
        )
        url = parse_clash_yaml(yaml)[0]
        assert url.startswith("hysteria2://")
        assert "h2.com:443" in url
        assert "sni=" in url
        assert "insecure=1" in url

    def test_auth_field_fallback(self):
        yaml = _yaml(
            "- type: hysteria2\n"
            "  name: h2\n"
            "  server: h.com\n"
            "  port: 443\n"
            "  auth: authpass\n"
        )
        url = parse_clash_yaml(yaml)[0]
        assert "authpass" in url


class TestHysteriaUrl:
    def test_basic(self):
        yaml = _yaml(
            "- type: hysteria\n"
            "  name: hy\n"
            "  server: hy.com\n"
            "  port: 20088\n"
            "  auth-str: secret\n"
            "  sni: apple.com\n"
            "  protocol: udp\n"
        )
        url = parse_clash_yaml(yaml)[0]
        assert url.startswith("hysteria://")
        assert "auth=" in url
        assert "protocol=udp" in url


class TestTuicUrl:
    def test_basic(self):
        uuid = "36106e0f-4d9a-470b-a3fd-535f3b7a1e92"
        yaml = _yaml(
            f"- type: tuic\n"
            f"  name: tuic\n"
            f"  server: 5.178.101.117\n"
            f"  port: 30006\n"
            f"  uuid: {uuid}\n"
            f"  password: dongtaiwang.com\n"
            f"  congestion-controller: bbr\n"
            f"  sni: www.microsoft.com\n"
        )
        url = parse_clash_yaml(yaml)[0]
        assert url.startswith("tuic://")
        assert uuid in url
        assert "congestion_control=bbr" in url


class TestSocks5Url:
    def test_with_credentials(self):
        yaml = _yaml(
            "- type: socks5\n"
            "  name: socks\n"
            "  server: 1.2.3.4\n"
            "  port: 1080\n"
            "  username: user\n"
            "  password: pass\n"
        )
        url = parse_clash_yaml(yaml)[0]
        assert url.startswith("socks://")
        userinfo = url.split("socks://")[1].split("@")[0]
        decoded = base64.b64decode(userinfo + "==").decode()
        assert decoded == "user:pass"

    def test_without_credentials(self):
        yaml = _yaml(
            "- type: socks5\n"
            "  name: anon\n"
            "  server: 1.2.3.4\n"
            "  port: 1080\n"
        )
        url = parse_clash_yaml(yaml)[0]
        assert "1.2.3.4:1080" in url


class TestUnsupportedTypesSkipped:
    def test_mieru_skipped(self):
        yaml = _yaml(
            "- type: mieru\n"
            "  name: m\n"
            "  server: s.com\n"
            "  port: 1234\n"
            "  password: pw\n"
        )
        assert parse_clash_yaml(yaml) == []

    def test_anytls_skipped(self):
        yaml = _yaml(
            "- type: anytls\n"
            "  name: a\n"
            "  server: s.com\n"
            "  port: 1234\n"
        )
        assert parse_clash_yaml(yaml) == []


class TestParseConfigsFromContentIntegration:
    def test_clash_yaml_parsed_via_main_entry(self):
        yaml = (
            "proxies:\n"
            "- type: ss\n"
            "  name: test\n"
            "  server: 1.2.3.4\n"
            "  port: 443\n"
            "  cipher: aes-128-gcm\n"
            "  password: pw\n"
        )
        result = parse_configs_from_content(yaml)
        assert len(result) == 1
        assert result[0].startswith("ss://")

    def test_plain_vpn_lines_still_work(self):
        content = "vless://uuid@host:443?type=tcp&security=tls#name"
        result = parse_configs_from_content(content)
        assert len(result) == 1
        assert result[0].startswith("vless://")
