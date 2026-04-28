from datetime import date, datetime
from pathlib import Path

from vpn_collector.parser import extract_host_port, is_vpn_line


def load_known_hosts(results_dir: Path) -> set[str]:
    hosts: set[str] = set()
    for f in results_dir.glob("*.txt"):
        if f.name == "candidates.txt":
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
