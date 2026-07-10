# Privileged Servers Feature — Design Spec

**Date:** 2026-07-10  
**Status:** Approved

## Overview

Добавить отдельный список «привилегированных» прокси-серверов — тех, что стабильно проходят полный tunnel-тест на протяжении более 7 дней. Файл готов для прямого импорта в Throne и аналогичные приложения. Обслуживание списка автоматизировано через cron.

---

## 1. Хранилище данных

### `results/config_meta.json`

Метаданные по host:port — дата первого успешного tunnel-теста и счётчик провалов.

```json
{
  "193.188.23.65:2443": {
    "first_seen": "2026-07-01",
    "fail_streak": 0
  }
}
```

- Ключ: `"host:port"` (строка)
- `first_seen`: дата (ISO 8601) первого прохождения полного tunnel-теста
- `fail_streak`: количество последовательных провалов при recheck (для буфера перед удалением из privileged)

### `results/privileged.txt`

Полные конфиг-строки, готовые для вставки в Throne. Формат идентичен `known_good.txt`.

```
# Updated: 2026-07-10 12:00:00 | Total: 3
vless://...#+++ServerName
vless://...#+++AnotherServer
```

---

## 2. Логика продвижения и удаления

### При `--test` (новые кандидаты)

- Конфиг прошёл tunnel-тест → записать `first_seen = today` в `config_meta.json` (только если запись ещё не существует для данного host:port)
- В `privileged.txt` не добавлять — сервер ещё не выдержал недели

### При `--recheck`

Для каждого конфига из `known_good.txt`:

1. Прогнать через полный tunnel-тест (TCP + sing-box + speedtest)
2. **Прошёл** и `today - first_seen >= PRIVILEGED_MIN_DAYS`:
   - Добавить в `privileged.txt` (если ещё нет)
   - Сбросить `fail_streak = 0`
3. **Не прошёл** и конфиг присутствует в `privileged.txt`:
   - Инкрементировать `fail_streak`
   - Запустить до `PRIVILEGED_RECHECK_RETRIES` повторных tunnel-тестов прямо сейчас
   - Если хоть один повторный прошёл → сбросить `fail_streak`, оставить в privileged
   - Если все повторные провалились → удалить из `privileged.txt`, сбросить `fail_streak`

### Флаг `--update-known-good`

При запуске `--recheck --update-known-good` после теста перезаписать `known_good.txt` только теми конфигами, что прошли recheck (убрать мёртвые).

---

## 3. Новые константы (`config.py`)

```python
PRIVILEGED_MIN_DAYS = 7         # дней стабильной работы для получения статуса
PRIVILEGED_RECHECK_RETRIES = 2  # доп. попыток перед удалением из privileged
```

---

## 4. Изменения в коде

### `vpn_collector/config.py`
- Добавить `PRIVILEGED_MIN_DAYS` и `PRIVILEGED_RECHECK_RETRIES`

### `vpn_collector/storage.py`
Новые функции:
- `load_config_meta(results_dir: Path) -> dict`
- `save_config_meta(results_dir: Path, meta: dict) -> None`
- `load_privileged(results_dir: Path) -> list[str]`
- `save_privileged(results_dir: Path, configs: list[str]) -> None`
- `update_meta_first_seen(meta: dict, host_port: str, today: str) -> None`

### `vpn_collector/main.py`
- `cmd_test()`: после каждого сохранённого конфига вызывать `update_meta_first_seen`
- `cmd_recheck()`: после tunnel-теста вызывать `_update_privileged(...)`; поддержать флаг `--update-known-good`
- Новая внутренняя функция `_update_privileged(results_dir, survivors, failed, singbox_path, meta)`

### `scripts/install_cron.sh`
Idempotent-скрипт установки cron-задачи. Добавляет строку в crontab только если её ещё нет.

---

## 5. Автоматизация через cron

Cron запускает `--recheck --update-known-good` раз в 3 дня.

```cron
# VPN privileged recheck — автоматическое обслуживание known_good и privileged
# Чтобы отключить — закомментировать строку ниже
0 3 */3 * * cd /home/john/allinonce_vllm/reason_gatherer && .venv/bin/python -m vpn_collector --recheck --update-known-good >> logs/cron_recheck.log 2>&1
```

- Логи: `logs/cron_recheck.log`
- Отключение: `crontab -e` и закомментировать строку
- Установка: `bash scripts/install_cron.sh` (скрипт автоматически определяет путь к python через `which python` или ищет `.venv/bin/python`)

---

## 6. Что не меняется

- Формат `known_good.txt` и `run_YYYY-MM-DD.txt`
- Логика TCP-фильтра и tunnel-теста
- Ротация run-файлов
- CLI-интерфейс (кроме нового флага `--update-known-good`)
