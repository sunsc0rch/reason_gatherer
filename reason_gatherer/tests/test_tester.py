import asyncio
import base64
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from vpn_collector.tester import tcp_check, tcp_filter, find_singbox, generate_singbox_config

VLESS1 = "vless://uuid1@1.2.3.4:443?type=tcp#Server1"
TROJAN = "trojan://password@9.10.11.12:443?sni=example.com#TrojanServer"

VLESS_TLS = "vless://some-uuid@host.com:443?type=tcp&security=tls&sni=host.com#Server"
VMESS_PAYLOAD = '{"v":"2","ps":"test","add":"vmess.host","port":"443","id":"myuuid","aid":"0","net":"tcp","type":"none","host":"","path":"","tls":"tls"}'
VMESS_LINE = "vmess://" + base64.b64encode(VMESS_PAYLOAD.encode()).decode()
TROJAN_LINE = "trojan://mypassword@trojan.host:443?sni=trojan.host#TrojanServer"
SS_LINE = "ss://YWVzLTI1Ni1nY206cGFzcw==@ss.host:8388#SSServer"
HY2_LINE = "hy2://mypassword@hy2.host:443?sni=hy2.host#Hy2Server"
TUIC_LINE = "tuic://myuuid:mypass@tuic.host:443?sni=tuic.host&congestion_control=bbr#TuicServer"


class TestTcpCheck:
    @pytest.mark.asyncio
    async def test_returns_true_on_open_port(self):
        async def fake_open(*args, **kwargs):
            writer = MagicMock()
            writer.close = MagicMock()
            writer.wait_closed = AsyncMock()
            return AsyncMock(), writer
        with patch("asyncio.open_connection", fake_open):
            assert await tcp_check("1.2.3.4", 443, timeout=5.0) is True

    @pytest.mark.asyncio
    async def test_returns_false_on_connection_error(self):
        async def fail_open(*args, **kwargs):
            raise ConnectionRefusedError()
        with patch("asyncio.open_connection", fail_open):
            assert await tcp_check("1.2.3.4", 9999, timeout=1.0) is False

    @pytest.mark.asyncio
    async def test_returns_false_on_timeout(self):
        async def slow_open(*args, **kwargs):
            await asyncio.sleep(10)
        with patch("asyncio.open_connection", slow_open):
            assert await tcp_check("1.2.3.4", 443, timeout=0.01) is False


class TestTcpFilter:
    @pytest.mark.asyncio
    async def test_keeps_reachable_configs(self):
        async def fake_open(*args, **kwargs):
            writer = MagicMock()
            writer.close = MagicMock()
            writer.wait_closed = AsyncMock()
            return AsyncMock(), writer
        with patch("asyncio.open_connection", fake_open):
            result = await tcp_filter([VLESS1, TROJAN], concurrency=2, timeout=1.0)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_removes_unreachable_configs(self):
        async def always_fail(*args, **kwargs):
            raise ConnectionRefusedError()
        with patch("asyncio.open_connection", always_fail):
            result = await tcp_filter([VLESS1, TROJAN], concurrency=2, timeout=1.0)
        assert result == []

    @pytest.mark.asyncio
    async def test_skips_unparseable_configs(self):
        async def fake_open(*args, **kwargs):
            writer = MagicMock()
            writer.close = MagicMock()
            writer.wait_closed = AsyncMock()
            return AsyncMock(), writer
        with patch("asyncio.open_connection", fake_open):
            result = await tcp_filter([VLESS1, "not-a-config"], concurrency=2, timeout=1.0)
        assert result == [VLESS1]


class TestFindSingbox:
    def test_finds_binary(self, tmp_path):
        binary = tmp_path / "sing-box"
        binary.write_text("#!/bin/sh")
        binary.chmod(0o755)
        with patch("vpn_collector.tester.SINGBOX_SEARCH_PATHS", [str(tmp_path)]):
            assert find_singbox() == str(binary)

    def test_returns_none_if_not_found(self):
        with patch("vpn_collector.tester.SINGBOX_SEARCH_PATHS", ["/nonexistent/path"]):
            assert find_singbox() is None


class TestGenerateSingboxConfig:
    def test_vless_structure(self):
        cfg = generate_singbox_config(VLESS_TLS, socks_port=11000)
        assert cfg["log"]["level"] == "error"
        assert cfg["inbounds"][0]["listen_port"] == 11000
        out = cfg["outbounds"][0]
        assert out["type"] == "vless"
        assert out["server"] == "host.com"
        assert out["server_port"] == 443
        assert out["uuid"] == "some-uuid"

    def test_vmess_structure(self):
        out = generate_singbox_config(VMESS_LINE, socks_port=11001)["outbounds"][0]
        assert out["type"] == "vmess"
        assert out["server"] == "vmess.host"
        assert out["server_port"] == 443
        assert out["uuid"] == "myuuid"

    def test_trojan_structure(self):
        out = generate_singbox_config(TROJAN_LINE, socks_port=11002)["outbounds"][0]
        assert out["type"] == "trojan"
        assert out["server"] == "trojan.host"
        assert out["password"] == "mypassword"

    def test_ss_structure(self):
        out = generate_singbox_config(SS_LINE, socks_port=11003)["outbounds"][0]
        assert out["type"] == "shadowsocks"
        assert out["server"] == "ss.host"
        assert out["server_port"] == 8388
        assert out["method"] == "aes-256-gcm"
        assert out["password"] == "pass"

    def test_hy2_structure(self):
        out = generate_singbox_config(HY2_LINE, socks_port=11004)["outbounds"][0]
        assert out["type"] == "hysteria2"
        assert out["server"] == "hy2.host"
        assert out["password"] == "mypassword"

    def test_hysteria_structure(self):
        hysteria_line = "hysteria://mypassword@hysteria.host:443?sni=hysteria.host#HysteriaServer"
        out = generate_singbox_config(hysteria_line, socks_port=11006)["outbounds"][0]
        assert out["type"] == "hysteria2"
        assert out["server"] == "hysteria.host"
        assert out["password"] == "mypassword"

    def test_tuic_structure(self):
        out = generate_singbox_config(TUIC_LINE, socks_port=11005)["outbounds"][0]
        assert out["type"] == "tuic"
        assert out["uuid"] == "myuuid"
        assert out["password"] == "mypass"
        assert out["congestion_control"] == "bbr"

    def test_socks_structure(self):
        # socks://Og@1.2.3.4:443#name  — Og = base64(":") = empty user + empty pass
        out = generate_singbox_config("socks://Og@1.2.3.4:443#name", socks_port=11010)["outbounds"][0]
        assert out["type"] == "socks"
        assert out["server"] == "1.2.3.4"
        assert out["server_port"] == 443
        assert out["username"] == ""
        assert out["password"] == ""
        assert out["version"] == "5"

    def test_socks_with_credentials(self):
        # socks://dXNlcjpwYXNz@1.2.3.4:1080#name  — base64("user:pass")
        creds = base64.b64encode(b"user:pass").decode()
        out = generate_singbox_config(f"socks://{creds}@1.2.3.4:1080#name", socks_port=11011)["outbounds"][0]
        assert out["type"] == "socks"
        assert out["username"] == "user"
        assert out["password"] == "pass"


from vpn_collector.tester import (
    speedtest_via_socks, check_claude_via_socks,
    test_config_tunnel as _test_config_tunnel, tunnel_filter,
)
test_config_tunnel = _test_config_tunnel
test_config_tunnel.__test__ = False

VLESS_TEST = "vless://some-uuid@host.com:443?type=tcp&security=tls&sni=host.com#TestServer"


class TestSpeedtestViaSocks:
    def test_returns_speed_in_mbps(self):
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"x" * (1024 * 1024)]
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("vpn_collector.tester.requests.Session") as MockSession, \
             patch("vpn_collector.tester.time.time", side_effect=[0.0, 0.1, 1.0]):
            mock_session = MagicMock()
            mock_session.get.return_value = mock_resp
            MockSession.return_value.__enter__ = lambda s: mock_session
            MockSession.return_value.__exit__ = MagicMock(return_value=False)
            assert speedtest_via_socks(12000) > 0

    def test_returns_zero_on_error(self):
        with patch("vpn_collector.tester.requests.Session") as MockSession:
            mock_session = MagicMock()
            mock_session.get.side_effect = Exception("fail")
            MockSession.return_value.__enter__ = lambda s: mock_session
            MockSession.return_value.__exit__ = MagicMock(return_value=False)
            assert speedtest_via_socks(12001) == 0.0


class TestCheckClaudeViaSocks:
    def _mock_session(self, mock_get_cls, resp):
        mock_session = MagicMock()
        mock_session.get.return_value = resp
        mock_get_cls.return_value.__enter__ = lambda s: mock_session
        mock_get_cls.return_value.__exit__ = MagicMock(return_value=False)

    def test_plus_on_200_clean_url(self):
        resp = MagicMock(status_code=200, url="https://claude.com/", text="<html></html>")
        with patch("vpn_collector.tester.requests.Session") as M:
            self._mock_session(M, resp)
            assert check_claude_via_socks(12002) == "+++"

    def test_minus_on_4xx_status(self):
        resp = MagicMock(status_code=403, url="https://claude.com/", text="")
        with patch("vpn_collector.tester.requests.Session") as M:
            self._mock_session(M, resp)
            assert check_claude_via_socks(12003) == "---"

    def test_minus_on_status_451(self):
        resp = MagicMock(status_code=451, url="https://claude.com/", text="")
        with patch("vpn_collector.tester.requests.Session") as M:
            self._mock_session(M, resp)
            assert check_claude_via_socks(12004) == "---"

    def test_minus_on_blocked_url_keyword(self):
        resp = MagicMock(status_code=200, url="https://claude.com/blocked",
                         text='<html data-theme="claude"></html>')
        with patch("vpn_collector.tester.requests.Session") as M:
            self._mock_session(M, resp)
            assert check_claude_via_socks(12005) == "---"

    def test_minus_on_exception(self):
        with patch("vpn_collector.tester.requests.Session") as M:
            mock_session = MagicMock()
            mock_session.get.side_effect = Exception("timeout")
            M.return_value.__enter__ = lambda s: mock_session
            M.return_value.__exit__ = MagicMock(return_value=False)
            assert check_claude_via_socks(12006) == "---"


class TestTestConfigTunnel:
    def test_returns_marked_config_on_success(self):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.terminate = MagicMock()
        mock_proc.wait = MagicMock()
        mock_tmp = MagicMock()
        mock_tmp.__enter__ = lambda s: MagicMock(name="/tmp/fake.json")
        mock_tmp.__exit__ = MagicMock(return_value=False)
        mock_tmp.return_value.name = "/tmp/fake.json"
        with patch("vpn_collector.tester.generate_singbox_config", return_value={}), \
             patch("vpn_collector.tester.subprocess.Popen") as mock_popen, \
             patch("vpn_collector.tester.speedtest_via_socks", return_value=5.0), \
             patch("vpn_collector.tester.check_claude_via_socks", return_value="+++"), \
             patch("vpn_collector.tester._wait_for_socks_port", return_value=True), \
             patch("vpn_collector.tester.json.dump"), \
             patch("vpn_collector.tester.tempfile.NamedTemporaryFile") as mock_ntf, \
             patch("vpn_collector.tester.os.unlink"):
            mock_popen.return_value = mock_proc
            mock_cm = MagicMock()
            mock_cm.__enter__ = MagicMock(return_value=MagicMock(name="/tmp/fake.json"))
            mock_cm.__exit__ = MagicMock(return_value=False)
            mock_cm.__enter__.return_value.name = "/tmp/fake.json"
            mock_ntf.return_value = mock_cm
            result = test_config_tunnel(VLESS_TEST, "/usr/bin/sing-box", socks_port=13000)
        assert result is not None
        assert "#+++TestServer" in result

    def test_returns_none_below_speed_threshold(self):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        with patch("vpn_collector.tester.generate_singbox_config", return_value={}), \
             patch("vpn_collector.tester.subprocess.Popen") as mock_popen, \
             patch("vpn_collector.tester.speedtest_via_socks", return_value=0.3), \
             patch("vpn_collector.tester._wait_for_socks_port", return_value=True), \
             patch("vpn_collector.tester.json.dump"), \
             patch("vpn_collector.tester.tempfile.NamedTemporaryFile") as mock_ntf, \
             patch("vpn_collector.tester.os.unlink"):
            mock_popen.return_value = mock_proc
            mock_cm = MagicMock()
            mock_cm.__enter__ = MagicMock(return_value=MagicMock(name="/tmp/fake.json"))
            mock_cm.__exit__ = MagicMock(return_value=False)
            mock_cm.__enter__.return_value.name = "/tmp/fake.json"
            mock_ntf.return_value = mock_cm
            result = test_config_tunnel(VLESS_TEST, "/usr/bin/sing-box", socks_port=13001)
        assert result is None


class TestTunnelFilter:
    @pytest.mark.asyncio
    async def test_returns_passing_configs(self):
        with patch("vpn_collector.tester.test_config_tunnel", return_value="vless://uuid@host:443#+++Server"):
            result = await tunnel_filter(["vless://uuid@host:443#Server"], "/usr/bin/sing-box", concurrency=1)
        assert result == ["vless://uuid@host:443#+++Server"]

    @pytest.mark.asyncio
    async def test_filters_out_none_results(self):
        with patch("vpn_collector.tester.test_config_tunnel", return_value=None):
            result = await tunnel_filter(["vless://uuid@host:443#Server"], "/usr/bin/sing-box", concurrency=1)
        assert result == []
