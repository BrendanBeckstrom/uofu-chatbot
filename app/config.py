"""Central settings. Everything can be overridden from .env (see .env.example)."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SITE = "https://www.price.utah.edu"

# WordPress sites the assistant indexes. All expose the public WordPress REST API.
SITES = {
    "price": {"name": "Price College of Engineering", "base": "https://www.price.utah.edu"},
    "ece": {"name": "Electrical & Computer Engineering", "base": "https://www.ece.utah.edu"},
    "mech": {"name": "Mechanical Engineering", "base": "https://www.mech.utah.edu"},
    "bme": {"name": "Biomedical Engineering", "base": "https://www.bme.utah.edu"},
    "che": {"name": "Chemical Engineering", "base": "https://www.che.utah.edu"},
    "civil": {"name": "Civil & Environmental Engineering", "base": "https://www.civil.utah.edu"},
    "mse": {"name": "Materials Science & Engineering", "base": "https://www.mse.utah.edu"},
    "cs": {"name": "Kahlert School of Computing", "base": "https://www.cs.utah.edu"},
}

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DOCS_PATH = DATA_DIR / "docs.json"
STATE_PATH = DATA_DIR / "sync_state.json"
FEEDBACK_PATH = DATA_DIR / "feedback.jsonl"
USAGE_PATH = DATA_DIR / "usage.jsonl"
WEB_DIR = ROOT / "web"

# Identify the bot honestly. Cloudflare in front of the sites blocks generic
# "Mozilla/5.0" strings, but a descriptive UA is allowed through.
USER_AGENT = os.getenv(
    "SCRAPER_USER_AGENT",
    "PriceChatbotPOC/0.1 (University of Utah student proof-of-concept)",
)

# robots.txt on these sites asks crawlers for a 10 second delay. Indexing and
# syncing honour it; live page reads (one per user question) use a shorter gap.
CRAWL_DELAY = float(os.getenv("CRAWL_DELAY", "10"))
LIVE_FETCH_INTERVAL = float(os.getenv("LIVE_FETCH_INTERVAL", "2"))
LIVE_CACHE_TTL = float(os.getenv("LIVE_CACHE_TTL", "3600"))

# Freshness: when a question arrives and the last change check is older than this,
# a background sync asks each site "what changed?" (2 tiny requests per site).
# Off on Cloud Run, which pauses the server between requests; there the index ships with each deploy.
AUTO_SYNC = os.getenv("AUTO_SYNC", "true").lower() in ("1", "true", "yes")
SYNC_TTL_MINUTES = float(os.getenv("SYNC_TTL_MINUTES", "30"))
# Deleted or unpublished pages don't show up as "changed"; a fuller ID check finds them.
RECONCILE_DAYS = float(os.getenv("RECONCILE_DAYS", "7"))
THIN_PAGE_CHARS = 300  # pages with less API text than this get their rendered HTML read instead

# College events live in the U's Trumba calendar, not WordPress.
TRUMBA_CALENDAR = os.getenv("TRUMBA_CALENDAR", "uu-college-of-engineering")
EVENTS_CACHE_TTL = float(os.getenv("EVENTS_CACHE_TTL", "900"))
TIMEZONE = "America/Denver"

MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")
# Namespaced on purpose: a shell-wide CLAUDE_EFFORT meant for another tool must not change this app.
EFFORT = os.getenv("CHATBOT_EFFORT", "low")
MAX_TOOL_STEPS = int(os.getenv("MAX_TOOL_STEPS", "3"))


# ---- Abuse and cost protection (see docs/SECURITY.md) ------------------------------------------

def _limits(name: str, default: str) -> list[tuple[int, float]]:
    """"10/60,60/3600" -> [(10, 60.0), (60, 3600.0)]: max requests per window in seconds."""
    rules = []
    for part in os.getenv(name, default).split(","):
        n, window = part.strip().split("/")
        rules.append((int(n), float(window)))
    return rules


# Only trust X-Forwarded-For / CF-Connecting-IP when the app runs behind a proxy you control;
# otherwise anyone could fake their IP and dodge the per-client limits.
TRUST_PROXY = os.getenv("TRUST_PROXY", "false").lower() in ("1", "true", "yes")

# Each browser gets a signed token (no login needed). Limits apply per token, with a looser per-IP
# backstop so a campus Wi-Fi network (many students behind one IP) isn't throttled as one person.
TOKEN_LIMITS = _limits("TOKEN_LIMITS", "5/60,30/3600,100/86400")          # per browser
IP_LIMITS = _limits("IP_LIMITS", "30/60,300/3600,1000/86400")             # per IP (IPv6 per /64)
TOKEN_ISSUE_LIMITS = _limits("TOKEN_ISSUE_LIMITS", "60/3600")             # new tokens per IP
TOKEN_TTL_HOURS = float(os.getenv("TOKEN_TTL_HOURS", "24"))
# Beta gate: when set, a browser gets a token only after entering this shared password (web/login.html).
BETA_PASSWORD = os.getenv("BETA_PASSWORD", "")
LOGIN_LIMITS = _limits("LOGIN_LIMITS", "10/600")                          # password attempts per IP
# Pages on other sites that may call the API (comma-separated), e.g. the Firebase Hosting addresses.
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
GLOBAL_CHAT_LIMITS = _limits("GLOBAL_CHAT_LIMITS", "30/60,600/3600")      # everyone combined
SEARCH_LIMITS = _limits("SEARCH_LIMITS", "20/60")
EVENTS_LIMITS = _limits("EVENTS_LIMITS", "60/60")
FEEDBACK_LIMITS = _limits("FEEDBACK_LIMITS", "5/60,50/86400")
MAX_CONCURRENT_ANSWERS = int(os.getenv("MAX_CONCURRENT_ANSWERS", "8"))
MAX_CONCURRENT_PER_CLIENT = int(os.getenv("MAX_CONCURRENT_PER_CLIENT", "1"))
MAX_BODY_BYTES = 16_384

# Money: a daily circuit breaker in the app, below the monthly limit set on the Anthropic workspace.
DAILY_BUDGET_USD = float(os.getenv("DAILY_BUDGET_USD", "5"))              # 0 = no cap
RESERVE_PER_ANSWER_USD = 0.015  # held while an answer runs, so parallel answers can't overshoot the cap

# Per-question budgets.
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "3000"))           # per model call, thinking included
MAX_TURNS_PER_SESSION = int(os.getenv("MAX_TURNS_PER_SESSION", "20"))
MAX_CONTEXT_TOKENS = int(os.getenv("MAX_CONTEXT_TOKENS", "40000"))        # then the chat asks to start fresh
SESSION_IDLE_MINUTES = float(os.getenv("SESSION_IDLE_MINUTES", "30"))
MAX_MESSAGE_CHARS = int(os.getenv("MAX_MESSAGE_CHARS", "1000"))
ANSWER_CACHE_HOURS = float(os.getenv("ANSWER_CACHE_HOURS", "6"))          # repeated first questions; 0 = off

# Topic scoping: a small classifier call labels each message before the main answer.
SCOPE_GATE = os.getenv("SCOPE_GATE", "true").lower() in ("1", "true", "yes")
SCOPE_GATE_MODEL = os.getenv("SCOPE_GATE_MODEL", "claude-haiku-5-5")


# Where question, feedback and spend records go: "files" (data/*.jsonl, the default) or "firestore".
LOG_BACKEND = os.getenv("LOG_BACKEND", "files").lower()
LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "90"))  # Firestore deletes records after this
APP_VERSION = os.getenv("APP_VERSION", "")  # the git commit, set by deploy/deploy.sh


def ai_enabled() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
