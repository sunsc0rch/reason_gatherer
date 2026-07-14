import os
import re
import socket
import subprocess
import tempfile
import uuid
from pathlib import Path

from awg_collector.config import (
    AWG_TEST_TIMEOUT, MIN_SPEED_MBPS, SPEEDTEST_URLS, PROXY_ENV_VARS, TCP_TIMEOUT,
)

import logging
logger = logging.getLogger(__name__)


def _clean_env() -> dict:
    env = os.environ.copy()
    for var in PROXY_ENV_VARS:
        env.pop(var, None)
    return env


def _run_sudo(args: list, timeout: int = AWG_TEST_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sudo", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_clean_env(),
    )


def tcp_check(host: str, port: int, timeout: float = TCP_TIMEOUT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False


def strip_dns(conf_text: str) -> str:
    return re.sub(r"^DNS\s*=.*\n?", "", conf_text, flags=re.MULTILINE)


def passes_speed(speed_bytes: float) -> bool:
    return speed_bytes >= MIN_SPEED_MBPS * 125_000


def test_awg_tunnel(conf_text: str) -> float | None:
    uid = uuid.uuid4().hex[:10]
    ns_name = f"awg_{uid}"
    # Interface name derived from conf filename by awg-quick (max 15 chars)
    iface = f"awg{uid[:11]}"
    tmp_conf = Path(tempfile.gettempdir()) / f"{iface}.conf"

    # Strip DNS to avoid resolvconf issues inside netns; DNS handled via /etc/netns
    clean_conf = strip_dns(conf_text)
    tmp_conf.write_text(clean_conf)

    ns_created = False
    iface_up = False
    try:
        # Create network namespace
        r = _run_sudo(["ip", "netns", "add", ns_name], timeout=10)
        if r.returncode != 0:
            logger.debug(f"netns add failed: {r.stderr}")
            return None
        ns_created = True

        # Set up per-netns DNS so curl can resolve inside the namespace
        ns_resolv = Path(f"/etc/netns/{ns_name}")
        _run_sudo(["mkdir", "-p", str(ns_resolv)], timeout=5)
        _run_sudo(["bash", "-c", f"echo 'nameserver 1.1.1.1' > /etc/netns/{ns_name}/resolv.conf"], timeout=5)

        # Bring up loopback inside netns
        _run_sudo(["ip", "netns", "exec", ns_name, "ip", "link", "set", "lo", "up"], timeout=5)

        # Bring up AWG interface inside netns
        r = _run_sudo(["ip", "netns", "exec", ns_name, "awg-quick", "up", str(tmp_conf)], timeout=15)
        if r.returncode != 0:
            logger.debug(f"awg-quick up failed: {r.stderr}")
            return None
        iface_up = True

        # Speedtest inside netns
        for url in SPEEDTEST_URLS:
            try:
                r = _run_sudo(
                    ["ip", "netns", "exec", ns_name,
                     "curl", "--max-time", "15", "-o", "/dev/null",
                     "-w", "%{speed_download}", "-s", "--", url],
                    timeout=20,
                )
                if r.returncode == 0 and r.stdout.strip():
                    speed = float(r.stdout.strip())
                    if speed > 0:
                        return speed
            except (subprocess.TimeoutExpired, ValueError):
                continue

        return None

    except subprocess.TimeoutExpired:
        logger.debug(f"Timeout testing AWG config (ns={ns_name})")
        return None

    finally:
        if iface_up:
            _run_sudo(["ip", "netns", "exec", ns_name, "awg-quick", "down", str(tmp_conf)], timeout=10)
        if ns_created:
            _run_sudo(["ip", "netns", "del", ns_name], timeout=5)
            _run_sudo(["rm", "-rf", f"/etc/netns/{ns_name}"], timeout=5)
        tmp_conf.unlink(missing_ok=True)


test_awg_tunnel.__test__ = False  # prevent pytest from collecting this as a test
