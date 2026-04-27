# VPN Config Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a modular Python CLI that scrapes VPN configs from GitHub repos and raw URLs, tests them via TCP pre-filter then sing-box tunnel, filters by speed (≥1 Mbit/s) and Claude.com reachability, and saves verified configs to rotating result files with deduplication.

**Architecture:** Six single-responsibility modules (config, parser, storage, sources, tester, main) in a flat package. Stage 1 (`--collect`) does fast async TCP pre-filter producing `candidates.txt`. Stage 2 (`--test`) runs sing-box subprocesses for speedtest and Claude.com check. All connections bypass system proxy. `sources.json` persists the source list and grows via `--add-source` / `--sync-stars`.

**Tech Stack:** Python 3.10+, aiohttp, aiofiles, requests[socks], tqdm, pytest, pytest-asyncio, unittest.mock; external: sing-box binary (auto-discovered from Throne installation)

---

## File Map

| File | Responsibility |
|------|---------------|
| `vpn_collector/config.py` | All constants and tunable parameters |
| `vpn_collector/parser.py` | Config line parsing, host:port extraction, VPN file detection |
| `vpn_collector/storage.py` | Deduplication, FIFO file rotation, known_good.txt writes |
| `vpn_collector/sources.py` | GitHub Trees API, sources.json management, stars sync |
| `vpn_collector/tester.py` | TCP pre-filter, sing-box config gen, tunnel test, speedtest, Claude check |
| `vpn_collector/main.py` | argparse CLI wiring |
| `tests/test_parser.py` | Parser unit tests |
| `tests/test_storage.py` | Storage unit tests with temp dirs |
| `tests/test_sources.py` | Sources unit tests with mocked HTTP |
| `tests/test_tester.py` | Tester unit tests with mocked subprocess |
| `requirements.txt` | Python dependencies |
| `sources.json` | Persisted source list (auto-created on first run) |

---

### Task 1: Project scaffold and config.py

**Files:**
- Create: `vpn_collector/__init__.py`
- Create: `vpn_collector/config.py`
- Create: `requirements.txt`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p vpn_collector tests results logs
touch vpn_collector/__init__.py tests/__init__.py
```

- [ ] **Step 2: Create requirements.txt**

```
aiohttp==3.9.5
aiofiles==23.2.1
requests[socks]==2.31.0
tqdm==4.66.2
pytest==8.1.1
pytest-asyncio==0.23.6
```

- [ ] **Step 3: Create vpn_collector/config.py**

```python
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
RESULTS_DIR = BASE_DIR / "results"
LOGS_DIR = BASE_DIR / "logs"
SOURCES_FILE = BASE_DIR / "sources.json"

TCP_TIMEOUT = 5.0
TCP_CONCURRENCY = 50
TUNNEL_CONCURRENCY = 5
MIN_SPEED_MBPS = 1.0
MAX_RUN_FILES = 5
SOCKS_PORT_RANGE = (10000, 19999)
SINGBOX_STARTUP_TIMEOUT = 3.0

SPEEDTEST_URL = "http://speedtest.tele2.net/1MB.bin"
CLAUDE_CHECK_URL = "https://claude.com/"

CLAUDE_BLOCK_KEYWORDS = [
    "app unavailable in region",
    "not available in your region",
    "unavailable in your country",
    "access restricted",
]
CLAUDE_BLOCK_URL_KEYWORDS = ["unavailable", "blocked", "region", "restricted"]

SINGBOX_SEARCH_PATHS = [
    "/opt/throne",
    "/usr/local/bin",
    os.path.expanduser("~/.local/share/throne"),
    os.path.expanduser("~/throne"),
    os.path.expanduser("~/.local/bin"),
    "/usr/bin",
    "/opt/hiddify",
    os.path.expanduser("~/.local/share/hiddify"),
]

VPN_PREFIXES = (
    "vless://", "vmess://", "trojan://", "ss://",
    "hysteria://", "hysteria2://", "hy2://", "tuic://",
)

SKIP_FILENAMES = {
    "readme", "requirements", "license", "changelog",
    "vercel.json", ".gitignore", ".github",
}
SKIP_EXTENSIONS = {".yml", ".yaml", ".json", ".md", ".html", ".py", ".sh", ".toml"}

PROXY_ENV_VARS = [
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
]

DEFAULT_SOURCES = [
    {"type": "repo", "value": "VP01596/vless-top15"},
    {"type": "repo", "value": "qopq1366/VlessConfig"},
    {"type": "repo", "value": "Vovo4ka000/V4kVPN"},
    {"type": "repo", "value": "MustafaBaqer/VestraNet-Nodes"},
    {"type": "repo", "value": "Mr-Meshky/vify"},
    {"type": "repo", "value": "kasesm/Free-Config"},
    {"type": "repo", "value": "igareck/vpn-configs-for-russia"},
    {"type": "repo", "value": "LalatinaHub/Mineral"},
    {"type": "repo", "value": "luxxuria/harvester"},
    {"type": "repo", "value": "mahdibland/V2RayAggregator"},
    {"type": "repo", "value": "barry-far/V2RayAggregator"},
    {"type": "repo", "value": "freefq/free"},
    {"type": "repo", "value": "peasoft/NoMoreVPN"},
]
```

- [ ] **Step 4: Install dependencies**

```bash
pip install -r requirements.txt
```

Expected: all packages install without errors.

- [ ] **Step 5: Verify import**

```bash
python -c "from vpn_collector import config; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add vpn_collector/ tests/ requirements.txt
git commit -m "feat: project scaffold and config"
```

---

### Task 2: parser.py

**Files:**
- Create: `vpn_collector/parser.py`
- Create: `tests/test_parser.py`

- [ ] **Step 1: Write failing tests — create tests/test_parser.py**

```python
import base64
import pytest
from vpn_collector.parser import (
    is_vpn_line, extract_host_port, extract_name, set_name,
    parse_configs_from_content, is_vpn_file,
)

VLESS = "vless://some-uuid@1.2.3.4:443?type=tcp&security=tls#MyServer"
VMESS_PAYLOAD = '{"v":"2","ps":"vmess_server","add":"5.6.7.8","port":"8080","id":"uuid123","aid":"0","net":"tcp","type":"none","host":"","path":"","tls":""}'
VMESS = "vmess://" + base64.b64encode(VMESS_PAYLOAD.encode()).decode()
TROJAN = "trojan://password123@9.10.11.12:443?sni=example.com#TrojanServer"
SS = "ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ=@13.14.15.16:8388#SSServer"
HY2 = "hy2://mypassword@17.18.19.20:443?sni=test.com#HysteriaServer"
TUIC = "tuic://myuuid:mypass@21.22.23.24:443?sni=tuic.com#TuicServer"


class TestIsVpnLine:
    def test_vless(self):
        assert is_vpn_line(VLESS) is True

    def test_vmess(self):
        assert is_vpn_line(VMESS) is True

    def test_trojan(self):
        assert is_vpn_line(TROJAN) is True

    def test_ss(self):
        assert is_vpn_line(SS) is True

    def test_hy2(self):
        assert is_vpn_line(HY2) is True

    def test_tuic(self):
        assert is_vpn_line(TUIC) is True

    def test_plain_text(self):
        assert is_vpn_line("This is a readme line") is False

    def test_empty(self):
        assert is_vpn_line("") is False

    def test_comment(self):
        assert is_vpn_line("# comment") is False


class TestExtractHostPort:
    def test_vless(self):
        assert extract_host_port(VLESS) == ("1.2.3.4", 443)

    def test_trojan(self):
        assert extract_host_port(TROJAN) == ("9.10.11.12", 443)

    def test_ss(self):
        assert extract_host_port(SS) == ("13.14.15.16", 8388)

    def test_hy2(self):
        assert extract_host_port(HY2) == ("17.18.19.20", 443)

    def test_tuic(self):
        assert extract_host_port(TUIC) == ("21.22.23.24", 443)

    def test_vmess(self):
        assert extract_host_port(VMESS) == ("5.6.7.8", 8080)

    def test_invalid_returns_none(self):
        assert extract_host_port("not-a-config") is None


class TestExtractSetName:
    def test_extract_name(self):
        assert extract_name(VLESS) == "MyServer"

    def test_extract_name_no_fragment(self):
        assert extract_name("vless://uuid@host:443?type=tcp") == ""

    def test_set_name_replaces_existing(self):
        result = set_name(VLESS, "+++MyServer")
        assert result.endswith("#+++MyServer")
        assert result.startswith("vless://")

    def test_set_name_no_existing_name(self):
        config = "vless://uuid@host:443?type=tcp"
        result = set_name(config, "+++NewName")
        assert result.endswith("#+++NewName")


class TestParseConfigsFromContent:
    def test_plain_list(self):
        content = f"{VLESS}\n{TROJAN}\nsome random line\n{SS}"
        result = parse_configs_from_content(content)
        assert len(result) == 3
        assert VLESS in result

    def test_base64_encoded_list(self):
        raw = f"{VLESS}\n{TROJAN}\n{SS}"
        encoded = base64.b64encode(raw.encode()).decode()
        result = parse_configs_from_content(encoded)
        assert len(result) == 3

    def test_empty_content(self):
        assert parse_configs_from_content("") == []

    def test_deduplicates(self):
        content = f"{VLESS}\n{VLESS}\n{TROJAN}"
        result = parse_configs_from_content(content)
        assert len(result) == 2


class TestIsVpnFile:
    def test_detects_plain_vpn_file(self):
        content = f"{VLESS}\n{TROJAN}\n{SS}\n"
        assert is_vpn_file("sub.txt", content) is True

    def test_skips_readme(self):
        content = f"{VLESS}\n{TROJAN}\n{SS}\n"
        assert is_vpn_file("README.md", content) is False

    def test_skips_requirements(self):
        assert is_vpn_file("requirements.txt", "requests==2.31.0\naiohttp==3.9.5\n") is False

    def test_skips_yaml(self):
        assert is_vpn_file("workflow.yml", f"{VLESS}\n{TROJAN}\n{SS}") is False

    def test_rejects_non_vpn_content(self):
        assert is_vpn_file("data.txt", "hello world\nfoo bar\nbaz qux") is False

    def test_fewer_than_3_configs_not_vpn_file(self):
        assert is_vpn_file("sub.txt", f"{VLESS}\n{TROJAN}") is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_parser.py -v 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'is_vpn_line'`

- [ ] **Step 3: Implement vpn_collector/parser.py**

```python
import base64
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

from vpn_collector.config import VPN_PREFIXES, SKIP_FILENAMES, SKIP_EXTENSIONS


def is_vpn_line(line: str) -> bool:
    return any(line.strip().startswith(p) for p in VPN_PREFIXES)


def extract_host_port(line: str) -> tuple[str, int] | None:
    line = line.strip().split("#")[0]
    try:
        if line.startswith("vmess://"):
            payload = base64.b64decode(line[8:] + "==").decode("utf-8", errors="replace")
            data = json.loads(payload)
            return str(data["add"]), int(data["port"])
        parsed = urlparse(line)
        if parsed.hostname and parsed.port:
            return parsed.hostname, parsed.port
    except Exception:
        pass
    return None


def extract_name(line: str) -> str:
    if "#" in line:
        return unquote(line.split("#", 1)[1])
    return ""


def set_name(line: str, name: str) -> str:
    base = line.split("#")[0]
    return f"{base}#{name}"


def parse_configs_from_content(content: str) -> list[str]:
    content = content.strip()
    if not content:
        return []
    lines = _extract_lines(content)
    seen: set[str] = set()
    result = []
    for line in lines:
        line = line.strip()
        if is_vpn_line(line) and line not in seen:
            seen.add(line)
            result.append(line)
    return result


def _extract_lines(content: str) -> list[str]:
    lines = content.splitlines()
    if any(is_vpn_line(l.strip()) for l in lines):
        return lines
    try:
        padding = "=" * (4 - len(content) % 4) if len(content) % 4 else ""
        decoded = base64.b64decode(content + padding).decode("utf-8", errors="replace")
        decoded_lines = decoded.splitlines()
        if any(is_vpn_line(l.strip()) for l in decoded_lines):
            return decoded_lines
    except Exception:
        pass
    return lines


def is_vpn_file(filename: str, content: str) -> bool:
    path = Path(filename)
    name_lower = path.name.lower()
    if path.suffix.lower() in SKIP_EXTENSIONS:
        return False
    for skip in SKIP_FILENAMES:
        if name_lower.startswith(skip):
            return False
    return len(parse_configs_from_content(content)) >= 3
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_parser.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add vpn_collector/parser.py tests/test_parser.py
git commit -m "feat: parser module - VPN line detection and file filtering"
```

---

### Task 3: storage.py

**Files:**
- Create: `vpn_collector/storage.py`
- Create: `tests/test_storage.py`

- [ ] **Step 1: Write failing tests — create tests/test_storage.py**

```python
import pytest
from pathlib import Path
from vpn_collector.storage import (
    load_known_hosts, is_duplicate, save_config,
    rotate_run_files, get_stats, update_known_good_header,
)

VLESS1 = "vless://uuid1@1.2.3.4:443?type=tcp#Server1"
VLESS2 = "vless://uuid2@5.6.7.8:8080?type=tcp#Server2"
VLESS3 = "vless://uuid3@9.10.11.12:443?type=tcp#Server3"


@pytest.fixture
def results_dir(tmp_path):
    d = tmp_path / "results"
    d.mkdir()
    return d


class TestLoadKnownHosts:
    def test_empty_dir(self, results_dir):
        assert load_known_hosts(results_dir) == set()

    def test_loads_from_known_good(self, results_dir):
        (results_dir / "known_good.txt").write_text(f"# header\n{VLESS1}\n{VLESS2}\n")
        hosts = load_known_hosts(results_dir)
        assert "1.2.3.4:443" in hosts
        assert "5.6.7.8:8080" in hosts

    def test_loads_from_run_files(self, results_dir):
        (results_dir / "run_2026-01-01.txt").write_text(f"{VLESS3}\n")
        hosts = load_known_hosts(results_dir)
        assert "9.10.11.12:443" in hosts

    def test_skips_comment_lines(self, results_dir):
        (results_dir / "known_good.txt").write_text("# Updated: 2026-01-01 | Total: 1\n")
        hosts = load_known_hosts(results_dir)
        assert len(hosts) == 0


class TestIsDuplicate:
    def test_detects_duplicate(self):
        assert is_duplicate(VLESS1, {"1.2.3.4:443"}) is True

    def test_not_duplicate(self):
        assert is_duplicate(VLESS1, {"9.9.9.9:80"}) is False

    def test_same_host_different_name_is_duplicate(self):
        config = "vless://otheruuid@1.2.3.4:443?type=tcp#DifferentName"
        assert is_duplicate(config, {"1.2.3.4:443"}) is True


class TestSaveConfig:
    def test_saves_to_known_good_and_run(self, results_dir):
        known: set[str] = set()
        save_config(VLESS1, results_dir, known, run_date="2026-04-27")
        assert (results_dir / "known_good.txt").exists()
        assert (results_dir / "run_2026-04-27.txt").exists()
        assert VLESS1 in (results_dir / "known_good.txt").read_text()
        assert VLESS1 in (results_dir / "run_2026-04-27.txt").read_text()

    def test_updates_known_hosts_set(self, results_dir):
        known: set[str] = set()
        save_config(VLESS1, results_dir, known, run_date="2026-04-27")
        assert "1.2.3.4:443" in known


class TestRotateRunFiles:
    def test_keeps_max_files(self, results_dir):
        for i in range(6):
            (results_dir / f"run_2026-01-0{i+1}.txt").write_text("x")
        rotate_run_files(results_dir, max_files=5)
        assert len(list(results_dir.glob("run_*.txt"))) == 5

    def test_removes_oldest(self, results_dir):
        for i in range(6):
            (results_dir / f"run_2026-01-0{i+1}.txt").write_text("x")
        rotate_run_files(results_dir, max_files=5)
        assert not (results_dir / "run_2026-01-01.txt").exists()
        assert (results_dir / "run_2026-01-06.txt").exists()

    def test_does_not_touch_known_good(self, results_dir):
        for i in range(6):
            (results_dir / f"run_2026-01-0{i+1}.txt").write_text("x")
        (results_dir / "known_good.txt").write_text("important")
        rotate_run_files(results_dir, max_files=5)
        assert (results_dir / "known_good.txt").exists()


class TestGetStats:
    def test_returns_counts(self, results_dir):
        (results_dir / "known_good.txt").write_text(f"# header\n{VLESS1}\n{VLESS2}\n")
        (results_dir / "run_2026-04-27.txt").write_text(f"{VLESS1}\n")
        stats = get_stats(results_dir)
        assert stats["known_good"] == 2
        assert stats["run_2026-04-27"] == 1
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_storage.py -v 2>&1 | head -10
```

Expected: `ImportError`

- [ ] **Step 3: Implement vpn_collector/storage.py**

```python
from datetime import date, datetime
from pathlib import Path

from vpn_collector.parser import extract_host_port, is_vpn_line


def load_known_hosts(results_dir: Path) -> set[str]:
    hosts: set[str] = set()
    for f in results_dir.glob("*.txt"):
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
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_storage.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add vpn_collector/storage.py tests/test_storage.py
git commit -m "feat: storage module - deduplication and FIFO rotation"
```

---

### Task 4: sources.py

**Files:**
- Create: `vpn_collector/sources.py`
- Create: `tests/test_sources.py`

- [ ] **Step 1: Write failing tests — create tests/test_sources.py**

```python
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from vpn_collector.sources import (
    load_sources, save_sources, add_source,
    sync_stars, fetch_url_configs, fetch_repo_configs,
)

VLESS1 = "vless://uuid1@1.2.3.4:443?type=tcp#Server1"
VLESS2 = "vless://uuid2@5.6.7.8:8080?type=tcp#Server2"
VLESS3 = "vless://uuid3@9.0.0.1:443?type=tcp#Server3"


@pytest.fixture
def sources_file(tmp_path):
    return tmp_path / "sources.json"


class TestLoadSaveSources:
    def test_load_creates_default_if_missing(self, sources_file):
        sources = load_sources(sources_file)
        assert len(sources) > 0
        assert all("type" in s and "value" in s for s in sources)

    def test_load_reads_existing(self, sources_file):
        data = [{"type": "repo", "value": "user/repo"}]
        sources_file.write_text(json.dumps(data))
        assert load_sources(sources_file) == data

    def test_save_writes_json(self, sources_file):
        data = [{"type": "repo", "value": "user/repo"}]
        save_sources(data, sources_file)
        assert json.loads(sources_file.read_text()) == data


class TestAddSource:
    def test_add_repo(self, sources_file):
        sources_file.write_text(json.dumps([]))
        assert add_source("newuser/newrepo", sources_file) is True
        sources = load_sources(sources_file)
        assert any(s["value"] == "newuser/newrepo" for s in sources)

    def test_add_url(self, sources_file):
        sources_file.write_text(json.dumps([]))
        assert add_source("https://example.com/sub.txt", sources_file) is True
        sources = load_sources(sources_file)
        assert any(s["value"] == "https://example.com/sub.txt" for s in sources)

    def test_no_duplicate(self, sources_file):
        sources_file.write_text(json.dumps([{"type": "repo", "value": "user/repo"}]))
        add_source("user/repo", sources_file)
        assert len([s for s in load_sources(sources_file) if s["value"] == "user/repo"]) == 1

    def test_returns_false_for_existing(self, sources_file):
        sources_file.write_text(json.dumps([{"type": "repo", "value": "user/repo"}]))
        assert add_source("user/repo", sources_file) is False


class TestSyncStars:
    @patch("vpn_collector.sources.requests.get")
    def test_adds_new_repos(self, mock_get, sources_file):
        sources_file.write_text(json.dumps([]))
        mock_resp = MagicMock()
        mock_resp.json.side_effect = [
            [{"full_name": "user/vpn-repo1"}, {"full_name": "user/vpn-repo2"}],
            [],
        ]
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        assert sync_stars("testuser", sources_file) == 2

    @patch("vpn_collector.sources.requests.get")
    def test_skips_existing(self, mock_get, sources_file):
        sources_file.write_text(json.dumps([{"type": "repo", "value": "user/vpn-repo1"}]))
        mock_resp = MagicMock()
        mock_resp.json.side_effect = [[{"full_name": "user/vpn-repo1"}], []]
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        assert sync_stars("testuser", sources_file) == 0


class TestFetchUrlConfigs:
    @patch("vpn_collector.sources.requests.get")
    def test_returns_configs(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = f"{VLESS1}\n{VLESS2}\n{VLESS3}\n"
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        assert len(fetch_url_configs("https://example.com/sub.txt")) == 3

    @patch("vpn_collector.sources.requests.get")
    def test_returns_empty_on_error(self, mock_get):
        mock_get.side_effect = Exception("connection error")
        assert fetch_url_configs("https://example.com/sub.txt") == []


class TestFetchRepoConfigs:
    @patch("vpn_collector.sources.requests.get")
    def test_fetches_txt_files_recursively(self, mock_get, tmp_path):
        tree_resp = MagicMock()
        tree_resp.status_code = 200
        tree_resp.json.return_value = {
            "tree": [
                {"type": "blob", "path": "sub.txt"},
                {"type": "blob", "path": "subdir/nodes.txt"},
                {"type": "blob", "path": "README.md"},
                {"type": "tree", "path": "subdir"},
            ]
        }
        file_resp = MagicMock()
        file_resp.status_code = 200
        file_resp.text = f"{VLESS1}\n{VLESS2}\n{VLESS3}\n"
        mock_get.side_effect = [tree_resp, file_resp, file_resp]
        configs = fetch_repo_configs("user/repo")
        assert len(configs) == 3  # deduped across two identical files
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_sources.py -v 2>&1 | head -10
```

Expected: `ImportError`

- [ ] **Step 3: Implement vpn_collector/sources.py**

```python
import json
import logging
import os
import requests
from pathlib import Path

from vpn_collector.config import DEFAULT_SOURCES, PROXY_ENV_VARS, SOURCES_FILE
from vpn_collector.parser import parse_configs_from_content, is_vpn_file

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"


def _clean_session() -> requests.Session:
    session = requests.Session()
    env = {k: v for k, v in os.environ.items() if k not in PROXY_ENV_VARS}
    session.trust_env = False
    return session


def load_sources(sources_file: Path) -> list[dict]:
    if not sources_file.exists():
        save_sources(DEFAULT_SOURCES, sources_file)
        return DEFAULT_SOURCES.copy()
    return json.loads(sources_file.read_text())


def save_sources(sources: list[dict], sources_file: Path) -> None:
    sources_file.write_text(json.dumps(sources, indent=2))


def add_source(url_or_repo: str, sources_file: Path) -> bool:
    sources = load_sources(sources_file)
    if any(s["value"] == url_or_repo for s in sources):
        return False
    source_type = "url" if url_or_repo.startswith("http") else "repo"
    sources.append({"type": source_type, "value": url_or_repo})
    save_sources(sources, sources_file)
    return True


def sync_stars(username: str, sources_file: Path) -> int:
    sources = load_sources(sources_file)
    existing_values = {s["value"] for s in sources}
    added = 0
    page = 1
    while True:
        try:
            resp = requests.get(
                f"{GITHUB_API}/users/{username}/starred",
                params={"per_page": 100, "page": page},
                timeout=10,
            )
            repos = resp.json()
            if not repos:
                break
            for repo in repos:
                full_name = repo["full_name"]
                if full_name not in existing_values:
                    sources.append({"type": "repo", "value": full_name})
                    existing_values.add(full_name)
                    added += 1
            page += 1
        except Exception as e:
            logger.warning(f"Failed to fetch stars page {page}: {e}")
            break
    save_sources(sources, sources_file)
    return added


def fetch_url_configs(url: str) -> list[str]:
    try:
        resp = _clean_session().get(url, timeout=15)
        return parse_configs_from_content(resp.text)
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return []


def fetch_repo_configs(repo: str) -> list[str]:
    try:
        session = _clean_session()
        resp = session.get(
            f"{GITHUB_API}/repos/{repo}/git/trees/HEAD",
            params={"recursive": "1"},
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning(f"Trees API {resp.status_code} for {repo}")
            return []
        txt_files = [
            item["path"] for item in resp.json().get("tree", [])
            if item["type"] == "blob" and item["path"].endswith(".txt")
        ]
        seen: set[str] = set()
        configs: list[str] = []
        for path in txt_files:
            try:
                raw = session.get(f"{GITHUB_RAW}/{repo}/HEAD/{path}", timeout=10)
                if raw.status_code != 200:
                    continue
                if is_vpn_file(path, raw.text):
                    for c in parse_configs_from_content(raw.text):
                        if c not in seen:
                            seen.add(c)
                            configs.append(c)
            except Exception as e:
                logger.debug(f"Skipped {repo}/{path}: {e}")
        return configs
    except Exception as e:
        logger.warning(f"Failed to process repo {repo}: {e}")
        return []


def fetch_all_configs(sources_file: Path) -> list[str]:
    sources = load_sources(sources_file)
    seen: set[str] = set()
    all_configs: list[str] = []
    for source in sources:
        if source["type"] == "repo":
            configs = fetch_repo_configs(source["value"])
        else:
            configs = fetch_url_configs(source["value"])
        for c in configs:
            if c not in seen:
                seen.add(c)
                all_configs.append(c)
    return all_configs
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_sources.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add vpn_collector/sources.py tests/test_sources.py
git commit -m "feat: sources module - GitHub Trees API, sources.json, stars sync"
```

---

### Task 5: tester.py — Stage 1 TCP filter

**Files:**
- Create: `vpn_collector/tester.py`
- Create: `tests/test_tester.py`

- [ ] **Step 1: Write failing tests — create tests/test_tester.py**

```python
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
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_tester.py -v 2>&1 | head -10
```

Expected: `ImportError`

- [ ] **Step 3: Create vpn_collector/tester.py with TCP stage**

```python
import asyncio
import logging
import os

from vpn_collector.config import TCP_TIMEOUT, TCP_CONCURRENCY, PROXY_ENV_VARS
from vpn_collector.parser import extract_host_port

logger = logging.getLogger(__name__)


async def tcp_check(host: str, port: int, timeout: float = TCP_TIMEOUT) -> bool:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def tcp_filter(
    configs: list[str],
    concurrency: int = TCP_CONCURRENCY,
    timeout: float = TCP_TIMEOUT,
) -> list[str]:
    semaphore = asyncio.Semaphore(concurrency)

    async def check_one(config: str) -> str | None:
        hp = extract_host_port(config)
        if not hp:
            return None
        async with semaphore:
            return config if await tcp_check(hp[0], hp[1], timeout) else None

    results = await asyncio.gather(*[check_one(c) for c in configs])
    return [r for r in results if r is not None]
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_tester.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add vpn_collector/tester.py tests/test_tester.py
git commit -m "feat: tester Stage 1 - async TCP pre-filter"
```

---

### Task 6: tester.py — sing-box discovery and per-protocol config generation

**Files:**
- Modify: `vpn_collector/tester.py`
- Modify: `tests/test_tester.py`

- [ ] **Step 1: Append failing tests to tests/test_tester.py**

```python
import base64
from pathlib import Path
from unittest.mock import patch
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
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_tester.py::TestFindSingbox tests/test_tester.py::TestGenerateSingboxConfig -v 2>&1 | head -10
```

Expected: `ImportError` or `AttributeError`

- [ ] **Step 3: Append to vpn_collector/tester.py**

```python
import base64
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

from vpn_collector.config import SINGBOX_SEARCH_PATHS


def find_singbox() -> str | None:
    for search_path in SINGBOX_SEARCH_PATHS:
        for name in ("sing-box", "singbox"):
            candidate = Path(search_path) / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None


def _singbox_wrapper(socks_port: int, outbound: dict) -> dict:
    return {
        "log": {"level": "error"},
        "inbounds": [{
            "type": "socks",
            "tag": "socks-in",
            "listen": "127.0.0.1",
            "listen_port": socks_port,
        }],
        "outbounds": [outbound],
    }


def _parse_vless(line: str) -> dict:
    p = urlparse(line)
    params = parse_qs(p.query)
    security = params.get("security", ["none"])[0]
    sni = params.get("sni", params.get("host", [p.hostname]))[0]
    transport_type = params.get("type", ["tcp"])[0]
    outbound: dict = {
        "type": "vless",
        "tag": "proxy",
        "server": p.hostname,
        "server_port": p.port,
        "uuid": p.username,
        "flow": params.get("flow", [""])[0],
    }
    if security in ("tls", "reality", "xtls"):
        outbound["tls"] = {
            "enabled": True,
            "server_name": sni,
            "insecure": True,
            "utls": {"enabled": True, "fingerprint": "chrome"},
        }
        if security == "reality":
            outbound["tls"]["reality"] = {
                "enabled": True,
                "public_key": params.get("pbk", [""])[0],
                "short_id": params.get("sid", [""])[0],
            }
    if transport_type == "ws":
        outbound["transport"] = {
            "type": "ws",
            "path": params.get("path", ["/"])[0],
            "headers": {"Host": params.get("host", [sni])[0]},
        }
    elif transport_type == "grpc":
        outbound["transport"] = {
            "type": "grpc",
            "service_name": params.get("serviceName", [""])[0],
        }
    return outbound


def _parse_vmess(line: str) -> dict:
    payload = base64.b64decode(line[8:] + "==").decode("utf-8", errors="replace")
    data = json.loads(payload)
    outbound: dict = {
        "type": "vmess",
        "tag": "proxy",
        "server": data["add"],
        "server_port": int(data.get("port", 443)),
        "uuid": data["id"],
        "security": data.get("scy", "auto") or "auto",
        "alter_id": int(data.get("aid", 0)),
    }
    if str(data.get("tls", "")).lower() == "tls":
        outbound["tls"] = {
            "enabled": True,
            "server_name": data.get("sni") or data.get("host") or data["add"],
            "insecure": True,
        }
    net = data.get("net", "tcp")
    if net == "ws":
        outbound["transport"] = {
            "type": "ws",
            "path": data.get("path", "/"),
            "headers": {"Host": data.get("host", data["add"])},
        }
    elif net == "grpc":
        outbound["transport"] = {"type": "grpc", "service_name": data.get("path", "")}
    return outbound


def _parse_trojan(line: str) -> dict:
    p = urlparse(line)
    params = parse_qs(p.query)
    sni = params.get("sni", [p.hostname])[0]
    return {
        "type": "trojan",
        "tag": "proxy",
        "server": p.hostname,
        "server_port": p.port,
        "password": unquote(p.username or ""),
        "tls": {"enabled": True, "server_name": sni, "insecure": True},
    }


def _parse_ss(line: str) -> dict:
    p = urlparse(line)
    if p.username and p.hostname and p.port:
        method = unquote(p.username)
        password = unquote(p.password or "")
        host, port = p.hostname, p.port
    else:
        userinfo_host = line[5:].split("#")[0]
        at_pos = userinfo_host.rfind("@")
        userinfo = userinfo_host[:at_pos]
        hostport = userinfo_host[at_pos + 1:]
        try:
            decoded = base64.b64decode(userinfo + "==").decode()
        except Exception:
            decoded = userinfo
        method, password = (decoded.split(":", 1) + [""])[:2]
        host, port_str = hostport.rsplit(":", 1)
        port = int(port_str)
    return {
        "type": "shadowsocks",
        "tag": "proxy",
        "server": host,
        "server_port": port,
        "method": method,
        "password": password,
    }


def _parse_hy2(line: str) -> dict:
    p = urlparse(line)
    params = parse_qs(p.query)
    sni = params.get("sni", [p.hostname])[0]
    password = unquote(p.username or "") or unquote(p.password or "")
    return {
        "type": "hysteria2",
        "tag": "proxy",
        "server": p.hostname,
        "server_port": p.port,
        "password": password,
        "tls": {"enabled": True, "server_name": sni, "insecure": True},
    }


def _parse_tuic(line: str) -> dict:
    p = urlparse(line)
    params = parse_qs(p.query)
    sni = params.get("sni", [p.hostname])[0]
    return {
        "type": "tuic",
        "tag": "proxy",
        "server": p.hostname,
        "server_port": p.port,
        "uuid": unquote(p.username or ""),
        "password": unquote(p.password or ""),
        "congestion_control": params.get("congestion_control", ["bbr"])[0],
        "tls": {"enabled": True, "server_name": sni, "insecure": True},
    }


def generate_singbox_config(config_line: str, socks_port: int) -> dict:
    line = config_line.strip().split("#")[0]
    if line.startswith("vless://"):
        outbound = _parse_vless(line)
    elif line.startswith("vmess://"):
        outbound = _parse_vmess(line)
    elif line.startswith("trojan://"):
        outbound = _parse_trojan(line)
    elif line.startswith("ss://"):
        outbound = _parse_ss(line)
    elif line.startswith(("hysteria2://", "hy2://")):
        outbound = _parse_hy2(line)
    elif line.startswith("hysteria://"):
        outbound = _parse_hy2(line)
    elif line.startswith("tuic://"):
        outbound = _parse_tuic(line)
    else:
        raise ValueError(f"Unsupported protocol: {line[:20]}")
    return _singbox_wrapper(socks_port, outbound)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_tester.py::TestFindSingbox tests/test_tester.py::TestGenerateSingboxConfig -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add vpn_collector/tester.py tests/test_tester.py
git commit -m "feat: tester - sing-box discovery and per-protocol config generation"
```

---

### Task 7: tester.py — tunnel orchestration, speedtest, Claude.com check

**Files:**
- Modify: `vpn_collector/tester.py`
- Modify: `tests/test_tester.py`

- [ ] **Step 1: Append failing tests to tests/test_tester.py**

```python
import subprocess
import time
from unittest.mock import patch, MagicMock, call
from vpn_collector.tester import (
    speedtest_via_socks, check_claude_via_socks,
    test_config_tunnel, tunnel_filter,
)

VLESS_TEST = "vless://some-uuid@host.com:443?type=tcp&security=tls&sni=host.com#TestServer"


class TestSpeedtestViaSocks:
    def test_returns_speed_in_mbps(self):
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"x" * (1024 * 1024)]
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("vpn_collector.tester.requests.Session") as MockSession, \
             patch("vpn_collector.tester.time.time", side_effect=[0.0, 1.0]):
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

    def test_plus_when_accessible(self):
        resp = MagicMock(status_code=200, url="https://claude.com/", text="<html>Claude</html>")
        with patch("vpn_collector.tester.requests.Session") as M:
            self._mock_session(M, resp)
            assert check_claude_via_socks(12002) == "+++"

    def test_minus_on_keyword_in_body(self):
        resp = MagicMock(status_code=200, url="https://claude.com/", text="app unavailable in region")
        with patch("vpn_collector.tester.requests.Session") as M:
            self._mock_session(M, resp)
            assert check_claude_via_socks(12003) == "---"

    def test_minus_on_status_451(self):
        resp = MagicMock(status_code=451, url="https://claude.com/", text="")
        with patch("vpn_collector.tester.requests.Session") as M:
            self._mock_session(M, resp)
            assert check_claude_via_socks(12004) == "---"

    def test_minus_on_blocked_url_keyword(self):
        resp = MagicMock(status_code=200, url="https://claude.com/region-unavailable", text="hello")
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
        with patch("vpn_collector.tester.generate_singbox_config", return_value={}), \
             patch("vpn_collector.tester.subprocess.Popen") as mock_popen, \
             patch("vpn_collector.tester.speedtest_via_socks", return_value=5.0), \
             patch("vpn_collector.tester.check_claude_via_socks", return_value="+++"), \
             patch("vpn_collector.tester.time.sleep"), \
             patch("vpn_collector.tester.json.dump"), \
             patch("builtins.open", MagicMock()), \
             patch("os.unlink"):
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_proc.terminate = MagicMock()
            mock_proc.wait = MagicMock()
            mock_popen.return_value.__enter__ = lambda s: mock_proc
            mock_popen.return_value.__exit__ = MagicMock(return_value=False)
            result = test_config_tunnel(VLESS_TEST, "/usr/bin/sing-box", socks_port=13000)
        assert result is not None
        assert "#+++TestServer" in result

    def test_returns_none_below_speed_threshold(self):
        with patch("vpn_collector.tester.generate_singbox_config", return_value={}), \
             patch("vpn_collector.tester.subprocess.Popen") as mock_popen, \
             patch("vpn_collector.tester.speedtest_via_socks", return_value=0.3), \
             patch("vpn_collector.tester.time.sleep"), \
             patch("vpn_collector.tester.json.dump"), \
             patch("builtins.open", MagicMock()), \
             patch("os.unlink"):
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_popen.return_value.__enter__ = lambda s: mock_proc
            mock_popen.return_value.__exit__ = MagicMock(return_value=False)
            result = test_config_tunnel(VLESS_TEST, "/usr/bin/sing-box", socks_port=13001)
        assert result is None
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_tester.py::TestSpeedtestViaSocks tests/test_tester.py::TestCheckClaudeViaSocks tests/test_tester.py::TestTestConfigTunnel -v 2>&1 | head -10
```

Expected: `ImportError`

- [ ] **Step 3: Append tunnel functions to vpn_collector/tester.py**

```python
import random
import subprocess
import tempfile
import time
import requests
from vpn_collector.config import (
    MIN_SPEED_MBPS, SPEEDTEST_URL, CLAUDE_CHECK_URL,
    CLAUDE_BLOCK_KEYWORDS, CLAUDE_BLOCK_URL_KEYWORDS,
    SINGBOX_STARTUP_TIMEOUT, TUNNEL_CONCURRENCY, SOCKS_PORT_RANGE, PROXY_ENV_VARS,
)
from vpn_collector.parser import extract_name, set_name


def _socks_session(socks_port: int) -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.proxies = {
        "http": f"socks5h://127.0.0.1:{socks_port}",
        "https": f"socks5h://127.0.0.1:{socks_port}",
    }
    return session


def speedtest_via_socks(socks_port: int) -> float:
    try:
        with _socks_session(socks_port) as session:
            start = time.time()
            resp = session.get(SPEEDTEST_URL, stream=True, timeout=15)
            downloaded = 0
            for chunk in resp.iter_content(chunk_size=65536):
                downloaded += len(chunk)
                if downloaded >= 1024 * 1024:
                    break
            elapsed = time.time() - start
            return (downloaded * 8) / (elapsed * 1_000_000) if elapsed > 0 else 0.0
    except Exception:
        return 0.0


def check_claude_via_socks(socks_port: int) -> str:
    try:
        with _socks_session(socks_port) as session:
            resp = session.get(CLAUDE_CHECK_URL, timeout=15, allow_redirects=True)
            if resp.status_code == 451:
                return "---"
            final_url = resp.url.lower()
            if any(kw in final_url for kw in CLAUDE_BLOCK_URL_KEYWORDS):
                return "---"
            body = resp.text.lower()
            if any(kw in body for kw in CLAUDE_BLOCK_KEYWORDS):
                return "---"
            return "+++"
    except Exception:
        return "---"


def test_config_tunnel(
    config_line: str, singbox_path: str, socks_port: int
) -> str | None:
    clean_env = {k: v for k, v in os.environ.items() if k not in PROXY_ENV_VARS}
    try:
        cfg = generate_singbox_config(config_line, socks_port)
    except Exception as e:
        logger.debug(f"Config generation failed: {e}")
        return None

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        json.dump(cfg, tmp)
        cfg_path = tmp.name

    proc = None
    try:
        proc = subprocess.Popen(
            [singbox_path, "run", "-c", cfg_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=clean_env,
        )
        time.sleep(SINGBOX_STARTUP_TIMEOUT)
        if proc.poll() is not None:
            return None
        if speedtest_via_socks(socks_port) < MIN_SPEED_MBPS:
            return None
        marker = check_claude_via_socks(socks_port)
        return set_name(config_line, f"{marker}{extract_name(config_line)}")
    except Exception as e:
        logger.debug(f"Tunnel test error: {e}")
        return None
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            os.unlink(cfg_path)
        except Exception:
            pass


async def tunnel_filter(
    candidates: list[str],
    singbox_path: str,
    concurrency: int = TUNNEL_CONCURRENCY,
) -> list[str]:
    semaphore = asyncio.Semaphore(concurrency)
    used_ports: set[int] = set()

    def get_port() -> int:
        while True:
            p = random.randint(*SOCKS_PORT_RANGE)
            if p not in used_ports:
                used_ports.add(p)
                return p

    async def test_one(config: str) -> str | None:
        port = get_port()
        async with semaphore:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, test_config_tunnel, config, singbox_path, port
            )

    results = await asyncio.gather(*[test_one(c) for c in candidates])
    return [r for r in results if r is not None]
```

- [ ] **Step 4: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add vpn_collector/tester.py tests/test_tester.py
git commit -m "feat: tester Stage 2 - speedtest, Claude.com check, tunnel orchestration"
```

---

### Task 8: main.py — CLI wiring

**Files:**
- Create: `vpn_collector/main.py`

- [ ] **Step 1: Create vpn_collector/main.py**

```python
import argparse
import asyncio
import logging
import sys
from datetime import date

from vpn_collector.config import (
    RESULTS_DIR, SOURCES_FILE, LOGS_DIR, MAX_RUN_FILES,
)
from vpn_collector.sources import fetch_all_configs, add_source, sync_stars
from vpn_collector.tester import tcp_filter, tunnel_filter, find_singbox
from vpn_collector.storage import (
    load_known_hosts, is_duplicate, save_config,
    rotate_run_files, get_stats,
)


def _setup_logging() -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOGS_DIR / "vpn_collector.log"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def cmd_collect() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    print("Fetching configs from all sources...")
    configs = fetch_all_configs(SOURCES_FILE)
    print(f"Collected {len(configs)} unique configs")

    print("Running TCP pre-filter...")
    candidates = asyncio.run(tcp_filter(configs))
    print(f"TCP passed: {len(candidates)}")

    (RESULTS_DIR / "candidates.txt").write_text("\n".join(candidates))
    print(f"Saved to results/candidates.txt")


def cmd_test() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    candidates_file = RESULTS_DIR / "candidates.txt"
    if not candidates_file.exists():
        print("No candidates.txt found. Run --collect first.")
        sys.exit(1)

    singbox_path = find_singbox()
    if not singbox_path:
        from vpn_collector.config import SINGBOX_SEARCH_PATHS
        print("sing-box binary not found. Searched:")
        for p in SINGBOX_SEARCH_PATHS:
            print(f"  {p}")
        sys.exit(1)
    print(f"Using sing-box: {singbox_path}")

    candidates = [l for l in candidates_file.read_text().splitlines() if l.strip()]
    known_hosts = load_known_hosts(RESULTS_DIR)
    new_candidates = [c for c in candidates if not is_duplicate(c, known_hosts)]
    print(f"Candidates: {len(candidates)} | New (not in history): {len(new_candidates)}")

    tested = asyncio.run(tunnel_filter(new_candidates, singbox_path))
    print(f"Passed all tests: {len(tested)}")

    run_date = date.today().isoformat()
    for config in tested:
        save_config(config, RESULTS_DIR, known_hosts, run_date=run_date)
    rotate_run_files(RESULTS_DIR, MAX_RUN_FILES)
    print(f"Results saved to results/run_{run_date}.txt and results/known_good.txt")


def cmd_full() -> None:
    cmd_collect()
    cmd_test()


def cmd_stats() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    stats = get_stats(RESULTS_DIR)
    if not stats:
        print("No result files found.")
        return
    for name, count in sorted(stats.items()):
        print(f"  {name}: {count} configs")


def main() -> None:
    _setup_logging()
    parser = argparse.ArgumentParser(description="VPN Config Collector and Tester")
    parser.add_argument("--collect", action="store_true", help="Fetch configs, TCP filter → candidates.txt")
    parser.add_argument("--test", action="store_true", help="Tunnel test candidates.txt → known_good.txt")
    parser.add_argument("--full", action="store_true", help="Run --collect then --test")
    parser.add_argument("--stats", action="store_true", help="Show counts per result file")
    parser.add_argument("--add-source", metavar="SOURCE", help="Add GitHub repo (user/repo) or raw URL")
    parser.add_argument("--sync-stars", metavar="USERNAME", help="Sync GitHub starred repos")
    args = parser.parse_args()

    if args.collect:
        cmd_collect()
    elif args.test:
        cmd_test()
    elif args.full:
        cmd_full()
    elif args.stats:
        cmd_stats()
    elif args.add_source:
        added = add_source(args.add_source, SOURCES_FILE)
        print("Added." if added else "Already exists.")
    elif args.sync_stars:
        count = sync_stars(args.sync_stars, SOURCES_FILE)
        print(f"Added {count} new repo(s) from stars.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test — stats command**

```bash
python -m vpn_collector.main --stats
```

Expected: `No result files found.` (no crash, results/ dir created)

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add vpn_collector/main.py
git commit -m "feat: main.py CLI wiring all commands"
```

---

## Self-Review

**Spec coverage:**
- ✅ Protocols: vless, vmess, trojan, ss, hysteria, hysteria2, hy2, tuic
- ✅ Stage 1 async TCP pre-filter (50 concurrent, asyncio)
- ✅ Stage 2 sing-box tunnel test (5 concurrent via `asyncio.run_in_executor`)
- ✅ Speedtest ≥1 Mbit/s filter
- ✅ Claude.com check: final URL keywords, HTML body keywords, HTTP 451 → `---` / `+++`
- ✅ `#+++name` / `#---name` markers on server name (not on full URI)
- ✅ Deduplication by `host:port` across `known_good.txt` + all `run_*.txt`
- ✅ FIFO rotation (max 5 `run_*.txt`), `known_good.txt` permanent
- ✅ VPN file detection — skips README, requirements, yaml, json, md, py, sh
- ✅ Recursive repo traversal via GitHub Trees API (`?recursive=1`)
- ✅ `sources.json` persistence, `--add-source`, `--sync-stars`
- ✅ System proxy isolation (`trust_env=False`, `PROXY_ENV_VARS` cleared for subprocesses)
- ✅ sing-box auto-discovery from Throne installation paths
- ✅ Two-stage execution: `--collect` / `--test` / `--full`

**Placeholder scan:** No TBD, TODO, or incomplete steps found.

**Type consistency:** `extract_host_port` → `tuple[str,int]|None` used consistently in parser.py, storage.py, tester.py. `set_name` / `extract_name` signatures match across tester.py and tests.
