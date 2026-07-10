# Автоматический recheck через cron

## Что делает

Каждые 3 дня в 03:00 автоматически запускает `--recheck --update-known-good`:

- Перепроверяет все конфиги из `known_good.txt` полным tunnel-тестом (не URL-тест)
- Обновляет `results/privileged.txt` — продвигает серверы старше 7 дней, удаляет упавшие
- Перезаписывает `known_good.txt` только живыми серверами
- Логи пишутся в `logs/cron_recheck.log`

## Установка

```bash
bash scripts/install_cron.sh
```

Скрипт idempotent — повторный запуск не добавит дубликат.

## Отключение

```bash
crontab -e
```

Закомментировать строку, содержащую `vpn_collector --recheck`:

```cron
# 0 3 */3 * * cd /path/to/project && .venv/bin/python -m vpn_collector --recheck --update-known-good >> logs/cron_recheck.log 2>&1
```

## Проверка установленных задач

```bash
crontab -l
```

## Ручной запуск recheck

```bash
python -m vpn_collector --recheck --update-known-good
```

## Файлы, которые обновляются

| Файл | Что происходит |
|------|----------------|
| `results/privileged.txt` | Добавляются серверы ≥7 дней, удаляются упавшие после 2 повторных проверок |
| `results/config_meta.json` | Обновляется `fail_streak` по каждому host:port |
| `results/known_good.txt` | Перезаписывается только живыми серверами (только с `--update-known-good`) |
| `results/recheck_YYYY-MM-DD.txt` | Создаётся файл с результатами каждого recheck |
| `logs/cron_recheck.log` | Лог выполнения |
