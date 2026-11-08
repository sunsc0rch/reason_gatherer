# reason_gatherer — AGENTS.md

Документация проекта (AWG-коллектор, источники, форматы архивов) — в `CLAUDE.md`.
Ниже — системный контекст хоста, продублированный из `CLAUDE.md` (полная версия с цифрами — README, раздел «WARP integration: warp-cli, Throne, zapret»).

## WARP / Throne / zapret (системный контекст хоста)

Три независимые части, работают одновременно.

### warp-cli — обход ISP-блэков для тестов

- `warp-cli mode proxy` → локальный SOCKS5 `127.0.0.1:40000`, его ждёт `--proxy` в `--diagnose`. **Не включать `mode warp` при тестах** — весь системный трафик пойдёт через туннель, все пробы станут «живыми», отчёт обесценится.
- Транспорт MASQUE (QUIC/HTTP3, UDP 443 → Cloudflare anycast `162.159.x`), не WireGuard — WG на UDP 2408 режется DPI тривиально.
- Честный A/B на одном пуле (227 конфигов): 8 configs / 6 endpoints напрямую vs 147 / 13 через WARP. Все 12 спасённых эндпоинтов — `blocked_by_isp`; 5 из 17 чёрных дыр мертвы даже через WARP.

### Throne — системный прокси со встроенной WARP

- Системный прокси: mixed-inbound `127.0.0.1:2080` (`system_proxy_enabled=true`).
- **WARP как egress (отбелывание IP)**: Routing Settings → вкладка Warp → Mode **MASQUE** → *Generate Warp Config* (регистрирует устройство в Cloudflare; MASQUE-identity отдельная от уже сгенерированной WireGuard) → *Enable Warp*. Цепочка `app → node → WARP → target`: нода стучится в свой сервер **напрямую** (`generate.cpp` делает warp профиль первым в outbound-массиве, а ноде — `detour` на него). Заблокированные ноды это **не** чинит.
- **WARP как ingress (дотянуться до `blocked_by_isp`)**: добавить профиль типа `socks` → `127.0.0.1:40000` (режим proxy warp-cli), затем Group → Edit Group → **Front Proxy** → выбрать его. Front proxy становится диалером ноды: `local → WARP(SOCKS) → node → target`. Нода достижима, exit-IP остаётся ноды. Вместо warp-cli можно нативный профиль типа `masque` (кнопка *Register a new Cloudflare WARP device* в редакторе профиля).
- Throne API по умолчанию выключен (`remote_api_enable=false`): для `thronectl` включить в Preferences → Integration Settings (без ключа `thronectl` не работает).

### zapret — предохранитель для транспорта WARP

- Правило живёт в `/opt/zapret/config`, в начале `NFQWS_OPT` (два сегмента через `--new`, оба на `--hostlist-domains=cloudflareclient.com`): UDP/443 — `fake` + fake-quic, TCP/443 (fallback MASQUE на HTTP/2) — `fake,multidisorder` + fake-tls. Бэкап: `/opt/zapret/config.backup-warp-20261108-*`. Активация: `sudo systemctl restart zapret`.
- warp-svc и так попадает в очередь nfqws (nft `postnat`: `udp dport 443 ct original packets 1-9 → queue 200`) — правило лишь добавляет десинхронизацию.
- Спасает от **DPI-детекта MASQUE по SNI** (читаемый QUIC Initial / TLS ClientHello `*.cloudflareclient.com`). **Не спасает** от IP-блэка `engage.cloudflareclient.com` (там менять `warp_masque_ep`/`warp_api_hosts` или нести WARP поверх другого прокси) и от IP-троттлинга.
- Контроль после правок: `curl --socks5-hostname 127.0.0.1:40000 https://www.cloudflare.com/cdn-cgi/trace` → `warp=on`; системный прокси Throne → HTTP 204.
