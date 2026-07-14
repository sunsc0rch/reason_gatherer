# AWG Collector — Design Spec

**Date:** 2026-07-14  
**Scope:** Новый изолированный модуль `awg_collector` для сбора и тестирования AmneziaWG конфигов.

---

## Цель

Собирать AmneziaWG (WireGuard с обфускацией) конфиги из публичных источников, тестировать их полноценным tunnel-тестом через сетевые пространства имён Linux, сохранять рабочие в виде `.conf` файлов и единого `.vpn` ZIP-архива для импорта в Amnezia 1.0.1.

Модуль полностью изолирован от `vpn_collector` — нет общих импортов, нет общих файлов результатов.

---

## Структура модуля

```
awg_collector/
├── __init__.py
├── config.py       # константы: пути, таймауты, пороги скорости
├── parser.py       # парсинг WireGuard .conf + AWG-полей
├── sources.py      # загрузка конфигов из GitHub / Telegram / URL
├── tester.py       # сетевые namespace + awg-quick + speedtest
├── storage.py      # сохранение .conf + генерация .vpn ZIP
└── main.py         # CLI: --collect, --recheck, --export, --add-source, --stats

results_awg/
├── known_good/             # .conf файлы прошедших tunnel-тест
├── all_configs.vpn         # ZIP всех known_good для импорта в Amnezia
├── candidates.conf         # сырые конфиги до тестирования
└── config_meta.json        # {"host:port": {"first_seen": "YYYY-MM-DD", "fail_streak": 0}}

sources_awg.json            # список источников AWG конфигов

tests/
├── test_awg_parser.py
├── test_awg_tester.py
└── test_awg_storage.py
```

---

## Формат конфигурации AmneziaWG

Стандартный WireGuard `.conf` с дополнительными полями обфускации в секции `[Interface]`:

```ini
[Interface]
PrivateKey = base64key==
Address = 10.8.0.2/32
DNS = 1.1.1.1
Jc = 4        # количество junk-пакетов (AWG-специфично)
Jmin = 40     # мин. размер junk-пакета
Jmax = 70     # макс. размер junk-пакета
S1 = 0        # дополнительный заголовок init handshake
S2 = 0        # дополнительный заголовок response handshake
H1 = 1        # magic header 1
H2 = 2        # magic header 2
H3 = 3        # magic header 3
H4 = 4        # magic header 4

[Peer]
PublicKey = base64key==
PresharedKey = base64key==   # опционально
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = 185.x.x.x:51820  # идентификатор сервера
PersistentKeepalive = 25
```

**Идентификация сервера:** `Endpoint` (host:port) из секции `[Peer]`.

**Признак AWG-конфига:** наличие хотя бы одного поля из `Jc`, `Jmin`, `Jmax`, `S1`, `S2`, `H1`-`H4`. Обычные WireGuard конфиги (без AWG-полей) отбрасываются.

---

## Парсер (`parser.py`)

- Читает `.conf` из текста или файла
- Поддерживает текст с несколькими конфигами подряд (разделитель — строка `[Interface]`)
- Извлекает endpoint (`host:port` из `[Peer] → Endpoint`)
- Валидирует наличие обязательных полей: `PrivateKey`, `PublicKey`, `Endpoint`
- Генерирует имя файла из endpoint: `185.123.45.67_51820.conf`
- Возвращает структуру: `{"text": str, "endpoint": str, "filename": str, "is_awg": bool}`

---

## Источники (`sources.py`)

Три типа в `sources_awg.json`:

```json
[
  {"type": "github", "value": "owner/repo"},
  {"type": "url",    "value": "https://raw.../config.conf"},
  {"type": "tg",     "value": "channel_name"}
]
```

- **github:** обход репозитория через GitHub API, поиск `*.conf` и `*.vpn`/`*.zip`, скачивание и парсинг
- **url:** прямая загрузка `.conf`, `.zip`, `.vpn` или текстового файла с несколькими конфигами
- **tg:** парсинг постов Telegram-канала на наличие `.conf` вложений или текстовых блоков

Начальный список источников определяется в ходе реализации (шаг 1 плана — ресёрч активных Telegram-каналов и GitHub-репозиториев с AWG-конфигами). Критерии отбора источников: регулярные обновления, наличие AWG-полей (`Jc` и т.д.), не обычный WireGuard.

Дедупликация перед тестированием: по `Endpoint` (host:port).

---

## Тестер (`tester.py`)

### Предварительные требования (однократная ручная установка)

```bash
apt install amneziawg-tools   # предоставляет awg и awg-quick
# + один из вариантов:
#   а) ядерный модуль amneziawg (dkms)
#   б) amneziawg-go (userspace, проще на Proxmox)
```

### Алгоритм теста одного конфига

```
1. Записать временный .conf в /tmp/ (с DNS = 1.1.1.1)
2. sudo ip netns add awg_test_<uuid4>
3. sudo ip netns exec awg_test_<uuid4> awg-quick up /tmp/<uuid4>.conf
4. Тест скорости (curl внутри netns):
   sudo ip netns exec awg_test_<uuid4> \
     curl --max-time 15 -o /dev/null -w "%{speed_download}" <SPEEDTEST_URL>
5. sudo ip netns exec awg_test_<uuid4> awg-quick down /tmp/<uuid4>.conf
6. sudo ip netns del awg_test_<uuid4>
7. Удалить /tmp/<uuid4>.conf
```

Cleanup выполняется в `finally` — namespace и temp-файл удаляются даже при исключении.

### Параметры

| Параметр | Значение |
|---|---|
| `AWG_TUNNEL_CONCURRENCY` | 3 (меньше чем у VLESS — каждый тест создаёт сетевой интерфейс) |
| `AWG_TEST_TIMEOUT` | 30 секунд на один конфиг |
| `MIN_SPEED_MBPS` | 1.0 Мбит/с (тот же порог что у VLESS) |

### Провал теста

`awg-quick up` завершился с ошибкой (недоступный сервер, неверные ключи) **ИЛИ** скорость < порога → конфиг отброшен, namespace удалён.

### Изоляция от системы

Все изменения маршрутизации происходят внутри отдельного netns — основная таблица маршрутов, singbox, tinyproxy, zapret, throne не затрагиваются.

---

## Хранилище (`storage.py`)

### Файловая структура

```
results_awg/
├── known_good/
│   ├── 185.123.45.67_51820.conf   # имя = endpoint с заменой : на _
│   ├── vpn.example.com_51820.conf
│   └── ...
├── all_configs.vpn                # ZIP-архив всех known_good
├── candidates.conf                # сырые конфиги (многоблочный файл)
└── config_meta.json
```

### `.vpn` архив

Обычный ZIP-файл: каждый конфиг как отдельный `<filename>.conf` внутри архива. Amnezia 1.0.1 импортирует через "Добавить конфигурацию → из файла".

### Ключевые функции

- `save_known_good(conf_text, endpoint)` — пишет `.conf` в `known_good/`, перезаписывает если AWG-поля изменились
- `load_known_good()` → `list[dict]` с текстом и endpoint каждого конфига
- `build_vpn_archive()` — пересобирает `all_configs.vpn` из текущего `known_good/`
- `load_config_meta()` / `save_config_meta()` — JSON метаданные
- `load_candidates()` / `save_candidates()` — сырые конфиги

### config_meta.json

```json
{
  "185.123.45.67:51820": {
    "first_seen": "2026-07-14",
    "fail_streak": 0
  }
}
```

---

## CLI (`main.py`)

```bash
python3 -m awg_collector.main --collect       # собрать → TCP-пинг → tunnel-тест → сохранить
python3 -m awg_collector.main --recheck       # перепроверить all known_good
python3 -m awg_collector.main --export        # пересобрать all_configs.vpn без тестов
python3 -m awg_collector.main --add-source U  # добавить источник в sources_awg.json
python3 -m awg_collector.main --stats         # статистика: кол-во в known_good, meta
```

### Поток `--collect`

```
fetch_all_configs(sources_awg.json)
  → парсинг AWG-конфигов
  → дедупликация по endpoint
  → сохранить в candidates.conf
  → TCP-пинг endpoint (быстрая предфильтрация)
  → tunnel-тест выживших (netns + awg-quick + speedtest)
  → save_known_good() для прошедших
  → update config_meta (first_seen)
  → build_vpn_archive()
```

### Поток `--recheck`

```
load_known_good()
  → tunnel-тест каждого
  → провал: повторить 2 раза (RECHECK_RETRIES = 2)
  → всё равно провал: удалить из known_good/
  → build_vpn_archive()
  → обновить config_meta (fail_streak → 0 при удалении)
```

### Логи

`logs/awg_collector.log` — общая папка `logs/` проекта.

---

## Тестирование

TDD-подход: сначала тесты, потом реализация.

- `test_awg_parser.py` — парсинг валидных/невалидных конфигов, детектирование AWG-полей, извлечение endpoint
- `test_awg_tester.py` — mock-тесты tunnel-теста (мокаем `subprocess.run` для awg-quick и curl)
- `test_awg_storage.py` — сохранение/загрузка конфигов, генерация ZIP, config_meta

---

## Ограничения и допущения

- Требует `sudo` для операций с netns и `awg-quick`
- `amneziawg-tools` должен быть установлен перед первым запуском
- Только AWG конфиги (с полями Jc/S1/H1 и т.д.) — обычный WireGuard отбрасывается
- Параллельность ограничена 3 одновременными тестами во избежание конфликтов интерфейсов
