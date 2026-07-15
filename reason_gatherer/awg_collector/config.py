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
TOP_N_CONFIGS = 50             # сколько fastest конфигов сохранять в known_good

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
TG_POSTS_LIMIT  = 200

GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"

AWG_FIELDS = {"Jc", "Jmin", "Jmax", "S1", "S2", "H1", "H2", "H3", "H4"}

DEFAULT_SOURCES_AWG: list[dict] = [
    {"type": "tg", "value": "amnezia_vpn_news_ru"},
    {"type": "tg", "value": "Neko_Shadowsocks"},
    {"type": "tg", "value": "amnezia_config"},
]
