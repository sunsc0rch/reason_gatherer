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
CRON_LINE="0 3 */3 * * cd $PROJECT_DIR && $PYTHON -m vpn_collector.main --recheck --update-known-good >> $LOG_FILE 2>&1"
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
