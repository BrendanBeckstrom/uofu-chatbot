"""Abuse and cost protection for the public chat endpoint.

Layers (all in-process; docs/SECURITY.md covers the multi-server version):
  - who is asking:    a signed per-browser token, plus the client IP (proxy-aware, IPv6 per /64)
  - how often:        sliding-window limits per token, per IP (looser, for shared campus Wi-Fi), and global
  - how many at once: one answer at a time per client, a small number overall
  - how much money:   a daily dollar cap with reservations; when hit, answers fall back to search results
"""

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import time
from collections import defaultdict, deque
from datetime import date
from pathlib import Path

from . import config
from .pricing import cost_usd


# ---- identity -----------------------------------------------------------------------------------

def client_ip(request) -> str:
    """The client's IP. Proxy headers are trusted only when TRUST_PROXY is set, because anyone can
    send a fake X-Forwarded-For straight to the server. IPv6 is grouped by /64 (one user's block)."""
    ip = request.client.host if request.client else "unknown"
    if config.TRUST_PROXY:
        cf = request.headers.get("cf-connecting-ip")
        xff = request.headers.get("x-forwarded-for")
        if cf:
            ip = cf.strip()
        elif xff:
            # The proxy appends the address it saw; the right-most entry is the one it vouches for.
            ip = xff.split(",")[-1].strip()
    try:
        if ipaddress.ip_address(ip).version == 6:
            return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    except ValueError:
        pass
    return ip


client_key = client_ip  # back-compat name


def _load_secret() -> bytes:
    """HMAC key for browser tokens: from the environment, or generated once and kept in data/."""
    if os.getenv("CHAT_TOKEN_SECRET"):
        return os.environ["CHAT_TOKEN_SECRET"].encode()
    path = config.DATA_DIR / ".token_secret"
    try:
        return path.read_bytes()
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_bytes(32)
        path.write_bytes(key)
        path.chmod(0o600)
        return key


_SECRET = _load_secret()


def issue_token() -> str:
    """A random browser ID with an expiry, signed so clients can't forge or extend it."""
    tid = secrets.token_urlsafe(12)
    expires = int(time.time() + config.TOKEN_TTL_HOURS * 3600)
    sig = hmac.new(_SECRET, f"{tid}.{expires}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{tid}.{expires}.{sig}"


def verify_token(token: str | None) -> str | None:
    """Returns the token's ID if it's genuine and unexpired, else None."""
    try:
        tid, expires, sig = (token or "").split(".")
        good = hmac.new(_SECRET, f"{tid}.{expires}".encode(), hashlib.sha256).hexdigest()[:32]
        if hmac.compare_digest(sig, good) and int(expires) > time.time():
            return tid
    except ValueError:
        pass
    return None


# ---- rate limits --------------------------------------------------------------------------------

class SlidingWindowLimiter:
    """Several (max_hits, window_seconds) rules per key, e.g. 5/minute and 30/hour."""

    MAX_KEYS = 100_000  # memory bound if someone rotates IPs or tokens

    def __init__(self, rules: list[tuple[int, float]], name: str = ""):
        self.rules = sorted(rules, key=lambda r: r[1])
        self.name = name
        self.longest = max(w for _, w in rules)
        self.hits: dict[str, deque] = defaultdict(deque)
        self.clock = time.monotonic  # tests swap in a frozen clock
        self._last_sweep = self.clock()

    def peek(self, key: str) -> float | None:
        """Seconds to wait if a hit now would exceed a rule, else None. Records nothing."""
        now = self.clock()
        q = self.hits.get(key)
        if not q:
            return None
        while q and now - q[0] > self.longest:
            q.popleft()
        for limit, window in self.rules:
            recent = [t for t in q if now - t <= window]
            if len(recent) >= limit:
                return max(1.0, window - (now - recent[0]))
        return None

    def hit(self, key: str):
        now = self.clock()
        if key not in self.hits and len(self.hits) >= self.MAX_KEYS:
            self._sweep(now, force=True)
        self.hits[key].append(now)
        self._sweep(now)

    def check(self, key: str) -> float | None:
        """Record a hit and return None, or return seconds to wait (recording nothing)."""
        wait = self.peek(key)
        if wait is None:
            self.hit(key)
        return wait

    def _sweep(self, now: float, force: bool = False):
        if not force and now - self._last_sweep < 300:
            return
        self._last_sweep = now
        for key in [k for k, q in self.hits.items() if not q or now - q[-1] > self.longest]:
            del self.hits[key]


def check_all(pairs: list[tuple["SlidingWindowLimiter", str]]) -> tuple[float, str] | None:
    """Check several limiters; record a hit in all of them only if none is exceeded."""
    for limiter, key in pairs:
        wait = limiter.peek(key)
        if wait:
            return wait, limiter.name
    for limiter, key in pairs:
        limiter.hit(key)
    return None


class ConcurrencyGuard:
    """Caps answers being generated at once, overall and per client."""

    def __init__(self, total: int, per_client: int):
        self.total, self.per_client = total, per_client
        self.active: dict[str, int] = defaultdict(int)
        self.count = 0

    def try_acquire(self, key: str) -> str | None:
        if self.count >= self.total:
            return "global"
        if self.active[key] >= self.per_client:
            return "client"
        self.active[key] += 1
        self.count += 1
        return None

    def release(self, key: str):
        self.count = max(0, self.count - 1)
        self.active[key] = max(0, self.active[key] - 1)
        if not self.active[key]:
            del self.active[key]


# ---- money --------------------------------------------------------------------------------------

class SpendGuard:
    """Daily dollar cap on model usage, persisted so a restart doesn't reset the day's total.
    Each answer reserves a worst-case amount up front and settles the real cost afterward."""

    def __init__(self, daily_cap: float, path: Path):
        self.daily_cap, self.path = daily_cap, path
        try:
            saved = json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            saved = {}
        self.day = saved.get("day", "")
        self.spent = float(saved.get("spent", 0)) if self.day == date.today().isoformat() else 0.0
        self.reserved = 0.0
        self.tripped_reason: str | None = None  # e.g. the Anthropic workspace limit was hit

    def _roll(self):
        today = date.today().isoformat()
        if self.day != today:
            self.day, self.spent, self.tripped_reason = today, 0.0, None

    def exhausted(self) -> bool:
        self._roll()
        if self.tripped_reason:
            return True
        return self.daily_cap > 0 and self.spent + self.reserved >= self.daily_cap

    def reserve(self, amount: float = config.RESERVE_PER_ANSWER_USD) -> bool:
        """Hold a worst-case amount for one answer; refuse if that would cross the cap."""
        if self.exhausted():
            return False
        if self.daily_cap > 0 and self.spent + self.reserved + amount > self.daily_cap + 1e-9:
            return False
        self.reserved += amount
        return True

    def release(self, amount: float = config.RESERVE_PER_ANSWER_USD):
        self.reserved = max(0.0, self.reserved - amount)

    def trip(self, reason: str):
        """An upstream spend limit was hit: stop calling the API for the rest of the day."""
        self._roll()
        self.tripped_reason = reason

    def record(self, usage: dict, model: str) -> float:
        self._roll()
        dollars = cost_usd(usage, model)
        self.spent += dollars
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"day": self.day, "spent": round(self.spent, 6)}))
        except OSError:
            pass
        return dollars

    def status(self) -> dict:
        self._roll()
        return {"day": self.day, "spent_usd": round(self.spent, 4), "reserved_usd": round(self.reserved, 4),
                "daily_cap_usd": self.daily_cap, "exhausted": self.exhausted(),
                "tripped_reason": self.tripped_reason}


# ---- shared instances ---------------------------------------------------------------------------

token_limiter = SlidingWindowLimiter(config.TOKEN_LIMITS, "per-browser")
ip_limiter = SlidingWindowLimiter(config.IP_LIMITS, "per-IP")
issue_limiter = SlidingWindowLimiter(config.TOKEN_ISSUE_LIMITS, "token-issue")
global_limiter = SlidingWindowLimiter(config.GLOBAL_CHAT_LIMITS, "global")
search_limiter = SlidingWindowLimiter(config.SEARCH_LIMITS, "search")
events_limiter = SlidingWindowLimiter(config.EVENTS_LIMITS, "events")
feedback_limiter = SlidingWindowLimiter(config.FEEDBACK_LIMITS, "feedback")
concurrency = ConcurrencyGuard(config.MAX_CONCURRENT_ANSWERS, config.MAX_CONCURRENT_PER_CLIENT)
spend = SpendGuard(config.DAILY_BUDGET_USD, config.DATA_DIR / "spend.json")
