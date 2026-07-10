# Privileged Servers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить автоматически обслуживаемый список привилегированных VPN-серверов (`privileged.txt`), куда попадают серверы, стабильно работающие >7 дней, и откуда удаляются после подтверждённого падения.

**Architecture:** Метаданные по host:port хранятся в `config_meta.json` (first_seen + fail_streak). При `--test` фиксируется first_seen. При `--recheck` обновляется privileged.txt: серверы старше 7 дней продвигаются, упавшие перепроверяются N раз и удаляются только при подтверждённом падении. Cron запускает `--recheck --update-known-good` каждые 3 дня.

**Tech Stack:** Python 3.11+, стандартная библиотека (json, datetime, pathlib), sing-box (уже используется), crontab

## Global Constraints

- Все tunnel-тесты запускают sing-box с `clean_env` (без HTTP_PROXY/HTTPS_PROXY/ALL_PROXY) — прямое соединение без системного прокси
- Идентификация сервера: строка `"host:port"` (не полный конфиг)
- `privileged.txt` содержит полные конфиг-строки (готовые для Throne), формат идентичен `known_good.txt`
- Константы: `PRIVILEGED_MIN_DAYS = 7`, `PRIVILEGED_RECHECK_RETRIES = 2`
- Тесты используют `tmp_path` fixture, никаких сетевых вызовов в unit-тестах
- Запуск тестов: `pytest tests/ -v`

---

## File Map

| Файл | Действие | Ответственность |
|------|----------|-----------------|
| `vpn_collector/config.py` | Modify | Добавить `PRIVILEGED_MIN_DAYS`, `PRIVILEGED_RECHECK_RETRIES` |
| `vpn_collector/storage.py` | Modify | Новые функции для config_meta и privileged |
| `vpn_collector/main.py` | Modify | Вызовы новых функций в cmd_test и cmd_recheck; флаг --update-known-good |
| `tests/test_storage.py` | Modify | Тесты новых функций storage |
| `tests/test_main_privileged.py` | Create | Интеграционные тесты логики продвижения/удаления |
| `scripts/install_cron.sh` | Create | Idempotent установка cron-задачи |

---

### Task 1: Константы и storage-функции для config_meta и privileged

**Files:**
- Modify: `vpn_collector/config.py`
- Modify: `vpn_collector/storage.py`
- Modify: `tests/test_storage.py`

**Interfaces:**
- Produces:
  - `load_config_meta(results_dir: Path) -> dict`  
    Возвращает `{"host:port": {"first_seen": "YYYY-MM-DD", "fail_streak": int}}`; пустой dict если файл не существует
  - `save_config_meta(results_dir: Path, meta: dict) -> None`  
    Атомарно перезаписывает `results/config_meta.json`
  - `update_meta_first_seen(meta: dict, host_port: str, today: str) -> None`  
    Если `host_port` нет в meta — добавляет запись с `first_seen=today, fail_streak=0`. Мутирует dict на месте.
  - `load_privileged(results_dir: Path) -> list[str]`  
    Возвращает список конфиг-строк из `privileged.txt` (без комментариев); пустой список если файл не существует
  - `save_privileged(results_dir: Path, configs: list[str]) -> None`  
    Перезаписывает `privileged.txt` с заголовком `# Updated: TIMESTAMP | Total: N`

- [ ] **Шаг 1.1: Добавить константы в config.py**

В конец файла `vpn_collector/config.py` добавить:

```python
PRIVILEGED_MIN_DAYS = 7
PRIVILEGED_RECHECK_RETRIES = 2
```

- [ ] **Шаг 1.2: Написать падающие тесты для config_meta**

Добавить в `tests/test_storage.py`:

```python
import json
from vpn_collector.storage import (
    load_config_meta, save_config_meta, update_meta_first_seen,
    load_privileged, save_privileged,
)


class TestConfigMeta:
    def test_load_missing_returns_empty(self, results_dir):
        assert load_config_meta(results_dir) == {}

    def test_roundtrip(self, results_dir):
        meta = {"1.2.3.4:443": {"first_seen": "2026-07-01", "fail_streak": 0}}
        save_config_meta(results_dir, meta)
        assert load_config_meta(results_dir) == meta

    def test_update_first_seen_new_entry(self, results_dir):
        meta = {}
        update_meta_first_seen(meta, "1.2.3.4:443", "2026-07-10")
        assert meta["1.2.3.4:443"]["first_seen"] == "2026-07-10"
        assert meta["1.2.3.4:443"]["fail_streak"] == 0

    def test_update_first_seen_does_not_overwrite(self, results_dir):
        meta = {"1.2.3.4:443": {"first_seen": "2026-07-01", "fail_streak": 0}}
        update_meta_first_seen(meta, "1.2.3.4:443", "2026-07-10")
        assert meta["1.2.3.4:443"]["first_seen"] == "2026-07-01"


class TestPrivileged:
    def test_load_missing_returns_empty(self, results_dir):
        assert load_privileged(results_dir) == []

    def test_roundtrip(self, results_dir):
        configs = [VLESS1, VLESS2]
        save_privileged(results_dir, configs)
        assert load_privileged(results_dir) == configs

    def test_save_writes_header(self, results_dir):
        save_privileged(results_dir, [VLESS1])
        text = (results_dir / "privileged.txt").read_text()
        assert text.startswith("# Updated:")
        assert "Total: 1" in text

    def test_skips_comment_lines_on_load(self, results_dir):
        (results_dir / "privileged.txt").write_text(
            f"# Updated: 2026-07-10 | Total: 1\n{VLESS1}\n"
        )
        result = load_privileged(results_dir)
        assert result == [VLESS1]

    def test_save_empty_list(self, results_dir):
        save_privileged(results_dir, [])
        assert load_privileged(results_dir) == []
        assert "Total: 0" in (results_dir / "privileged.txt").read_text()
```

- [ ] **Шаг 1.3: Запустить тесты — убедиться что падают**

```bash
pytest tests/test_storage.py::TestConfigMeta tests/test_storage.py::TestPrivileged -v
```

Ожидаемый результат: `ImportError` или `FAILED` (функции не существуют).

- [ ] **Шаг 1.4: Реализовать функции в storage.py**

Добавить в конец `vpn_collector/storage.py`:

```python
import json


def load_config_meta(results_dir: Path) -> dict:
    meta_file = results_dir / "config_meta.json"
    if not meta_file.exists():
        return {}
    try:
        return json.loads(meta_file.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_config_meta(results_dir: Path, meta: dict) -> None:
    (results_dir / "config_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False)
    )


def update_meta_first_seen(meta: dict, host_port: str, today: str) -> None:
    if host_port not in meta:
        meta[host_port] = {"first_seen": today, "fail_streak": 0}


def load_privileged(results_dir: Path) -> list[str]:
    priv_file = results_dir / "privileged.txt"
    if not priv_file.exists():
        return []
    result = []
    for line in priv_file.read_text(errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and is_vpn_line(line):
            result.append(line)
    return result


def save_privileged(results_dir: Path, configs: list[str]) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = f"# Updated: {timestamp} | Total: {len(configs)}"
    with open(results_dir / "privileged.txt", "w") as f:
        f.write(header + "\n")
        for line in configs:
            f.write(line + "\n")
```

Убедиться что `import json` и `from datetime import date, datetime` уже есть в начале файла (datetime — да, json — нет, нужно добавить).

- [ ] **Шаг 1.5: Запустить тесты — убедиться что проходят**

```bash
pytest tests/test_storage.py -v
```

Ожидаемый результат: все тесты `PASSED`.

- [ ] **Шаг 1.6: Коммит**

```bash
git add vpn_collector/config.py vpn_collector/storage.py tests/test_storage.py
git commit -m "feat: add config_meta and privileged storage functions"
```

---

### Task 2: Обновление cmd_test — фиксация first_seen

**Files:**
- Modify: `vpn_collector/main.py`
- Create: `tests/test_main_privileged.py`

**Interfaces:**
- Consumes:
  - `load_config_meta(results_dir: Path) -> dict` (Task 1)
  - `save_config_meta(results_dir: Path, meta: dict) -> None` (Task 1)
  - `update_meta_first_seen(meta: dict, host_port: str, today: str) -> None` (Task 1)
  - `extract_host_port(config: str) -> tuple | None` (существующая)
- Produces: `cmd_test()` обновляет `config_meta.json` при каждом сохранённом конфиге

- [ ] **Шаг 2.1: Написать падающий тест**

Создать `tests/test_main_privileged.py`:

```python
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import date

VLESS1 = "vless://uuid1@1.2.3.4:443?type=tcp#Server1"
VLESS2 = "vless://uuid2@5.6.7.8:8080?type=tcp#Server2"


@pytest.fixture
def results_dir(tmp_path):
    d = tmp_path / "results"
    d.mkdir()
    return d


class TestCmdTestUpdatesFirstSeen:
    def test_first_seen_written_on_pass(self, results_dir, tmp_path):
        """После успешного tunnel-теста first_seen должен быть записан в config_meta.json."""
        candidates_file = results_dir / "candidates.txt"
        candidates_file.write_text(f"{VLESS1}\n")

        with (
            patch("vpn_collector.main.RESULTS_DIR", results_dir),
            patch("vpn_collector.main.find_singbox", return_value="/fake/singbox"),
            patch("vpn_collector.main.tunnel_filter", return_value=[VLESS1]),
            patch("vpn_collector.main.load_known_hosts", return_value=set()),
            patch("vpn_collector.main.rotate_run_files"),
            patch("vpn_collector.main.trim_candidates", return_value=0),
            patch("vpn_collector.main.load_known_good_hp", return_value=set()),
            patch("vpn_collector.main.save_config"),
        ):
            from vpn_collector.main import cmd_test
            cmd_test()

        meta_file = results_dir / "config_meta.json"
        assert meta_file.exists()
        meta = json.loads(meta_file.read_text())
        assert "1.2.3.4:443" in meta
        assert meta["1.2.3.4:443"]["first_seen"] == date.today().isoformat()
        assert meta["1.2.3.4:443"]["fail_streak"] == 0

    def test_existing_first_seen_not_overwritten(self, results_dir):
        """Повторный тест не должен перезаписывать first_seen."""
        candidates_file = results_dir / "candidates.txt"
        candidates_file.write_text(f"{VLESS1}\n")
        meta_initial = {"1.2.3.4:443": {"first_seen": "2026-06-01", "fail_streak": 0}}
        (results_dir / "config_meta.json").write_text(json.dumps(meta_initial))

        with (
            patch("vpn_collector.main.RESULTS_DIR", results_dir),
            patch("vpn_collector.main.find_singbox", return_value="/fake/singbox"),
            patch("vpn_collector.main.tunnel_filter", return_value=[VLESS1]),
            patch("vpn_collector.main.load_known_hosts", return_value=set()),
            patch("vpn_collector.main.rotate_run_files"),
            patch("vpn_collector.main.trim_candidates", return_value=0),
            patch("vpn_collector.main.load_known_good_hp", return_value=set()),
            patch("vpn_collector.main.save_config"),
        ):
            from vpn_collector.main import cmd_test
            cmd_test()

        meta = json.loads((results_dir / "config_meta.json").read_text())
        assert meta["1.2.3.4:443"]["first_seen"] == "2026-06-01"
```

- [ ] **Шаг 2.2: Запустить тест — убедиться что падает**

```bash
pytest tests/test_main_privileged.py::TestCmdTestUpdatesFirstSeen -v
```

Ожидаемый результат: `FAILED` (config_meta.json не создаётся).

- [ ] **Шаг 2.3: Обновить cmd_test в main.py**

В `vpn_collector/main.py` добавить импорты:

```python
from vpn_collector.storage import (
    load_known_hosts, load_known_good_hp, load_known_good_configs,
    rewrite_known_good, load_tcp_cache, update_tcp_cache,
    is_duplicate, save_config, rotate_run_files, trim_candidates, get_stats,
    load_config_meta, save_config_meta, update_meta_first_seen,
    load_privileged, save_privileged,
)
```

Заменить `cmd_test()` — добавить загрузку/сохранение meta вокруг tunnel_filter:

```python
def cmd_test() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    candidates_file = RESULTS_DIR / "candidates.txt"
    if not candidates_file.exists():
        print("No candidates.txt found. Run --collect first.")
        sys.exit(1)

    singbox_path = find_singbox()
    if not singbox_path:
        print("sing-box binary not found. Searched:")
        for p in SINGBOX_SEARCH_PATHS:
            print(f"  {p}")
        sys.exit(1)
    _log.info(f"Using sing-box: {singbox_path}")

    candidates = [line for line in candidates_file.read_text().splitlines() if line.strip()]
    known_hosts = load_known_hosts(RESULTS_DIR)
    new_candidates = [c for c in candidates if not is_duplicate(c, known_hosts)]
    _log.info(f"Candidates: {len(candidates)} | Already verified: {len(candidates) - len(new_candidates)} | To test: {len(new_candidates)}")

    run_date = date.today().isoformat()
    meta = load_config_meta(RESULTS_DIR)
    passed = [0]

    def save_immediately(config: str) -> None:
        save_config(config, RESULTS_DIR, known_hosts, run_date=run_date)
        passed[0] += 1
        _log.info(f"Saved: {config[:80]}...")
        hp = extract_host_port(config)
        if hp:
            update_meta_first_seen(meta, f"{hp[0]}:{hp[1]}", run_date)

    asyncio.run(tunnel_filter(new_candidates, singbox_path, on_pass=save_immediately))
    save_config_meta(RESULTS_DIR, meta)
    rotate_run_files(RESULTS_DIR, MAX_RUN_FILES)
    _log.info(f"Done: {passed[0]} new configs saved → results/run_{run_date}.txt")

    if passed[0] > 0:
        removed = trim_candidates(candidates_file, load_known_good_hp(RESULTS_DIR))
        _log.info(f"Trimmed candidates.txt: removed {removed} now-verified configs")
```

- [ ] **Шаг 2.4: Запустить тест — убедиться что проходит**

```bash
pytest tests/test_main_privileged.py::TestCmdTestUpdatesFirstSeen -v
```

Ожидаемый результат: `PASSED`.

- [ ] **Шаг 2.5: Убедиться что старые тесты не сломались**

```bash
pytest tests/ -v
```

Ожидаемый результат: все тесты `PASSED`.

- [ ] **Шаг 2.6: Коммит**

```bash
git add vpn_collector/main.py tests/test_main_privileged.py
git commit -m "feat: record first_seen in config_meta on tunnel test pass"
```

---

### Task 3: Логика обновления privileged при recheck

**Files:**
- Modify: `vpn_collector/main.py`
- Modify: `tests/test_main_privileged.py`

**Interfaces:**
- Consumes:
  - `load_config_meta`, `save_config_meta` (Task 1)
  - `load_privileged`, `save_privileged` (Task 1)
  - `extract_host_port` (существующая)
  - `test_config_tunnel` из `vpn_collector.tester` (существующая)
  - `PRIVILEGED_MIN_DAYS`, `PRIVILEGED_RECHECK_RETRIES` из `config` (Task 1)
- Produces:
  - Внутренняя функция `_update_privileged(results_dir, survivors, dead_configs, singbox_path, meta)` 
  - `cmd_recheck(update_known_good: bool = False)` — обновлённая версия

- [ ] **Шаг 3.1: Написать падающие тесты для _update_privileged**

Добавить в `tests/test_main_privileged.py`:

```python
from vpn_collector.main import _update_privileged
from vpn_collector.storage import load_privileged, save_privileged, load_config_meta, save_config_meta


class TestUpdatePrivileged:
    def test_promotes_old_server(self, results_dir):
        """Сервер с first_seen >7 дней назад и прошедший recheck → в privileged."""
        meta = {"1.2.3.4:443": {"first_seen": "2026-07-01", "fail_streak": 0}}
        save_config_meta(results_dir, meta)

        with patch("vpn_collector.main.PRIVILEGED_MIN_DAYS", 7):
            _update_privileged(
                results_dir=results_dir,
                survivors=[VLESS1],
                dead_configs=[],
                singbox_path="/fake/singbox",
                meta=meta,
                today="2026-07-10",
            )

        assert VLESS1 in load_privileged(results_dir)

    def test_does_not_promote_new_server(self, results_dir):
        """Сервер с first_seen <7 дней назад не попадает в privileged."""
        meta = {"1.2.3.4:443": {"first_seen": "2026-07-09", "fail_streak": 0}}
        save_config_meta(results_dir, meta)

        _update_privileged(
            results_dir=results_dir,
            survivors=[VLESS1],
            dead_configs=[],
            singbox_path="/fake/singbox",
            meta=meta,
            today="2026-07-10",
        )

        assert VLESS1 not in load_privileged(results_dir)

    def test_removes_dead_after_retries(self, results_dir):
        """Сервер в privileged, не прошедший recheck и повторные проверки → удалить."""
        save_privileged(results_dir, [VLESS1])
        meta = {"1.2.3.4:443": {"first_seen": "2026-07-01", "fail_streak": 0}}
        save_config_meta(results_dir, meta)

        with (
            patch("vpn_collector.main.PRIVILEGED_RECHECK_RETRIES", 2),
            patch("vpn_collector.main.test_config_tunnel", return_value=None),
            patch("vpn_collector.main.find_free_socks_port", return_value=15000),
        ):
            _update_privileged(
                results_dir=results_dir,
                survivors=[],
                dead_configs=[VLESS1],
                singbox_path="/fake/singbox",
                meta=meta,
                today="2026-07-10",
            )

        assert VLESS1 not in load_privileged(results_dir)

    def test_keeps_privileged_if_retry_passes(self, results_dir):
        """Сервер упал в recheck, но прошёл повторную проверку → остаётся в privileged."""
        save_privileged(results_dir, [VLESS1])
        meta = {"1.2.3.4:443": {"first_seen": "2026-07-01", "fail_streak": 0}}
        save_config_meta(results_dir, meta)

        with (
            patch("vpn_collector.main.PRIVILEGED_RECHECK_RETRIES", 2),
            patch("vpn_collector.main.test_config_tunnel", return_value=VLESS1),
            patch("vpn_collector.main.find_free_socks_port", return_value=15000),
        ):
            _update_privileged(
                results_dir=results_dir,
                survivors=[],
                dead_configs=[VLESS1],
                singbox_path="/fake/singbox",
                meta=meta,
                today="2026-07-10",
            )

        assert VLESS1 in load_privileged(results_dir)
        assert meta["1.2.3.4:443"]["fail_streak"] == 0

    def test_does_not_add_duplicate_to_privileged(self, results_dir):
        """Повторный вызов не дублирует запись в privileged."""
        save_privileged(results_dir, [VLESS1])
        meta = {"1.2.3.4:443": {"first_seen": "2026-07-01", "fail_streak": 0}}
        save_config_meta(results_dir, meta)

        _update_privileged(
            results_dir=results_dir,
            survivors=[VLESS1],
            dead_configs=[],
            singbox_path="/fake/singbox",
            meta=meta,
            today="2026-07-10",
        )

        assert load_privileged(results_dir).count(VLESS1) == 1
```

- [ ] **Шаг 3.2: Запустить тесты — убедиться что падают**

```bash
pytest tests/test_main_privileged.py::TestUpdatePrivileged -v
```

Ожидаемый результат: `ImportError` или `FAILED`.

- [ ] **Шаг 3.3: Реализовать вспомогательную функцию find_free_socks_port в main.py**

Добавить перед `cmd_recheck` в `vpn_collector/main.py`:

```python
import random as _random

def find_free_socks_port() -> int:
    from vpn_collector.config import SOCKS_PORT_RANGE
    return _random.randint(*SOCKS_PORT_RANGE)
```

- [ ] **Шаг 3.4: Реализовать _update_privileged в main.py**

Добавить перед `cmd_recheck` в `vpn_collector/main.py`:

```python
from vpn_collector.config import PRIVILEGED_MIN_DAYS, PRIVILEGED_RECHECK_RETRIES
from vpn_collector.tester import test_config_tunnel
from datetime import date as _date


def _update_privileged(
    results_dir: Path,
    survivors: list[str],
    dead_configs: list[str],
    singbox_path: str,
    meta: dict,
    today: str,
) -> None:
    from datetime import date as _date2
    privileged = load_privileged(results_dir)
    privileged_hp = set()
    for cfg in privileged:
        hp = extract_host_port(cfg)
        if hp:
            privileged_hp.add(f"{hp[0]}:{hp[1]}")

    # Продвигаем серверы, стабильно работающие >= PRIVILEGED_MIN_DAYS дней
    for cfg in survivors:
        hp = extract_host_port(cfg)
        if not hp:
            continue
        key = f"{hp[0]}:{hp[1]}"
        entry = meta.get(key)
        if not entry:
            continue
        try:
            days = (_date2.fromisoformat(today) - _date2.fromisoformat(entry["first_seen"])).days
        except ValueError:
            continue
        if days >= PRIVILEGED_MIN_DAYS and key not in privileged_hp:
            privileged.append(cfg)
            privileged_hp.add(key)
            _log.info(f"Promoted to privileged ({days}d): {cfg[:80]}")
        if key in privileged_hp:
            meta[key]["fail_streak"] = 0

    # Обрабатываем упавшие серверы из privileged
    for cfg in dead_configs:
        hp = extract_host_port(cfg)
        if not hp:
            continue
        key = f"{hp[0]}:{hp[1]}"
        if key not in privileged_hp:
            continue
        # Повторные проверки
        recovered = False
        for attempt in range(PRIVILEGED_RECHECK_RETRIES):
            port = find_free_socks_port()
            _log.info(f"Privileged retry {attempt + 1}/{PRIVILEGED_RECHECK_RETRIES}: {cfg[:60]}")
            result = test_config_tunnel(cfg, singbox_path, port)
            if result is not None:
                _log.info(f"Privileged server recovered on retry: {cfg[:60]}")
                meta[key]["fail_streak"] = 0
                recovered = True
                break
        if not recovered:
            privileged = [c for c in privileged if extract_host_port(c) != hp]
            privileged_hp.discard(key)
            meta[key]["fail_streak"] = meta[key].get("fail_streak", 0) + 1
            _log.info(f"Removed from privileged after {PRIVILEGED_RECHECK_RETRIES} retries: {cfg[:60]}")

    save_privileged(results_dir, privileged)
```

- [ ] **Шаг 3.5: Обновить cmd_recheck для вызова _update_privileged и флага --update-known-good**

Заменить `cmd_recheck()` в `vpn_collector/main.py`:

```python
def cmd_recheck(update_known_good: bool = False) -> None:
    """Re-test all configs in known_good.txt; update privileged.txt accordingly."""
    RESULTS_DIR.mkdir(exist_ok=True)
    if not (RESULTS_DIR / "known_good.txt").exists():
        print("No known_good.txt found. Nothing to recheck.")
        sys.exit(1)

    singbox_path = find_singbox()
    if not singbox_path:
        print("sing-box binary not found. Searched:")
        for p in SINGBOX_SEARCH_PATHS:
            print(f"  {p}")
        sys.exit(1)
    _log.info(f"Using sing-box: {singbox_path}")

    configs = load_known_good_configs(RESULTS_DIR)
    _log.info(f"Recheck: {len(configs)} configs loaded from known_good.txt")

    _log.info("TCP pre-filter...")
    tcp_alive = asyncio.run(tcp_filter(configs))
    _log.info(f"TCP: {len(tcp_alive)} alive | {len(configs) - len(tcp_alive)} unreachable")

    _log.info("Tunnel test...")
    recheck_date = date.today().isoformat()
    out_file = RESULTS_DIR / f"recheck_{recheck_date}.txt"
    survivors: list[str] = []

    original_by_base = {c.split("#")[0]: c for c in tcp_alive}

    def on_pass(config: str) -> None:
        original = original_by_base.get(config.split("#")[0], config)
        survivors.append(original)
        with open(out_file, "a") as f:
            f.write(original + "\n")
        _log.info(f"Still good: {original[:80]}...")

    asyncio.run(tunnel_filter(tcp_alive, singbox_path, on_pass=on_pass))

    survivors_hp = {extract_host_port(c) for c in survivors}
    dead_configs = [c for c in configs if extract_host_port(c) not in survivors_hp]

    meta = load_config_meta(RESULTS_DIR)
    _update_privileged(
        results_dir=RESULTS_DIR,
        survivors=survivors,
        dead_configs=dead_configs,
        singbox_path=singbox_path,
        meta=meta,
        today=recheck_date,
    )
    save_config_meta(RESULTS_DIR, meta)

    if update_known_good:
        rewrite_known_good(RESULTS_DIR, survivors)
        _log.info(f"known_good.txt updated: {len(survivors)} survivors, {len(dead_configs)} removed")

    _log.info(
        f"Recheck done: {len(survivors)}/{len(configs)} still working → {out_file.name}"
    )
```

- [ ] **Шаг 3.6: Добавить флаг --update-known-good в argparse (main.py)**

В функции `main()` найти строку с `--recheck` и добавить новый аргумент:

```python
parser.add_argument(
    "--update-known-good",
    action="store_true",
    help="Used with --recheck: overwrite known_good.txt with only surviving configs",
)
```

И в блоке `elif args.recheck:`:

```python
elif args.recheck:
    cmd_recheck(update_known_good=args.update_known_good)
```

- [ ] **Шаг 3.7: Запустить тесты — убедиться что проходят**

```bash
pytest tests/test_main_privileged.py -v
```

Ожидаемый результат: все тесты `PASSED`.

- [ ] **Шаг 3.8: Убедиться что все тесты проходят**

```bash
pytest tests/ -v
```

Ожидаемый результат: все тесты `PASSED`.

- [ ] **Шаг 3.9: Коммит**

```bash
git add vpn_collector/main.py tests/test_main_privileged.py
git commit -m "feat: update privileged.txt during recheck with retry buffer"
```

---

### Task 4: Cron-автоматизация

**Files:**
- Create: `scripts/install_cron.sh`

**Interfaces:**
- Consumes: `vpn_collector/main.py --recheck --update-known-good` (Task 3)
- Produces: cron-задача в пользовательском crontab, idempotent установка

- [ ] **Шаг 4.1: Создать scripts/install_cron.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Найти python в venv или системный
if [ -f "$PROJECT_DIR/.venv/bin/python" ]; then
    PYTHON="$PROJECT_DIR/.venv/bin/python"
elif [ -f "$PROJECT_DIR/venv/bin/python" ]; then
    PYTHON="$PROJECT_DIR/venv/bin/python"
else
    PYTHON="$(which python3)"
fi

LOG_FILE="$PROJECT_DIR/logs/cron_recheck.log"

# Cron-строка: каждые 3 дня в 03:00
CRON_LINE="0 3 */3 * * cd $PROJECT_DIR && $PYTHON -m vpn_collector --recheck --update-known-good >> $LOG_FILE 2>&1"
CRON_MARKER="vpn_collector --recheck"

# Idempotent: добавить только если строки ещё нет
if crontab -l 2>/dev/null | grep -qF "$CRON_MARKER"; then
    echo "Cron job already installed. To view: crontab -l"
    echo "To disable: crontab -e and comment out the line containing '$CRON_MARKER'"
else
    (crontab -l 2>/dev/null; echo "# VPN privileged recheck — auto-maintenance of known_good and privileged"; echo "# To disable: comment out the line below in: crontab -e"; echo "$CRON_LINE") | crontab -
    echo "Cron job installed successfully."
    echo "Schedule: every 3 days at 03:00"
    echo "Logs: $LOG_FILE"
    echo "To disable: crontab -e and comment out the line containing '$CRON_MARKER'"
fi
```

- [ ] **Шаг 4.2: Сделать исполняемым**

```bash
chmod +x scripts/install_cron.sh
```

- [ ] **Шаг 4.3: Проверить скрипт вручную (dry-run)**

```bash
bash -n scripts/install_cron.sh && echo "Syntax OK"
```

Ожидаемый результат: `Syntax OK`.

- [ ] **Шаг 4.4: Коммит**

```bash
git add scripts/install_cron.sh
git commit -m "feat: add install_cron.sh for automatic privileged recheck"
```

---

## Self-Review

**Покрытие спецификации:**
- ✓ config_meta.json (first_seen + fail_streak) — Task 1
- ✓ privileged.txt (полные конфиг-строки, формат как known_good) — Task 1
- ✓ first_seen при --test — Task 2
- ✓ Продвижение в privileged при recheck ≥7 дней — Task 3
- ✓ Буфер PRIVILEGED_RECHECK_RETRIES перед удалением — Task 3
- ✓ --update-known-good флаг — Task 3
- ✓ Cron-автоматизация с лёгким отключением — Task 4
- ✓ Все тесты через clean_env (уже в test_config_tunnel, не меняется)

**Проверка плейсхолдеров:** нет TBD/TODO.

**Согласованность типов:**
- `_update_privileged` принимает `today: str` — передаётся `recheck_date = date.today().isoformat()` ✓
- `load_privileged` / `save_privileged` возвращает/принимает `list[str]` ✓
- `meta` dict мутируется на месте и сохраняется через `save_config_meta` ✓
- `find_free_socks_port` используется в тестах через patch — имя совпадает ✓
