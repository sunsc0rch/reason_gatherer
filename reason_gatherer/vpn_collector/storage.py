from datetime import date, datetime
from pathlib import Path

from vpn_collector.parser import extract_host_port, is_vpn_line

_NON_CONFIG_FILES = {"candidates.txt", "tcp_cache.txt"}


def load_known_hosts(results_dir: Path) -> set[str]:
    hosts: set[str] = set()
    for f in results_dir.glob("*.txt"):
        if f.name in _NON_CONFIG_FILES:
            continue
        for line in f.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if is_vpn_line(line):
                hp = extract_host_port(line)
                if hp:
                    hosts.add(f"{hp[0]}:{hp[1]}")
    return hosts


def load_known_good_hp(results_dir: Path) -> set[tuple]:
    """Return (host, port) pairs from known_good.txt."""
    known_good = results_dir / "known_good.txt"
    if not known_good.exists():
        return set()
    result: set[tuple] = set()
    for line in known_good.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if is_vpn_line(line):
            hp = extract_host_port(line)
            if hp:
                result.add(hp)
    return result


def load_tcp_cache(results_dir: Path) -> set[tuple]:
    """Return (host, port) pairs that previously passed TCP check."""
    cache_file = results_dir / "tcp_cache.txt"
    if not cache_file.exists():
        return set()
    result: set[tuple] = set()
    for line in cache_file.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        host, _, port_str = line.rpartition(":")
        try:
            result.add((host, int(port_str)))
        except ValueError:
            pass
    return result


def update_tcp_cache(results_dir: Path, new_hosts: list[tuple]) -> None:
    """Append newly TCP-verified (host, port) pairs to tcp_cache.txt."""
    if not new_hosts:
        return
    with open(results_dir / "tcp_cache.txt", "a") as f:
        for host, port in new_hosts:
            f.write(f"{host}:{port}\n")


def trim_candidates(candidates_file: Path, known_good_hp: set[tuple]) -> int:
    """Remove configs already in known_good from candidates.txt. Returns removed count."""
    if not candidates_file.exists():
        return 0
    lines = candidates_file.read_text().splitlines()
    remaining = []
    removed = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        hp = extract_host_port(stripped)
        if hp and hp in known_good_hp:
            removed += 1
        else:
            remaining.append(stripped)
    with open(candidates_file, "w") as f:
        if remaining:
            f.write("\n".join(remaining) + "\n")
    return removed


def is_duplicate(config: str, known_hosts: set[str]) -> bool:
    hp = extract_host_port(config)
    if not hp:
        return False
    return f"{hp[0]}:{hp[1]}" in known_hosts


def save_config(
    config: str,
    results_dir: Path,
    known_hosts: set[str],
    run_date: str | None = None,
) -> None:
    if run_date is None:
        run_date = date.today().isoformat()
    hp = extract_host_port(config)
    if hp:
        known_hosts.add(f"{hp[0]}:{hp[1]}")
    with open(results_dir / f"run_{run_date}.txt", "a") as f:
        f.write(config + "\n")
    with open(results_dir / "known_good.txt", "a") as f:
        f.write(config + "\n")
    update_known_good_header(results_dir)


def rotate_run_files(results_dir: Path, max_files: int) -> None:
    run_files = sorted(results_dir.glob("run_*.txt"))
    while len(run_files) > max_files:
        run_files[0].unlink()
        run_files = run_files[1:]


def update_known_good_header(results_dir: Path) -> None:
    known_good = results_dir / "known_good.txt"
    if not known_good.exists():
        return
    lines = known_good.read_text().splitlines()
    config_lines = [l for l in lines if l.strip() and not l.startswith("#")]
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = f"# Updated: {timestamp} | Total: {len(config_lines)}"
    with open(known_good, "w") as f:
        f.write(header + "\n")
        for line in config_lines:
            f.write(line + "\n")


def get_stats(results_dir: Path) -> dict[str, int]:
    stats: dict[str, int] = {}
    for f in sorted(results_dir.glob("*.txt")):
        lines = [
            l for l in f.read_text().splitlines()
            if l.strip() and not l.startswith("#")
        ]
        stats[f.stem] = len(lines)
    return stats
