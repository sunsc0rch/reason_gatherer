# Telegram Source + socks:// Protocol — Implementation Spec

## Goal

Add Telegram channels as a VPN config source alongside existing GitHub repo and raw URL sources. Also add `socks://` protocol support throughout the pipeline.

## Architecture

Two independent additions shipped together:

1. **`socks://` protocol** — new VPN prefix + sing-box outbound parser
2. **Telegram source type `"tg"`** — new `tg_source.py` module, `--setup-tg` CLI command, integration into existing `fetch_all_configs` pipeline

---

## Part 1: socks:// Protocol

### Config format
```
socks://[base64(user:pass)@]host:port#name
```
Example: `socks://Og@185.8.172.128:443#%40proxy_kafee`  
`Og` = base64 of `:` → empty username, empty password.

### Changes
- `config.py`: add `"socks://"` to `VPN_PREFIXES`
- `tester.py`: add `_parse_socks(line)` → sing-box `"type": "socks"` outbound:
  ```python
  {
      "type": "socks",
      "tag": "proxy",
      "server": host,
      "server_port": port,
      "username": username,   # empty string if not present
      "password": password,   # empty string if not present
      "version": "5",
  }
  ```
- `generate_singbox_config()`: add `elif line.startswith("socks://")` branch

---

## Part 2: Telegram Source

### Auth storage (never committed to git)

| File | Path | Content |
|---|---|---|
| Auth config | `~/.config/vpn_collector/tg_auth.json` | `{"api_id": 12345, "api_hash": "abc..."}` |
| Session | `~/.config/vpn_collector/tg.session` | Telethon binary session (auto-managed) |

Both files live outside the repository. `~/.config/vpn_collector/` is created automatically.

### New file: `vpn_collector/tg_source.py`

Public interface:

```python
def load_tg_auth() -> dict | None
# Returns {"api_id": int, "api_hash": str} or None if file missing

def save_tg_auth(api_id: int, api_hash: str) -> None
# Writes ~/.config/vpn_collector/tg_auth.json, creates dir if needed

def is_tg_configured() -> bool
# True if auth file exists AND session file exists

async def fetch_tg_channel_configs(client, channel: str, limit: int) -> list[str]
# Fetches last `limit` posts from `channel`, extracts VPN configs.
# `channel` is bare name (no @, no t.me/).
# Silently returns [] on access errors (private channel, banned, etc.)

async def fetch_all_tg_configs(channels: list[str], limit: int = 50) -> list[str]
# Loads auth + session, connects client, calls fetch_tg_channel_configs
# for each channel, deduplicates, returns merged list.
# If auth missing: logs WARNING "Run --setup-tg first", returns [].
# If session missing: logs WARNING "Run --setup-tg first", returns [].
# If Telethon not installed: logs ERROR with install instructions, returns [].
```

### `--setup-tg` command flow

```
1. Check ~/.config/vpn_collector/tg_auth.json
   - Exists → load api_id, api_hash
   - Missing → prompt user for api_id and api_hash, save to file
2. Create TelegramClient(session_path, api_id, api_hash)
3. Prompt for phone number (e.g. +79991234567)
4. Telegram sends SMS → prompt for code
5. If 2FA enabled → prompt for password
6. Session saved automatically to ~/.config/vpn_collector/tg.session
7. Print: "Setup complete. Add channels with: --add-source t.me/channelname"
```

### `add_source` changes

Detect Telegram URLs and normalize to bare channel name:

| Input | Stored as |
|---|---|
| `t.me/channelname` | `{"type": "tg", "value": "channelname"}` |
| `t.me/s/channelname` | `{"type": "tg", "value": "channelname"}` |
| `https://t.me/channelname` | `{"type": "tg", "value": "channelname"}` |

Detection: input starts with `t.me/` or `https://t.me/` (after stripping).

### `fetch_all_configs` integration

```python
def fetch_all_configs(sources_file):
    sources = load_sources(sources_file)
    tg_channels = [s["value"] for s in sources if s["type"] == "tg"]
    
    # existing GitHub + URL fetch (unchanged)
    configs = [...existing logic...]
    
    # TG fetch — non-blocking if not configured
    if tg_channels:
        tg_configs = asyncio.run(fetch_all_tg_configs(tg_channels))
        for c in tg_configs:
            if c not in seen:
                seen.add(c)
                configs.append(c)
    
    return configs
```

### Error handling

| Situation | Behaviour |
|---|---|
| `tg_auth.json` missing | WARNING + skip TG, `--collect` continues |
| `tg.session` missing | WARNING + skip TG, `--collect` continues |
| `telethon` not installed | ERROR with `pip install telethon`, skip TG |
| Channel not found / no access | DEBUG log per channel, skip that channel |
| Session expired / auth error | WARNING "Session invalid, run --setup-tg again" |
| Network error | WARNING per channel, skip |

### `config.py` additions

```python
TG_AUTH_FILE    = Path.home() / ".config" / "vpn_collector" / "tg_auth.json"
TG_SESSION_FILE = Path.home() / ".config" / "vpn_collector" / "tg"  # no .session ext — Telethon adds it
TG_POSTS_LIMIT  = 50
```

### `requirements.txt`

Add: `telethon>=1.36`

---

## Testing

### `tests/test_tg_source.py`

- `test_load_tg_auth_missing` — returns None when file absent
- `test_load_tg_auth_present` — returns dict when file present
- `test_save_tg_auth_creates_dir` — creates `~/.config/vpn_collector/` if missing
- `test_is_tg_configured_false_no_auth` — False when auth missing
- `test_is_tg_configured_false_no_session` — False when auth present but session missing
- `test_is_tg_configured_true` — True when both exist
- `test_fetch_tg_channel_configs_parses_posts` — mock TelegramClient, posts with VPN configs extracted
- `test_fetch_tg_channel_configs_skips_empty_posts` — posts without configs return []
- `test_fetch_all_tg_configs_no_auth_returns_empty` — logs warning, returns []
- `test_fetch_all_tg_configs_telethon_missing` — ImportError → logs error, returns []

### `tests/test_tester.py` additions

- `test_socks_structure` — `generate_singbox_config("socks://Og@1.2.3.4:443#name")` → type=socks, server, port, empty creds

### `tests/test_sources.py` additions

- `test_add_source_tme_url` — `add_source("t.me/channelname")` → `{"type": "tg", "value": "channelname"}`
- `test_add_source_tme_s_url` — strips `/s/` prefix
- `test_add_source_tme_https` — strips `https://`

---

## Out of scope

- Listing all channels the user is subscribed to (only manually-added channels via `--add-source`)
- Media/file attachments in Telegram posts (text only)
- Telegram groups (channels only)
