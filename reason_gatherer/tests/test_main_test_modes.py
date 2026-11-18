import json
import sys
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import vpn_collector.main as main_module
from vpn_collector.main import cmd_test
from vpn_collector.storage import load_known_hosts


VLESS = "vless://uuid@1.2.3.4:443?type=tcp#Server"


def _warp_cli_results(mode: str):
    return [
        SimpleNamespace(stdout=f"Mode: {mode}\n", stderr=""),
        SimpleNamespace(stdout="Status update: Connected\n", stderr=""),
    ]


def test_cmd_test_refuses_connected_system_warp_tunnel(tmp_path):
    candidates = tmp_path / "candidates.txt"
    candidates.write_text(f"{VLESS}\n")

    with (
        patch("vpn_collector.main.RESULTS_DIR", tmp_path),
        patch("vpn_collector.main._warp_tunnel_active", return_value=True),
        patch("vpn_collector.main.find_singbox") as find_singbox,
        patch("vpn_collector.main.tunnel_filter", new_callable=AsyncMock) as tunnel_filter,
    ):
        with pytest.raises(SystemExit, match="system-tunnel"):
            cmd_test()

    find_singbox.assert_not_called()
    tunnel_filter.assert_not_awaited()


def test_cmd_test_allows_warp_proxy_mode(tmp_path):
    candidates = tmp_path / "candidates.txt"
    candidates.write_text(f"{VLESS}\n")

    with (
        patch("vpn_collector.main.RESULTS_DIR", tmp_path),
        patch("vpn_collector.main.subprocess.run", side_effect=_warp_cli_results("WarpProxy on port 40000")),
        patch("vpn_collector.main.find_singbox", return_value="/fake/sing-box"),
        patch("vpn_collector.main.tunnel_filter", new_callable=AsyncMock, return_value=[]) as tunnel_filter,
        patch("vpn_collector.main.rotate_run_files"),
    ):
        cmd_test()

    tunnel_filter.assert_awaited_once()


def test_main_dispatches_test_warp_and_rejects_combined_mode(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["vpn-collector", "--test-warp"])
    with patch("vpn_collector.main._setup_logging"), \
         patch("vpn_collector.main.cmd_test_warp", create=True) as cmd_test_warp:
        main_module.main()
    cmd_test_warp.assert_called_once()

    monkeypatch.setattr(sys, "argv", ["vpn-collector", "--test", "--test-warp"])
    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_cmd_test_warp_preflight_failure_writes_no_results(tmp_path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "candidates.txt").write_text(f"{VLESS}\n")

    with (
        patch("vpn_collector.main.RESULTS_DIR", results_dir),
        patch("vpn_collector.main.find_singbox", return_value="/fake/sing-box"),
        patch("vpn_collector.main.socks5_connect", new_callable=AsyncMock, return_value=False),
        patch("vpn_collector.main.tunnel_filter", new_callable=AsyncMock) as tunnel_filter,
    ):
        with pytest.raises(SystemExit, match="WARP SOCKS"):
            main_module.cmd_test_warp()

    assert not (results_dir / "warp").exists()
    tunnel_filter.assert_not_awaited()


def test_cmd_test_warp_saves_only_under_warp_results(tmp_path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    candidates_file = results_dir / "candidates.txt"
    candidates_file.write_text(f"{VLESS}\n")
    direct_known_good = results_dir / "known_good.txt"
    direct_known_good.write_text("# direct pool\nvless://uuid@9.8.7.6:443#Direct\n")
    direct_run = results_dir / "run_2026-11-17.txt"
    direct_run.write_text("direct run remains unchanged\n")
    direct_meta = results_dir / "config_meta.json"
    direct_meta.write_text('{"direct": {"first_seen": "2026-11-17"}}')
    before = {
        path.name: path.read_bytes()
        for path in (candidates_file, direct_known_good, direct_run, direct_meta)
    }
    proxy = ("127.0.0.1", 40000)
    passed = f"{VLESS.split('#', 1)[0]}#+++Server"

    async def fake_tunnel_filter(configs, singbox_path, on_pass=None, dialer_proxy=None):
        assert configs == [VLESS]
        assert dialer_proxy == proxy
        if on_pass:
            on_pass(passed)
        return [passed]

    with (
        patch("vpn_collector.main.RESULTS_DIR", results_dir),
        patch("vpn_collector.main.find_singbox", return_value="/fake/sing-box"),
        patch("vpn_collector.main.socks5_connect", new_callable=AsyncMock, return_value=True),
        patch("vpn_collector.main.tunnel_filter", side_effect=fake_tunnel_filter) as tunnel_filter,
    ):
        main_module.cmd_test_warp(proxy=proxy)

    warp_dir = results_dir / "warp"
    assert passed in (warp_dir / "known_good.txt").read_text()
    assert passed in (warp_dir / f"run_{date.today().isoformat()}.txt").read_text()
    assert {path.name: path.read_bytes() for path in (candidates_file, direct_known_good, direct_run, direct_meta)} == before
    assert "1.2.3.4:443" not in load_known_hosts(results_dir)
    tunnel_filter.assert_awaited_once()


def test_cmd_test_warp_deduplicates_only_within_warp_pool(tmp_path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "candidates.txt").write_text(f"{VLESS}\n")
    warp_dir = results_dir / "warp"
    warp_dir.mkdir()
    (warp_dir / "known_good.txt").write_text(f"{VLESS}\n")

    with (
        patch("vpn_collector.main.RESULTS_DIR", results_dir),
        patch("vpn_collector.main.find_singbox", return_value="/fake/sing-box"),
        patch("vpn_collector.main.socks5_connect", new_callable=AsyncMock, return_value=True),
        patch("vpn_collector.main.tunnel_filter", new_callable=AsyncMock, return_value=[]) as tunnel_filter,
        patch("vpn_collector.main.rotate_run_files"),
    ):
        main_module.cmd_test_warp()

    assert tunnel_filter.await_args.args[0] == []
    assert "1.2.3.4:443" not in load_known_hosts(results_dir)
