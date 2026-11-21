import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
RESULTS_DIR = BASE_DIR / "results"
LOGS_DIR = BASE_DIR / "logs"
SOURCES_FILE = BASE_DIR / "sources.json"

TCP_TIMEOUT = 4.0
TCP_CONCURRENCY = 100
# Blackhole (ISP destination-IP drop point) detector: ping with a TTL cap.
# A reply at any of these TTLs means the packet cleared the ISP drop point;
# silence at all of them means the destination is dropped inside the access
# network (before the first hop that would answer with Time-to-live-exceeded).
BLACKHOLE_TTLS = (5, 8, 12)
PING_TIMEOUT = 2.0
TCP_BATCH_SIZE = 5000
TUNNEL_CONCURRENCY = 32
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
GEMINI_TEST_MODEL = os.environ.get("GEMINI_TEST_MODEL", "gemini-3.8-flash")
GEMINI_TEST_DEFAULT_SAMPLE = 10
GEMINI_TEST_INTERVAL_SECONDS = 12.0

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
    {"type": "repo", "value": "MustafaBaqer/VestraNet-Nodes"},
    {"type": "repo", "value": "Mr-Meshky/vify"},
    {"type": "repo", "value": "kasesm/Free-Config"},
    {"type": "repo", "value": "igareck/vpn-configs-for-russia"},
    {"type": "repo", "value": "LalatinaHub/Mineral"},
    {"type": "repo", "value": "luxxuria/harvester"},
    {"type": "repo", "value": "mahdibland/V2RayAggregator"},
    {"type": "repo", "value": "barry-far/V2ray-Config"},
    {"type": "repo", "value": "freefq/free"},
    # Curated raw feeds from @airfield1972 #keys; endpoints checked 2026-11-20.
    {"type": "url", "value": "https://raw.githubusercontent.com/Areral/ScarletDevil/refs/heads/main/sub_all.txt"},
    {"type": "url", "value": "https://raw.githubusercontent.com/TelegaVPN/free-vpn-keys/refs/heads/main/sub/base64/all.txt"},
    {"type": "url", "value": "https://raw.githubusercontent.com/Edsel-Rahimi/Ariston/data/gold.txt"},
    {"type": "url", "value": "https://raw.githubusercontent.com/theakres/VPN/refs/heads/main/all"},
    {"type": "url", "value": "https://gist.githubusercontent.com/zhangqiyang2-max/47f1336a2e41af2e0f7f4313cc8c4bdc/raw/v2ray.txt"},
    {"type": "url", "value": "https://gist.githubusercontent.com/554mtntjch-code/3a1a5e147050f64d72d5b8f5c6d4d61c/raw/v2ray.txt"},
    {"type": "url", "value": "https://gist.githubusercontent.com/skysph-dev/5b55986287442543485b30468db3eb65/raw/v2ray.txt"},
    {"type": "url", "value": "https://gist.githubusercontent.com/st0rer/52759ee3f68c3d4b2f2d53c307867471/raw/hy2_nodes.txt"},
    {"type": "url", "value": "https://gist.githubusercontent.com/December000/fd23d2530ffc29264297a5e687a79ecd/raw/base64.txt"},
    {"type": "url", "value": "https://raw.githubusercontent.com/ivanprochorov2022-debug/V2RayN-VPN-Source/refs/heads/main/live.txt"},
    # Active public Telegram channels selected from @airfield1972 #keys.
    {"type": "tg", "value": "pass_net"},
    {"type": "tg", "value": "VPsave"},
    {"type": "tg", "value": "configv2rayng"},
    {"type": "tg", "value": "ex_proxies"},
    {"type": "tg", "value": "FXxNET"},
    # Live-tested, regularly rebuilt subscriptions; checked 2026-11-20.
    {"type": "url", "value": "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/top100.txt"},
    {"type": "url", "value": "https://raw.githubusercontent.com/rekt0ro/ProxyRift/main/subscriptions/light.txt"},
    {"type": "url", "value": "https://raw.githubusercontent.com/Danialsamadi/v2go/main/AllConfigsSub.txt"},
]

TG_AUTH_FILE    = Path.home() / ".config" / "vpn_collector" / "tg_auth.json"
TG_SESSION_FILE = Path.home() / ".config" / "vpn_collector" / "tg"
TG_POSTS_LIMIT  = 50

PRIVILEGED_MIN_DAYS = 7
PRIVILEGED_RECHECK_RETRIES = 2

SUBSCRIPTION_MAX_URLS = 100
SUBSCRIPTION_MAX_NODES = 30
SUBSCRIPTION_NODE_BATCH_SIZE = 10
SUBSCRIPTION_REPO_FETCH_CONCURRENCY = 10
