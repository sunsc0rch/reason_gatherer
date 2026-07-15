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


def _inject_table_off(conf_text: str) -> str:
    """Add Table = off to [Interface] so awg-quick doesn't change host routes."""
    if re.search(r"^\s*Table\s*=", conf_text, re.MULTILINE | re.IGNORECASE):
        return conf_text
    return re.sub(r"(\[Interface\])", r"\1\nTable = off", conf_text, count=1)


def _handshake_age(iface: str) -> int | None:
    """Return seconds since last AWG handshake, or None if no handshake yet."""
    r = _run_sudo(["awg", "show", iface, "latest-handshakes"], timeout=5)
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            try:
                ts = int(parts[1])
                if ts == 0:
                    return None
                import time
                return int(time.time()) - ts
            except ValueError:
                pass
    return None


def test_awg_tunnel(conf_text: str) -> float | None:
    """Test AWG config in the main network namespace with Table=off (no route changes).

    amneziawg-go needs internet access to reach the AWG endpoint; running inside
    an isolated netns breaks UDP transport. Table=off prevents host-route pollution
    while we measure speed on the interface.
    """
    uid = uuid.uuid4().hex[:10]
    iface = f"awg{uid[:11]}"
    tmp_conf = Path(tempfile.gettempdir()) / f"{iface}.conf"

    clean_conf = strip_dns(conf_text)
    clean_conf = _inject_table_off(clean_conf)
    tmp_conf.write_text(clean_conf)
    # awg-quick needs the file to be root-readable but not world-accessible
    try:
        tmp_conf.chmod(0o600)
    except Exception:
        pass

    iface_up = False
    try:
        r = _run_sudo(["awg-quick", "up", str(tmp_conf)], timeout=20)
        if r.returncode != 0:
            logger.debug(f"awg-quick up failed for {iface}: {r.stderr[:300]}")
            return None
        iface_up = True

        # Wait for WireGuard handshake (up to 10 s in 1 s steps)
        import time
        for _ in range(10):
            age = _handshake_age(iface)
            if age is not None and age < 30:
                break
            time.sleep(1)
        else:
            logger.debug(f"No handshake on {iface}")
            return None

        # Measure download speed: curl bound to the AWG interface
        for url in SPEEDTEST_URLS:
            try:
                r = _run_sudo(
                    ["curl", "--max-time", "15", "--interface", iface,
                     "-o", "/dev/null", "-w", "%{speed_download}", "-s", "--", url],
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
        logger.debug(f"Timeout testing AWG config (iface={iface})")
        return None

    finally:
        if iface_up:
            _run_sudo(["awg-quick", "down", str(tmp_conf)], timeout=10)
        tmp_conf.unlink(missing_ok=True)


test_awg_tunnel.__test__ = False  # prevent pytest from collecting this as a test
