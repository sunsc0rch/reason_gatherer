# tests/test_awg_tester.py
import subprocess
import pytest
from unittest.mock import patch, MagicMock

from awg_collector.tester import tcp_check, test_awg_tunnel, passes_speed, strip_dns

SAMPLE_CONF = """[Interface]
PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
Address = 10.8.0.2/32
DNS = 1.1.1.1
Jc = 4

[Peer]
PublicKey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=
AllowedIPs = 0.0.0.0/0
Endpoint = 185.123.45.67:51820"""


class TestPassesSpeed:
    def test_above_threshold_passes(self):
        assert passes_speed(200_000) is True  # 1.6 Mbps

    def test_below_threshold_fails(self):
        assert passes_speed(50_000) is False  # 0.4 Mbps

    def test_exactly_threshold_passes(self):
        assert passes_speed(125_000) is True  # exactly 1.0 Mbps


class TestStripDns:
    def test_removes_dns_line(self):
        result = strip_dns("DNS = 1.1.1.1\nAddress = 10.0.0.1/32\n")
        assert "DNS" not in result

    def test_no_dns_unchanged(self):
        text = "Address = 10.0.0.1/32\n"
        assert strip_dns(text) == text


class TestTcpCheck:
    def test_open_port_returns_true(self):
        import socket, threading
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        t = threading.Thread(target=lambda: server.accept())
        t.daemon = True
        t.start()
        assert tcp_check("127.0.0.1", port, timeout=2.0) is True
        server.close()

    def test_closed_port_returns_false(self):
        assert tcp_check("127.0.0.1", 1, timeout=1.0) is False


class TestAwgTunnel:
    def _make_run(self, returncode=0, stdout="1500000.0"):
        """Helper: mock subprocess.run to return success."""
        result = MagicMock()
        result.returncode = returncode
        result.stdout = stdout
        return result

    def test_returns_speed_on_success(self):
        with patch("awg_collector.tester._run_sudo") as mock_run:
            mock_run.return_value = self._make_run(0, "1500000.0")
            speed = test_awg_tunnel(SAMPLE_CONF)
        assert speed == 1_500_000.0

    def test_returns_none_when_awg_quick_fails(self):
        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if "awg-quick" in cmd:
                r = MagicMock()
                r.returncode = 1
                r.stdout = ""
                return r
            r = MagicMock()
            r.returncode = 0
            r.stdout = ""
            return r

        with patch("awg_collector.tester._run_sudo", side_effect=side_effect):
            speed = test_awg_tunnel(SAMPLE_CONF)
        assert speed is None

    def test_returns_none_on_timeout(self):
        with patch("awg_collector.tester._run_sudo", side_effect=subprocess.TimeoutExpired("cmd", 30)):
            speed = test_awg_tunnel(SAMPLE_CONF)
        assert speed is None

    def test_cleanup_called_on_failure(self):
        calls = []

        def side_effect(*args, **kwargs):
            calls.append(list(args[0]) if args else [])
            r = MagicMock()
            r.returncode = 1 if "up" in (args[0] if args else []) else 0
            r.stdout = ""
            return r

        with patch("awg_collector.tester._run_sudo", side_effect=side_effect):
            test_awg_tunnel(SAMPLE_CONF)

        # Verify ip netns del was called (cleanup)
        cleanup_calls = [c for c in calls if "netns" in c and "del" in c]
        assert len(cleanup_calls) >= 1

    def test_dns_stripped_from_conf(self):
        seen_confs = []

        def side_effect(*args, **kwargs):
            cmd = list(args[0]) if args else []
            # Capture the conf file path when awg-quick up is called
            if "up" in cmd:
                conf_path = cmd[-1]
                try:
                    import pathlib
                    seen_confs.append(pathlib.Path(conf_path).read_text())
                except Exception:
                    pass
            r = MagicMock()
            r.returncode = 0
            r.stdout = "1500000.0"
            return r

        with patch("awg_collector.tester._run_sudo", side_effect=side_effect):
            test_awg_tunnel(SAMPLE_CONF)

        assert seen_confs, "conf file was not read — awg-quick up was never called or path extraction failed"
        assert "DNS" not in seen_confs[0]
