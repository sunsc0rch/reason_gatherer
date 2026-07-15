# reason_gatherer — CLAUDE.md

## AWG Collector (`awg_collector/`)

### AmneziaWG 1.0.1 — поддерживаемые поля

Amnezia 1.0.1 поддерживает в секции `[Interface]` только:
`Jc`, `Jmin`, `Jmax`, `S1`, `S2`, `H1`, `H2`, `H3`, `H4`

Поля `S3` и `I1` (AWG 2.x, присутствуют в WARP конфигах Delta-Kronecker) **не поддерживаются** — вызывают ошибку «нераспознанный ключ». Функция `strip_awg2_fields()` в `storage.py` автоматически удаляет их перед сохранением.

### Формат архива

Amnezia 1.0.1 принимает **только `.zip`** (не `.vpn`, не `.conf` с AWG 2.x полями).
Архив: `results_awg/all_configs.zip`

### Tunnel-тестирование AWG

- AWG — UDP, TCP pre-filter неприменим (убран из pipeline)
- `amneziawg-go` работает в **основном netns** (не изолированном — UDP не пройдёт)
- `Table = off` в `[Interface]` предотвращает изменение маршрутов хоста
- Handshake: `awg show iface latest-handshakes`, скорость: `curl --interface iface`
- Требует `amneziawg-go` в PATH + NOPASSWD sudoers для `awg`, `awg-quick`, `ip`, `curl`

### Компиляция amneziawg-go

Требует Go 1.25+. При сборке: `GOPROXY=https://goproxy.io,https://goproxy.cn,direct`
(proxy.golang.org недоступен с этого сервера)

### Источники конфигов (`sources_awg.json`)

- `Delta-Kronecker/WARP-Config` на GitHub — WARP конфиги (S3/I1 стрипаются автоматически)
- TG `amnezia_wg` — реальные AWG конфиги от сообщества
- TG `vpnconfigsgive` — реальные AWG конфиги

GitHub raw URL может не работать без системного прокси (session использует `trust_env=False`).

### Структура результатов

```
results_awg/
  known_good/      ← проверенные .conf файлы (без S3/I1)
  all_configs.zip  ← архив для импорта в Amnezia
  candidates.conf  ← все собранные кандидаты до тестирования
```
