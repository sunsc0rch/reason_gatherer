import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
RESULTS_DIR = BASE_DIR / "results"
LOGS_DIR = BASE_DIR / "logs"
SOURCES_FILE = BASE_DIR / "sources.json"

TCP_TIMEOUT = 4.0
TCP_CONCURRENCY = 100
TCP_BATCH_SIZE = 5000
TUNNEL_CONCURRENCY = 20
MIN_SPEED_MBPS = 1.0
MAX_RUN_FILES = 5
SOCKS_PORT_RANGE = (10000, 19999)
SINGBOX_STARTUP_TIMEOUT = 3.0
# Early abort: if speed is below this fraction of MIN_SPEED_MBPS after
# SPEEDTEST_EARLY_ABORT_AFTER seconds, the server can't mathematically
# recover to pass the threshold.
SPEEDTEST_EARLY_ABORT_FACTOR = 0.5
SPEEDTEST_EARLY_ABORT_AFTER = 4.0

SPEEDTEST_URLS = [
    "http://cachefly.cachefly.net/1mb.test",           # Akamai CDN, globally distributed
    "https://speed.cloudflare.com/__down?bytes=1048576", # Cloudflare, best coverage from RU
    "https://proof.ovh.net/files/1Mb.dat",              # OVH Europe, good RU peering
]
CLAUDE_CHECK_URL = "https://claude.com/"
# Only check the final redirect URL for hard ISP-level block pages.
CLAUDE_BLOCK_URL_KEYWORDS = ["/blocked", "/unavailable", "/restricted"]

SINGBOX_SEARCH_PATHS = [
    "/opt/throne",
    "/usr/local/bin",
    os.path.expanduser("~/.local/share/throne"),
    os.path.expanduser("~/throne"),
    os.path.expanduser("~/.local/bin"),
    "/usr/bin",
    "/opt/hiddify",
    os.path.expanduser("~/.local/share/hiddify"),
]

VPN_PREFIXES = (
    "vless://", "vmess://", "trojan://", "ss://",
    "hysteria://", "hysteria2://", "hy2://", "tuic://",
    "socks://",
)

SKIP_FILENAMES = {
    "readme", "requirements", "license", "changelog",
    "vercel.json", ".gitignore", ".github",
}
SKIP_EXTENSIONS = {".json", ".md", ".html", ".py", ".sh", ".toml"}

PROXY_ENV_VARS = [
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
]

DEFAULT_SOURCES = [
    {"type": "repo", "value": "VP01596/vless-top15"},
    {"type": "repo", "value": "qopq1366/VlessConfig"},
    {"type": "repo", "value": "Vovo4ka000/V4kVPN"},
    {"type": "repo", "value": "MustafaBaqer/VestraNet-Nodes"},
    {"type": "repo", "value": "Mr-Meshky/vify"},
    {"type": "repo", "value": "kasesm/Free-Config"},
    {"type": "repo", "value": "igareck/vpn-configs-for-russia"},
    {"type": "repo", "value": "LalatinaHub/Mineral"},
    {"type": "repo", "value": "luxxuria/harvester"},
    {"type": "repo", "value": "mahdibland/V2RayAggregator"},
    {"type": "repo", "value": "barry-far/V2ray-Config"},
    {"type": "repo", "value": "freefq/free"},
    {"type": "repo", "value": "peasoft/NoMoreVPN"},
]

TG_AUTH_FILE    = Path.home() / ".config" / "vpn_collector" / "tg_auth.json"
TG_SESSION_FILE = Path.home() / ".config" / "vpn_collector" / "tg"
TG_POSTS_LIMIT  = 50
