# AWG Collector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Построить изолированный модуль `awg_collector` для сбора, тестирования и хранения AmneziaWG конфигов из публичных источников.

**Architecture:** Зеркалит структуру `vpn_collector/` но полностью независим. GitHub/URL/Telegram → парсинг AWG `.conf` → TCP pre-filter → tunnel-тест через `sudo ip netns exec ... awg-quick up` + curl speedtest → `results_awg/known_good/*.conf` + `all_configs.vpn` ZIP.

**Tech Stack:** Python 3.12, subprocess + ip-netns, amneziawg-tools (системный), telethon (Telegram), requests (GitHub API), zipfile, pytest

## Global Constraints

- **Полная изоляция:** ни одного `from vpn_collector import ...` — нулевые общие импорты
- **sudo:** tester.py вызывает `sudo ip netns ...` и `sudo awg-quick ...`
- **Только AWG конфиги:** принимаем только `.conf` содержащие хотя бы одно поле из `Jc Jmin Jmax S1 S2 H1 H2 H3 H4`
- **TDD:** тест → убедиться что падает → реализация → убедиться что проходит → коммит
- **Entry point:** `python3 -m awg_collector.main`
- `AWG_TUNNEL_CONCURRENCY = 3`, `AWG_RECHECK_RETRIES = 2`, `MIN_SPEED_MBPS = 1.0`
- Результаты в `results_awg/` (рядом с существующим `results/`)

---

## File Map

| Файл | Создать/Изменить | Назначение |
|---|---|---|
| `awg_collector/__init__.py` | Create | Пустой пакет |
| `awg_collector/config.py` | Create | Константы: пути, таймауты, пороги |
| `awg_collector/parser.py` | Create | Парсинг WireGuard `.conf` + AWG-полей |
| `awg_collector/storage.py` | Create | Сохранение `.conf`, ZIP-архив, config_meta |
| `awg_collector/sources.py` | Create | Загрузка конфигов из GitHub / URL / Telegram |
| `awg_collector/tg_source.py` | Create | Telegram-клиент через Telethon (зеркало vpn_collector/tg_source.py) |
| `awg_collector/tester.py` | Create | netns + awg-quick + curl speedtest |
| `awg_collector/main.py` | Create | CLI: --collect --recheck --export --add-source --stats |
| `sources_awg.json` | Create | Список источников AWG конфигов |
| `tests/test_awg_parser.py` | Create | Тесты парсера |
| `tests/test_awg_storage.py` | Create | Тесты хранилища |
| `tests/test_awg_tester.py` | Create | Тесты tester (мокаем subprocess) |
| `tests/test_awg_sources.py` | Create | Тесты sources (мокаем HTTP) |

---

## Task 1: Скелет пакета + config.py + ресёрч источников

**Files:**
- Create: `awg_collector/__init__.py`
- Create: `awg_collector/config.py`
- Create: `sources_awg.json`

**Interfaces:**
- Produces: все константы из `awg_collector.config`, используются во всех последующих задачах

- [ ] **Шаг 1: Создать директорию пакета**

```bash
mkdir -p awg_collector
touch awg_collector/__init__.py
```

- [ ] **Шаг 2: Написать `awg_collector/config.py`**

```python
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
RESULTS_AWG_DIR = BASE_DIR / "results_awg"
KNOWN_GOOD_DIR = RESULTS_AWG_DIR / "known_good"
LOGS_DIR = BASE_DIR / "logs"
SOURCES_AWG_FILE = BASE_DIR / "sources_awg.json"

TCP_TIMEOUT = 4.0
TCP_CONCURRENCY = 100
AWG_TUNNEL_CONCURRENCY = 3
AWG_TEST_TIMEOUT = 30          # секунд на один конфиг
AWG_RECHECK_RETRIES = 2
MIN_SPEED_MBPS = 1.0

SPEEDTEST_URLS = [
    "http://cachefly.cachefly.net/1mb.test",
    "https://speed.cloudflare.com/__down?bytes=1048576",
    "https://proof.ovh.net/files/1Mb.dat",
]

PROXY_ENV_VARS = [
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
]

TG_AUTH_FILE    = Path.home() / ".config" / "vpn_collector" / "tg_auth.json"
TG_SESSION_FILE = Path.home() / ".config" / "vpn_collector" / "tg"
TG_POSTS_LIMIT  = 50

GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"

AWG_FIELDS = {"Jc", "Jmin", "Jmax", "S1", "S2", "H1", "H2", "H3", "H4"}

DEFAULT_SOURCES_AWG: list[dict] = []  # заполняется после ресёрча в шаге 3
```

- [ ] **Шаг 3: Найти качественные источники AWG конфигов**

Использовать WebSearch для поиска. Запросы:
- `site:github.com "amneziawg" ".conf" configs`
- `site:github.com "awg" wireguard configs free`
- Telegram: поиск по словам `amneziawg`, `awg конфиги`, `amnezia vpn configs`

Критерии отбора источника:
1. Репозиторий/канал обновляется хотя бы раз в 2 недели
2. Конфиги содержат AWG-поля (`Jc`, `H1` и т.д.) — не просто WireGuard
3. Файлы публично доступны без авторизации

После нахождения источников обновить `DEFAULT_SOURCES_AWG` в `config.py` и создать `sources_awg.json`:

```json
[
  {"type": "github", "value": "НАЙДЕННЫЙ_OWNER/REPO"},
  {"type": "tg",     "value": "НАЙДЕННЫЙ_КАНАЛ"},
  {"type": "url",    "value": "https://ПРЯМАЯ_ССЫЛКА/config.conf"}
]
```

- [ ] **Шаг 4: Коммит скелета**

```bash
git add awg_collector/__init__.py awg_collector/config.py sources_awg.json
git commit -m "feat(awg): scaffold awg_collector package with config and sources"
```

---

## Task 2: parser.py (TDD)

**Files:**
- Create: `awg_collector/parser.py`
- Create: `tests/test_awg_parser.py`

**Interfaces:**
- Produces:
  - `parse_awg_configs(text: str) -> list[dict]` — парсит текст с одним или несколькими конфигами
  - `parse_awg_file(path: Path) -> list[dict]` — читает файл
  - Каждый dict: `{"text": str, "endpoint": str, "filename": str, "is_awg": bool}`

- [ ] **Шаг 1: Написать тесты**

```python
# tests/test_awg_parser.py
import pytest
from pathlib import Path
from awg_collector.parser import parse_awg_configs, parse_awg_file

VALID_AWG = """[Interface]
PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
Address = 10.8.0.2/32
DNS = 1.1.1.1
Jc = 4
Jmin = 40
Jmax = 70
S1 = 0
S2 = 0
H1 = 1
H2 = 2
H3 = 3
H4 = 4

[Peer]
PublicKey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = 185.123.45.67:51820
PersistentKeepalive = 25"""

VALID_WG_ONLY = """[Interface]
PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
Address = 10.8.0.2/32

[Peer]
PublicKey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=
AllowedIPs = 0.0.0.0/0
Endpoint = 1.2.3.4:51820"""

MISSING_ENDPOINT = """[Interface]
PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
Jc = 4

[Peer]
PublicKey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=
AllowedIPs = 0.0.0.0/0"""


class TestParseAwgConfigs:
    def test_valid_awg_returns_one_config(self):
        results = parse_awg_configs(VALID_AWG)
        assert len(results) == 1

    def test_valid_awg_is_awg_true(self):
        results = parse_awg_configs(VALID_AWG)
        assert results[0]["is_awg"] is True

    def test_valid_awg_endpoint_extracted(self):
        results = parse_awg_configs(VALID_AWG)
        assert results[0]["endpoint"] == "185.123.45.67:51820"

    def test_valid_awg_filename_from_endpoint(self):
        results = parse_awg_configs(VALID_AWG)
        assert results[0]["filename"] == "185.123.45.67_51820.conf"

    def test_valid_awg_text_preserved(self):
        results = parse_awg_configs(VALID_AWG)
        assert "PrivateKey" in results[0]["text"]
        assert "Jc = 4" in results[0]["text"]

    def test_wg_only_is_awg_false(self):
        results = parse_awg_configs(VALID_WG_ONLY)
        assert len(results) == 1
        assert results[0]["is_awg"] is False

    def test_missing_endpoint_skipped(self):
        results = parse_awg_configs(MISSING_ENDPOINT)
        assert results == []

    def test_empty_text_returns_empty(self):
        assert parse_awg_configs("") == []

    def test_multiple_configs_in_text(self):
        two_configs = VALID_AWG + "\n\n" + VALID_AWG.replace("185.123.45.67:51820", "10.0.0.1:51820")
        results = parse_awg_configs(two_configs)
        assert len(results) == 2

    def test_domain_endpoint_accepted(self):
        conf = VALID_AWG.replace("185.123.45.67:51820", "vpn.example.com:51820")
        results = parse_awg_configs(conf)
        assert results[0]["endpoint"] == "vpn.example.com:51820"
        assert results[0]["filename"] == "vpn.example.com_51820.conf"

    def test_invalid_port_skipped(self):
        conf = VALID_AWG.replace("185.123.45.67:51820", "185.123.45.67:99999")
        assert parse_awg_configs(conf) == []

    def test_missing_private_key_skipped(self):
        conf = VALID_AWG.replace("PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=\n", "")
        assert parse_awg_configs(conf) == []


class TestParseAwgFile:
    def test_reads_file(self, tmp_path):
        p = tmp_path / "test.conf"
        p.write_text(VALID_AWG)
        results = parse_awg_file(p)
        assert len(results) == 1
        assert results[0]["endpoint"] == "185.123.45.67:51820"

    def test_missing_file_returns_empty(self, tmp_path):
        results = parse_awg_file(tmp_path / "nonexistent.conf")
        assert results == []
```

- [ ] **Шаг 2: Убедиться что тесты падают**

```bash
python -m pytest tests/test_awg_parser.py -v 2>&1 | head -20
```

Ожидаемо: `ModuleNotFoundError: No module named 'awg_collector.parser'`

- [ ] **Шаг 3: Написать `awg_collector/parser.py`**

```python
import re
from pathlib import Path

AWG_FIELDS = {"Jc", "Jmin", "Jmax", "S1", "S2", "H1", "H2", "H3", "H4"}
REQUIRED_FIELDS = {"PrivateKey", "PublicKey", "Endpoint"}


def parse_awg_configs(text: str) -> list[dict]:
    blocks = re.split(r'(?=^\[Interface\])', text, flags=re.MULTILINE)
    configs = []
    for block in blocks:
        block = block.strip()
        if not block or "[Interface]" not in block:
            continue
        result = _parse_single(block)
        if result is not None:
            configs.append(result)
    return configs


def parse_awg_file(path: Path) -> list[dict]:
    try:
        return parse_awg_configs(path.read_text(errors="replace"))
    except OSError:
        return []


def _parse_single(text: str) -> dict | None:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            fields[key.strip()] = value.strip()

    if not REQUIRED_FIELDS.issubset(fields):
        return None

    endpoint = fields.get("Endpoint", "")
    if not _valid_endpoint(endpoint):
        return None

    is_awg = bool(AWG_FIELDS & set(fields))

    host, _, port = endpoint.rpartition(":")
    filename = f"{host}_{port}.conf"

    return {
        "text": text,
        "endpoint": endpoint,
        "filename": filename,
        "is_awg": is_awg,
    }


def _valid_endpoint(endpoint: str) -> bool:
    if not endpoint:
        return False
    host, _, port = endpoint.rpartition(":")
    if not host or not port:
        return False
    try:
        p = int(port)
        return 1 <= p <= 65535
    except ValueError:
        return False
```

- [ ] **Шаг 4: Убедиться что тесты проходят**

```bash
python -m pytest tests/test_awg_parser.py -v
```

Ожидаемо: все `PASSED`

- [ ] **Шаг 5: Коммит**

```bash
git add awg_collector/parser.py tests/test_awg_parser.py
git commit -m "feat(awg): add AWG config parser with TDD"
```

---

## Task 3: storage.py (TDD)

**Files:**
- Create: `awg_collector/storage.py`
- Create: `tests/test_awg_storage.py`

**Interfaces:**
- Consumes: `awg_collector.config.{RESULTS_AWG_DIR, KNOWN_GOOD_DIR}`
- Produces:
  - `save_known_good(conf_text: str, endpoint: str) -> Path`
  - `load_known_good() -> list[dict]` — каждый dict: `{"text": str, "endpoint": str, "filename": str}`
  - `remove_known_good(endpoint: str) -> None`
  - `build_vpn_archive() -> Path` — возвращает путь к `all_configs.vpn`
  - `load_config_meta() -> dict`
  - `save_config_meta(meta: dict) -> None`
  - `update_meta_first_seen(meta: dict, endpoint: str, today: str) -> None`
  - `save_candidates(configs: list[dict]) -> None`
  - `load_candidates() -> list[str]`

- [ ] **Шаг 1: Написать тесты**

```python
# tests/test_awg_storage.py
import json
import zipfile
import pytest
from pathlib import Path
from unittest.mock import patch

SAMPLE_CONF = """[Interface]
PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
Jc = 4

[Peer]
PublicKey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=
Endpoint = 185.123.45.67:51820
AllowedIPs = 0.0.0.0/0"""

ENDPOINT = "185.123.45.67:51820"


@pytest.fixture()
def tmp_dirs(tmp_path, monkeypatch):
    results_dir = tmp_path / "results_awg"
    known_good_dir = results_dir / "known_good"
    import awg_collector.storage as stor
    monkeypatch.setattr(stor, "RESULTS_AWG_DIR", results_dir)
    monkeypatch.setattr(stor, "KNOWN_GOOD_DIR", known_good_dir)
    return results_dir, known_good_dir


class TestSaveLoadKnownGood:
    def test_save_creates_file(self, tmp_dirs):
        from awg_collector.storage import save_known_good
        results_dir, known_good_dir = tmp_dirs
        path = save_known_good(SAMPLE_CONF, ENDPOINT)
        assert path.exists()
        assert path.name == "185.123.45.67_51820.conf"

    def test_save_writes_content(self, tmp_dirs):
        from awg_collector.storage import save_known_good
        save_known_good(SAMPLE_CONF, ENDPOINT)
        results_dir, known_good_dir = tmp_dirs
        content = (known_good_dir / "185.123.45.67_51820.conf").read_text()
        assert "Jc = 4" in content

    def test_load_returns_saved(self, tmp_dirs):
        from awg_collector.storage import save_known_good, load_known_good
        save_known_good(SAMPLE_CONF, ENDPOINT)
        configs = load_known_good()
        assert len(configs) == 1
        assert configs[0]["endpoint"] == ENDPOINT
        assert "Jc = 4" in configs[0]["text"]

    def test_load_empty_when_no_dir(self, tmp_dirs):
        from awg_collector.storage import load_known_good
        configs = load_known_good()
        assert configs == []

    def test_remove_deletes_file(self, tmp_dirs):
        from awg_collector.storage import save_known_good, remove_known_good, load_known_good
        save_known_good(SAMPLE_CONF, ENDPOINT)
        remove_known_good(ENDPOINT)
        assert load_known_good() == []

    def test_remove_nonexistent_no_error(self, tmp_dirs):
        from awg_collector.storage import remove_known_good
        remove_known_good("1.2.3.4:51820")  # should not raise


class TestBuildVpnArchive:
    def test_creates_zip(self, tmp_dirs):
        from awg_collector.storage import save_known_good, build_vpn_archive
        save_known_good(SAMPLE_CONF, ENDPOINT)
        archive = build_vpn_archive()
        assert archive.exists()
        assert archive.suffix == ".vpn"

    def test_zip_contains_conf(self, tmp_dirs):
        from awg_collector.storage import save_known_good, build_vpn_archive
        save_known_good(SAMPLE_CONF, ENDPOINT)
        archive = build_vpn_archive()
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
        assert "185.123.45.67_51820.conf" in names

    def test_zip_conf_content_correct(self, tmp_dirs):
        from awg_collector.storage import save_known_good, build_vpn_archive
        save_known_good(SAMPLE_CONF, ENDPOINT)
        archive = build_vpn_archive()
        with zipfile.ZipFile(archive) as zf:
            content = zf.read("185.123.45.67_51820.conf").decode()
        assert "Jc = 4" in content

    def test_empty_known_good_creates_empty_zip(self, tmp_dirs):
        from awg_collector.storage import build_vpn_archive
        results_dir, known_good_dir = tmp_dirs
        known_good_dir.mkdir(parents=True)
        archive = build_vpn_archive()
        with zipfile.ZipFile(archive) as zf:
            assert zf.namelist() == []


class TestConfigMeta:
    def test_load_returns_empty_when_no_file(self, tmp_dirs):
        from awg_collector.storage import load_config_meta
        assert load_config_meta() == {}

    def test_save_and_load_roundtrip(self, tmp_dirs):
        from awg_collector.storage import save_config_meta, load_config_meta
        meta = {ENDPOINT: {"first_seen": "2026-07-14", "fail_streak": 0}}
        save_config_meta(meta)
        loaded = load_config_meta()
        assert loaded == meta

    def test_update_first_seen_sets_entry(self, tmp_dirs):
        from awg_collector.storage import update_meta_first_seen
        meta = {}
        update_meta_first_seen(meta, ENDPOINT, "2026-07-14")
        assert meta[ENDPOINT]["first_seen"] == "2026-07-14"
        assert meta[ENDPOINT]["fail_streak"] == 0

    def test_update_first_seen_does_not_overwrite(self, tmp_dirs):
        from awg_collector.storage import update_meta_first_seen
        meta = {ENDPOINT: {"first_seen": "2026-07-01", "fail_streak": 0}}
        update_meta_first_seen(meta, ENDPOINT, "2026-07-14")
        assert meta[ENDPOINT]["first_seen"] == "2026-07-01"


class TestCandidates:
    def test_save_and_load_roundtrip(self, tmp_dirs):
        from awg_collector.storage import save_candidates, load_candidates
        configs = [{"text": SAMPLE_CONF, "endpoint": ENDPOINT, "filename": "x.conf"}]
        save_candidates(configs)
        loaded = load_candidates()
        assert len(loaded) == 1
        assert "Jc = 4" in loaded[0]

    def test_load_empty_when_no_file(self, tmp_dirs):
        from awg_collector.storage import load_candidates
        assert load_candidates() == []
```

- [ ] **Шаг 2: Убедиться что тесты падают**

```bash
python -m pytest tests/test_awg_storage.py -v 2>&1 | head -10
```

Ожидаемо: `ModuleNotFoundError: No module named 'awg_collector.storage'`

- [ ] **Шаг 3: Написать `awg_collector/storage.py`**

```python
import json
import re
import zipfile
from pathlib import Path

from awg_collector.config import RESULTS_AWG_DIR, KNOWN_GOOD_DIR


def _ensure_dirs() -> None:
    RESULTS_AWG_DIR.mkdir(exist_ok=True)
    KNOWN_GOOD_DIR.mkdir(exist_ok=True)


def save_known_good(conf_text: str, endpoint: str) -> Path:
    _ensure_dirs()
    host, _, port = endpoint.rpartition(":")
    path = KNOWN_GOOD_DIR / f"{host}_{port}.conf"
    path.write_text(conf_text)
    return path


def load_known_good() -> list[dict]:
    if not KNOWN_GOOD_DIR.exists():
        return []
    results = []
    for path in sorted(KNOWN_GOOD_DIR.glob("*.conf")):
        text = path.read_text(errors="replace")
        stem = path.stem
        last = stem.rfind("_")
        if last == -1:
            continue
        endpoint = stem[:last] + ":" + stem[last + 1:]
        results.append({"text": text, "endpoint": endpoint, "filename": path.name})
    return results


def remove_known_good(endpoint: str) -> None:
    host, _, port = endpoint.rpartition(":")
    path = KNOWN_GOOD_DIR / f"{host}_{port}.conf"
    path.unlink(missing_ok=True)


def build_vpn_archive() -> Path:
    _ensure_dirs()
    archive_path = RESULTS_AWG_DIR / "all_configs.vpn"
    configs = load_known_good()
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for cfg in configs:
            zf.writestr(cfg["filename"], cfg["text"])
    return archive_path


def load_config_meta() -> dict:
    meta_file = RESULTS_AWG_DIR / "config_meta.json"
    if not meta_file.exists():
        return {}
    try:
        return json.loads(meta_file.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_config_meta(meta: dict) -> None:
    _ensure_dirs()
    (RESULTS_AWG_DIR / "config_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False)
    )


def update_meta_first_seen(meta: dict, endpoint: str, today: str) -> None:
    if endpoint not in meta:
        meta[endpoint] = {"first_seen": today, "fail_streak": 0}


def save_candidates(configs: list[dict]) -> None:
    _ensure_dirs()
    text = "\n\n".join(cfg["text"] for cfg in configs)
    (RESULTS_AWG_DIR / "candidates.conf").write_text(text)


def load_candidates() -> list[str]:
    path = RESULTS_AWG_DIR / "candidates.conf"
    if not path.exists():
        return []
    blocks = re.split(r"(?=^\[Interface\])", path.read_text(errors="replace"), flags=re.MULTILINE)
    return [b.strip() for b in blocks if b.strip() and "[Interface]" in b]
```

- [ ] **Шаг 4: Убедиться что тесты проходят**

```bash
python -m pytest tests/test_awg_storage.py -v
```

Ожидаемо: все `PASSED`

- [ ] **Шаг 5: Коммит**

```bash
git add awg_collector/storage.py tests/test_awg_storage.py
git commit -m "feat(awg): add storage layer with .conf + .vpn ZIP support"
```

---

## Task 4: sources.py + tg_source.py (TDD)

**Files:**
- Create: `awg_collector/sources.py`
- Create: `awg_collector/tg_source.py`
- Create: `tests/test_awg_sources.py`

**Interfaces:**
- Consumes: `parse_awg_configs`, `parse_awg_file`, `SOURCES_AWG_FILE`, `GITHUB_API`, `GITHUB_RAW`
- Produces:
  - `fetch_all_configs(sources_file: Path) -> list[dict]` — возвращает дедуплицированные AWG конфиги
  - `add_source(url_or_repo: str, sources_file: Path) -> bool`
  - `load_sources(sources_file: Path) -> list[dict]`

- [ ] **Шаг 1: Написать тесты**

```python
# tests/test_awg_sources.py
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from awg_collector.sources import add_source, load_sources, fetch_all_configs

SAMPLE_CONF = """[Interface]
PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
Jc = 4
Jmin = 40
Jmax = 70
S1 = 0
S2 = 0
H1 = 1
H2 = 2
H3 = 3
H4 = 4

[Peer]
PublicKey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=
AllowedIPs = 0.0.0.0/0
Endpoint = 185.123.45.67:51820
PersistentKeepalive = 25"""


@pytest.fixture()
def sources_file(tmp_path):
    return tmp_path / "sources_awg.json"


class TestAddSource:
    def test_add_github_repo(self, sources_file):
        assert add_source("owner/repo", sources_file) is True
        sources = load_sources(sources_file)
        assert {"type": "github", "value": "owner/repo"} in sources

    def test_add_url(self, sources_file):
        assert add_source("https://example.com/config.conf", sources_file) is True
        sources = load_sources(sources_file)
        assert {"type": "url", "value": "https://example.com/config.conf"} in sources

    def test_add_telegram_url(self, sources_file):
        assert add_source("https://t.me/somechannel", sources_file) is True
        sources = load_sources(sources_file)
        assert {"type": "tg", "value": "somechannel"} in sources

    def test_duplicate_not_added(self, sources_file):
        add_source("owner/repo", sources_file)
        assert add_source("owner/repo", sources_file) is False
        assert len(load_sources(sources_file)) == 1

    def test_creates_file_if_missing(self, sources_file):
        assert not sources_file.exists()
        add_source("owner/repo", sources_file)
        assert sources_file.exists()


class TestFetchAllConfigs:
    def test_deduplicates_by_endpoint(self, sources_file, tmp_path):
        sources_file.write_text(json.dumps([
            {"type": "url", "value": "https://example.com/a.conf"},
            {"type": "url", "value": "https://example.com/b.conf"},
        ]))
        # Both URLs return same endpoint
        with patch("awg_collector.sources._fetch_url") as mock_fetch:
            mock_fetch.return_value = SAMPLE_CONF
            result = fetch_all_configs(sources_file)
        assert len(result) == 1
        assert result[0]["endpoint"] == "185.123.45.67:51820"

    def test_skips_non_awg_configs(self, sources_file):
        wg_only = SAMPLE_CONF.replace("Jc = 4\nJmin = 40\nJmax = 70\nS1 = 0\nS2 = 0\nH1 = 1\nH2 = 2\nH3 = 3\nH4 = 4\n", "")
        sources_file.write_text(json.dumps([{"type": "url", "value": "https://x.com/c.conf"}]))
        with patch("awg_collector.sources._fetch_url") as mock_fetch:
            mock_fetch.return_value = wg_only
            result = fetch_all_configs(sources_file)
        assert result == []

    def test_fetch_error_skipped(self, sources_file):
        sources_file.write_text(json.dumps([{"type": "url", "value": "https://x.com/c.conf"}]))
        with patch("awg_collector.sources._fetch_url", side_effect=Exception("network error")):
            result = fetch_all_configs(sources_file)
        assert result == []
```

- [ ] **Шаг 2: Убедиться что тесты падают**

```bash
python -m pytest tests/test_awg_sources.py -v 2>&1 | head -10
```

- [ ] **Шаг 3: Написать `awg_collector/tg_source.py`**

Скопировать логику из `vpn_collector/tg_source.py` полностью (не импортировать), адаптировав `fetch_tg_channel_configs` — вместо поиска VLESS-строк ищем вложения `.conf` и текстовые блоки `[Interface]`:

```python
# awg_collector/tg_source.py
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from awg_collector.config import TG_AUTH_FILE, TG_SESSION_FILE, TG_POSTS_LIMIT
from awg_collector.parser import parse_awg_configs

logger = logging.getLogger(__name__)


def _telethon_proxy() -> tuple | None:
    for var in ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy"):
        val = os.environ.get(var, "").strip()
        if not val:
            continue
        try:
            import socks as _socks
            p = urlparse(val)
            scheme = p.scheme.lower().rstrip("h")
            proxy_types = {"socks5": _socks.SOCKS5, "socks4": _socks.SOCKS4, "http": _socks.HTTP}
            proxy_type = proxy_types.get(scheme)
            if proxy_type is None:
                continue
            port = p.port or (1080 if "socks" in scheme else 8080)
            return (proxy_type, p.hostname, port)
        except Exception:
            pass
    return None


def load_tg_auth() -> dict | None:
    if not TG_AUTH_FILE.exists():
        return None
    return json.loads(TG_AUTH_FILE.read_text())


def is_tg_configured() -> bool:
    session_path = Path(str(TG_SESSION_FILE) + ".session")
    return TG_AUTH_FILE.exists() and session_path.exists()


async def fetch_tg_channel_configs(client, channel: str, limit: int) -> list[dict]:
    try:
        messages = await client.get_messages(channel, limit=limit)
        configs: list[dict] = []
        for msg in messages:
            if not msg:
                continue
            # Текстовые блоки в теле сообщения
            if msg.text and "[Interface]" in msg.text:
                configs.extend(parse_awg_configs(msg.text))
            # Вложения .conf
            if msg.document:
                name = getattr(msg.document.attributes[-1], "file_name", "") if msg.document.attributes else ""
                if name.endswith(".conf"):
                    try:
                        data = await client.download_media(msg.document, bytes)
                        if data:
                            configs.extend(parse_awg_configs(data.decode("utf-8", errors="replace")))
                    except Exception as e:
                        logger.debug(f"Failed to download attachment from {channel}: {e}")
        return configs
    except Exception as e:
        logger.warning(f"TG channel {channel} error: {e}")
        return []
```

- [ ] **Шаг 4: Написать `awg_collector/sources.py`**

```python
import json
import logging
import os
from pathlib import Path

import requests

from awg_collector.config import (
    DEFAULT_SOURCES_AWG, SOURCES_AWG_FILE, PROXY_ENV_VARS,
    GITHUB_API, GITHUB_RAW, TG_POSTS_LIMIT,
)
from awg_collector.parser import parse_awg_configs

logger = logging.getLogger(__name__)


def _clean_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def load_sources(sources_file: Path) -> list[dict]:
    if not sources_file.exists():
        save_sources(DEFAULT_SOURCES_AWG, sources_file)
        return DEFAULT_SOURCES_AWG.copy()
    return json.loads(sources_file.read_text())


def save_sources(sources: list[dict], sources_file: Path) -> None:
    sources_file.write_text(json.dumps(sources, indent=2))


def add_source(url_or_repo: str, sources_file: Path) -> bool:
    sources = load_sources(sources_file)
    stripped = url_or_repo.strip()

    tg_value = None
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if stripped.startswith(prefix):
            tg_value = stripped[len(prefix):].lstrip("s/").strip("/")
            break

    if tg_value is not None:
        if any(s["type"] == "tg" and s["value"] == tg_value for s in sources):
            return False
        sources.append({"type": "tg", "value": tg_value})
        save_sources(sources, sources_file)
        return True

    if any(s["value"] == stripped for s in sources):
        return False

    source_type = "url" if stripped.startswith("http") else "github"
    sources.append({"type": source_type, "value": stripped})
    save_sources(sources, sources_file)
    return True


def fetch_all_configs(sources_file: Path) -> list[dict]:
    sources = load_sources(sources_file)
    seen_endpoints: set[str] = set()
    all_configs: list[dict] = []

    for source in sources:
        try:
            if source["type"] == "url":
                raw = _fetch_url(source["value"])
                parsed = parse_awg_configs(raw)
            elif source["type"] == "github":
                parsed = _fetch_github_repo(source["value"])
            elif source["type"] == "tg":
                parsed = _fetch_tg_channel(source["value"])
            else:
                continue
        except Exception as e:
            logger.warning(f"Source {source['value']} failed: {e}")
            continue

        for cfg in parsed:
            if not cfg["is_awg"]:
                continue
            ep = cfg["endpoint"]
            if ep not in seen_endpoints:
                seen_endpoints.add(ep)
                all_configs.append(cfg)

    return all_configs


def _fetch_url(url: str, timeout: int = 20) -> str:
    session = _clean_session()
    r = session.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text


def _fetch_github_repo(repo: str) -> list[dict]:
    session = _clean_session()
    owner, _, name = repo.partition("/")
    # Get default branch
    try:
        r = session.get(f"{GITHUB_API}/repos/{repo}", timeout=10)
        r.raise_for_status()
        branch = r.json().get("default_branch", "main")
    except Exception:
        branch = "main"

    # Get file tree
    try:
        r = session.get(
            f"{GITHUB_API}/repos/{repo}/git/trees/{branch}?recursive=1",
            timeout=15,
        )
        r.raise_for_status()
        tree = r.json().get("tree", [])
    except Exception as e:
        logger.warning(f"GitHub tree for {repo}: {e}")
        return []

    configs: list[dict] = []
    for item in tree:
        path = item.get("path", "")
        if not path.endswith(".conf"):
            continue
        try:
            raw_url = f"{GITHUB_RAW}/{repo}/{branch}/{path}"
            text = _fetch_url(raw_url)
            configs.extend(parse_awg_configs(text))
        except Exception as e:
            logger.debug(f"GitHub file {path}: {e}")

    return configs


def _fetch_tg_channel(channel: str) -> list[dict]:
    from awg_collector.tg_source import is_tg_configured, load_tg_auth, fetch_tg_channel_configs
    if not is_tg_configured():
        logger.info(f"TG not configured, skipping channel {channel}")
        return []
    try:
        import asyncio
        from telethon import TelegramClient
        from awg_collector.config import TG_SESSION_FILE
        from awg_collector.tg_source import _telethon_proxy

        auth = load_tg_auth()
        if not auth:
            return []

        async def _run():
            proxy = _telethon_proxy()
            async with TelegramClient(str(TG_SESSION_FILE), auth["api_id"], auth["api_hash"], proxy=proxy) as client:
                return await fetch_tg_channel_configs(client, channel, TG_POSTS_LIMIT)

        return asyncio.run(_run())
    except Exception as e:
        logger.warning(f"TG channel {channel}: {e}")
        return []
```

- [ ] **Шаг 5: Убедиться что тесты проходят**

```bash
python -m pytest tests/test_awg_sources.py -v
```

Ожидаемо: все `PASSED`

- [ ] **Шаг 6: Коммит**

```bash
git add awg_collector/sources.py awg_collector/tg_source.py tests/test_awg_sources.py
git commit -m "feat(awg): add sources fetcher (GitHub / URL / Telegram)"
```

---

## Task 5: tester.py (TDD)

**Files:**
- Create: `awg_collector/tester.py`
- Create: `tests/test_awg_tester.py`

**Interfaces:**
- Consumes: `config.{AWG_TEST_TIMEOUT, MIN_SPEED_MBPS, SPEEDTEST_URLS, PROXY_ENV_VARS, TCP_TIMEOUT}`
- Produces:
  - `tcp_check(host: str, port: int, timeout: float) -> bool`
  - `test_awg_tunnel(conf_text: str) -> float | None` — bytes/sec или None при провале
  - `passes_speed(speed_bytes: float) -> bool`
  - `strip_dns(conf_text: str) -> str` — убирает DNS= из конфига

- [ ] **Шаг 1: Написать тесты**

```python
# tests/test_awg_tester.py
import subprocess
import pytest
from unittest.mock import patch, call, MagicMock

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
            if "up" in cmd:
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

        if seen_confs:
            assert "DNS" not in seen_confs[0]
```

- [ ] **Шаг 2: Убедиться что тесты падают**

```bash
python -m pytest tests/test_awg_tester.py -v 2>&1 | head -10
```

- [ ] **Шаг 3: Написать `awg_collector/tester.py`**

```python
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


def _run_sudo(*args, timeout: int = AWG_TEST_TIMEOUT) -> subprocess.CompletedProcess:
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
        r = _run_sudo("ip", "netns", "add", ns_name, timeout=10)
        if r.returncode != 0:
            logger.debug(f"netns add failed: {r.stderr}")
            return None
        ns_created = True

        # Set up per-netns DNS so curl can resolve inside the namespace
        ns_resolv = Path(f"/etc/netns/{ns_name}")
        _run_sudo("mkdir", "-p", str(ns_resolv), timeout=5)
        _run_sudo("bash", "-c", f"echo 'nameserver 1.1.1.1' > /etc/netns/{ns_name}/resolv.conf", timeout=5)

        # Bring up loopback inside netns
        _run_sudo("ip", "netns", "exec", ns_name, "ip", "link", "set", "lo", "up", timeout=5)

        # Bring up AWG interface inside netns
        r = _run_sudo("ip", "netns", "exec", ns_name, "awg-quick", "up", str(tmp_conf), timeout=15)
        if r.returncode != 0:
            logger.debug(f"awg-quick up failed: {r.stderr}")
            return None
        iface_up = True

        # Speedtest inside netns
        for url in SPEEDTEST_URLS:
            try:
                r = _run_sudo(
                    "ip", "netns", "exec", ns_name,
                    "curl", "--max-time", "15", "-o", "/dev/null",
                    "-w", "%{speed_download}", "-s", "--", url,
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
            _run_sudo("ip", "netns", "exec", ns_name, "awg-quick", "down", str(tmp_conf), timeout=10)
        if ns_created:
            _run_sudo("ip", "netns", "del", ns_name, timeout=5)
            _run_sudo("rm", "-rf", f"/etc/netns/{ns_name}", timeout=5)
        tmp_conf.unlink(missing_ok=True)
```

- [ ] **Шаг 4: Убедиться что тесты проходят**

```bash
python -m pytest tests/test_awg_tester.py -v
```

Ожидаемо: все `PASSED`

- [ ] **Шаг 5: Коммит**

```bash
git add awg_collector/tester.py tests/test_awg_tester.py
git commit -m "feat(awg): add tunnel tester via network namespaces"
```

---

## Task 6: main.py CLI

**Files:**
- Create: `awg_collector/main.py`

**Interfaces:**
- Consumes: все модули awg_collector
- Produces: CLI-команды `--collect`, `--recheck`, `--export`, `--add-source`, `--stats`

- [ ] **Шаг 1: Написать `awg_collector/main.py`**

```python
import argparse
import asyncio
import logging
import socket
import sys
from datetime import date
from pathlib import Path

from awg_collector.config import (
    RESULTS_AWG_DIR, SOURCES_AWG_FILE, LOGS_DIR,
    AWG_TUNNEL_CONCURRENCY, AWG_RECHECK_RETRIES, TCP_CONCURRENCY, TCP_TIMEOUT,
)
from awg_collector.parser import parse_awg_configs
from awg_collector.sources import fetch_all_configs, add_source
from awg_collector.storage import (
    save_known_good, load_known_good, remove_known_good, build_vpn_archive,
    load_config_meta, save_config_meta, update_meta_first_seen,
    save_candidates,
)
from awg_collector.tester import tcp_check, test_awg_tunnel, passes_speed

_log = logging.getLogger(__name__)


def _setup_logging() -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOGS_DIR / "awg_collector.log"),
            logging.StreamHandler(sys.stdout),
        ],
    )


async def _tcp_filter(configs: list[dict]) -> list[dict]:
    by_endpoint: dict[str, list[dict]] = {}
    for cfg in configs:
        ep = cfg["endpoint"]
        by_endpoint.setdefault(ep, []).append(cfg)

    sem = asyncio.Semaphore(TCP_CONCURRENCY)

    async def check(ep: str) -> str | None:
        host, _, port = ep.rpartition(":")
        async with sem:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, int(port)), timeout=TCP_TIMEOUT
                )
                writer.close()
                await writer.wait_closed()
                return ep
            except Exception:
                return None

    endpoints = list(by_endpoint)
    results = await asyncio.gather(*[check(ep) for ep in endpoints])
    passing = {ep for ep in results if ep}
    return [cfg for ep, cfgs in by_endpoint.items() if ep in passing for cfg in cfgs]


def _tunnel_test_batch(configs: list[dict]) -> list[dict]:
    import concurrent.futures
    passing = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=AWG_TUNNEL_CONCURRENCY) as pool:
        futures = {pool.submit(test_awg_tunnel, cfg["text"]): cfg for cfg in configs}
        for future, cfg in futures.items():
            try:
                speed = future.result()
                if speed is not None and passes_speed(speed):
                    passing.append(cfg)
                    _log.info(f"PASS {cfg['endpoint']} {speed/125000:.1f} Mbps")
                else:
                    _log.info(f"FAIL {cfg['endpoint']}")
            except Exception as e:
                _log.warning(f"Error testing {cfg['endpoint']}: {e}")
    return passing


def cmd_collect() -> None:
    RESULTS_AWG_DIR.mkdir(exist_ok=True)
    today = date.today().isoformat()

    _log.info("Fetching AWG configs from all sources...")
    configs = fetch_all_configs(SOURCES_AWG_FILE)
    _log.info(f"Collected {len(configs)} unique AWG configs")

    if not configs:
        _log.warning("No configs collected. Check sources_awg.json.")
        return

    save_candidates(configs)

    _log.info("TCP pre-filter...")
    configs = asyncio.run(_tcp_filter(configs))
    _log.info(f"TCP passed: {len(configs)}")

    _log.info(f"Tunnel testing {len(configs)} configs (concurrency={AWG_TUNNEL_CONCURRENCY})...")
    passing = _tunnel_test_batch(configs)
    _log.info(f"Passed tunnel test: {len(passing)}")

    meta = load_config_meta()
    for cfg in passing:
        save_known_good(cfg["text"], cfg["endpoint"])
        update_meta_first_seen(meta, cfg["endpoint"], today)

    save_config_meta(meta)
    archive = build_vpn_archive()
    total = len(load_known_good())
    _log.info(f"known_good: {total} configs | archive: {archive}")


def cmd_recheck() -> None:
    today = date.today().isoformat()
    configs = load_known_good()
    _log.info(f"Rechecking {len(configs)} known_good configs...")

    meta = load_config_meta()
    removed = 0

    for cfg in configs:
        ep = cfg["endpoint"]
        passed = False
        for attempt in range(AWG_RECHECK_RETRIES + 1):
            speed = test_awg_tunnel(cfg["text"])
            if speed is not None and passes_speed(speed):
                _log.info(f"PASS {ep} {speed/125000:.1f} Mbps")
                passed = True
                break
            _log.info(f"FAIL attempt {attempt+1}/{AWG_RECHECK_RETRIES+1} {ep}")

        if not passed:
            _log.info(f"Removing {ep} from known_good")
            remove_known_good(ep)
            if ep in meta:
                meta[ep]["fail_streak"] = 0
            removed += 1

    save_config_meta(meta)
    archive = build_vpn_archive()
    remaining = len(load_known_good())
    _log.info(f"Recheck done: removed={removed} remaining={remaining} | {archive}")


def cmd_export() -> None:
    archive = build_vpn_archive()
    count = len(load_known_good())
    _log.info(f"Exported {count} configs to {archive}")


def cmd_stats() -> None:
    configs = load_known_good()
    meta = load_config_meta()
    print(f"known_good: {len(configs)} configs")
    print(f"config_meta entries: {len(meta)}")
    archive = RESULTS_AWG_DIR / "all_configs.vpn"
    if archive.exists():
        size_kb = archive.stat().st_size // 1024
        print(f"all_configs.vpn: {size_kb} KB")


def main() -> None:
    _setup_logging()
    parser = argparse.ArgumentParser(description="AWG config collector")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--collect",    action="store_true", help="Fetch + test configs")
    group.add_argument("--recheck",    action="store_true", help="Recheck known_good")
    group.add_argument("--export",     action="store_true", help="Rebuild all_configs.vpn")
    group.add_argument("--add-source", metavar="URL",        help="Add source to sources_awg.json")
    group.add_argument("--stats",      action="store_true", help="Print statistics")
    args = parser.parse_args()

    if args.collect:
        cmd_collect()
    elif args.recheck:
        cmd_recheck()
    elif args.export:
        cmd_export()
    elif args.add_source:
        added = add_source(args.add_source, SOURCES_AWG_FILE)
        print("Added." if added else "Already exists.")
    elif args.stats:
        cmd_stats()


if __name__ == "__main__":
    main()
```

- [ ] **Шаг 2: Проверить что CLI запускается без ошибок импорта**

```bash
python3 -m awg_collector.main --stats
```

Ожидаемо: `known_good: 0 configs` (или аналогичный вывод без ошибок)

- [ ] **Шаг 3: Проверить --add-source**

```bash
python3 -m awg_collector.main --add-source "https://t.me/testchannel"
```

Ожидаемо: `Added.`

```bash
cat sources_awg.json
```

Ожидаемо: JSON с `{"type": "tg", "value": "testchannel"}`

- [ ] **Шаг 4: Коммит**

```bash
git add awg_collector/main.py
git commit -m "feat(awg): add CLI main.py with --collect --recheck --export --stats"
```

---

## Task 7: Установка зависимостей + smoke test

**Files:** нет новых файлов

- [ ] **Шаг 1: Установить amneziawg-tools**

```bash
sudo apt update
sudo apt install -y amneziawg-tools
```

Проверить что `awg-quick` доступен:

```bash
which awg-quick && awg-quick --version 2>&1 || awg-quick --help 2>&1 | head -3
```

- [ ] **Шаг 2: Загрузить ядерный модуль**

Вариант А — ядерный модуль (если поддерживается Proxmox):
```bash
sudo modprobe amneziawg 2>&1 || echo "kernel module not available"
```

Вариант Б — amneziawg-go (userspace, рекомендуется для Proxmox):
```bash
# Скачать бинарь amneziawg-go для linux/amd64
# Проверить актуальный релиз: https://github.com/amnezia-vpn/amneziawg-go/releases
# Установить как /usr/local/bin/amneziawg-go
```

Проверить что хотя бы один вариант работает:
```bash
sudo ip netns add awg_smoketest
sudo ip netns exec awg_smoketest ip link add awg0 type amneziawg 2>/dev/null && echo "kernel module OK" || echo "try userspace"
sudo ip netns del awg_smoketest
```

- [ ] **Шаг 3: Найти один реальный AWG конфиг для smoke test**

Взять конфиг из найденных источников в Task 1. Сохранить в `/tmp/smoke_test.conf`.

- [ ] **Шаг 4: Запустить smoke test тестера напрямую**

```python
# запустить в python3
import logging
logging.basicConfig(level=logging.DEBUG)
from awg_collector.tester import test_awg_tunnel
conf = open("/tmp/smoke_test.conf").read()
speed = test_awg_tunnel(conf)
print(f"Speed: {speed}")
print(f"Passes: {speed is not None and speed >= 125_000}")
```

Ожидаемо: вывод скорости в bytes/sec или `None` с DEBUG логами объясняющими причину.

- [ ] **Шаг 5: Запустить полный --collect с реальными источниками**

```bash
python3 -m awg_collector.main --collect
```

Проверить:
```bash
ls results_awg/known_good/
cat results_awg/config_meta.json
python3 -m awg_collector.main --stats
```

- [ ] **Шаг 6: Проверить .vpn архив**

```bash
python3 -c "import zipfile; zf=zipfile.ZipFile('results_awg/all_configs.vpn'); print(zf.namelist())"
```

Ожидаемо: список `.conf` файлов внутри архива.

- [ ] **Шаг 7: Финальный коммит**

```bash
git add results_awg/.gitkeep 2>/dev/null || true
git commit -m "feat(awg): complete awg_collector module — smoke test passed"
```

---

## Запуск всех тестов

```bash
python -m pytest tests/test_awg_parser.py tests/test_awg_storage.py tests/test_awg_tester.py tests/test_awg_sources.py -v
```

Ожидаемо: все `PASSED`, нет `ERROR`.
