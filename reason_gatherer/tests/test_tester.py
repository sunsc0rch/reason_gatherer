import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from vpn_collector.tester import tcp_check, tcp_filter

VLESS1 = "vless://uuid1@1.2.3.4:443?type=tcp#Server1"
TROJAN = "trojan://password@9.10.11.12:443?sni=example.com#TrojanServer"


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


import base64
from pathlib import Path
from vpn_collector.tester import find_singbox, generate_singbox_config

VLESS_TLS = "vless://some-uuid@host.com:443?type=tcp&security=tls&sni=host.com#Server"
VMESS_PAYLOAD = '{"v":"2","ps":"test","add":"vmess.host","port":"443","id":"myuuid","aid":"0","net":"tcp","type":"none","host":"","path":"","tls":"tls"}'
VMESS_LINE = "vmess://" + base64.b64encode(VMESS_PAYLOAD.encode()).decode()
TROJAN_LINE = "trojan://mypassword@trojan.host:443?sni=trojan.host#TrojanServer"
SS_LINE = "ss://YWVzLTI1Ni1nY206cGFzcw==@ss.host:8388#SSServer"
HY2_LINE = "hy2://mypassword@hy2.host:443?sni=hy2.host#Hy2Server"
TUIC_LINE = "tuic://myuuid:mypass@tuic.host:443?sni=tuic.host&congestion_control=bbr#TuicServer"


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

    def test_hy2_structure(self):
        out = generate_singbox_config(HY2_LINE, socks_port=11004)["outbounds"][0]
        assert out["type"] == "hysteria2"
        assert out["server"] == "hy2.host"
        assert out["password"] == "mypassword"

    def test_tuic_structure(self):
        out = generate_singbox_config(TUIC_LINE, socks_port=11005)["outbounds"][0]
        assert out["type"] == "tuic"
        assert out["uuid"] == "myuuid"
        assert out["password"] == "mypass"
        assert out["congestion_control"] == "bbr"
