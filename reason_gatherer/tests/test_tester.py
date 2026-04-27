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
