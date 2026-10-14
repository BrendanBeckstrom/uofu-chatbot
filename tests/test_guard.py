"""Abuse and cost protection: limits, concurrency, the daily budget, proxy headers, and the server's 429s.

Run:  .venv/bin/python -m tests.test_guard
"""

import tempfile
import time
from pathlib import Path
from types import SimpleNamespace as NS

from fastapi.testclient import TestClient

from app import config, guard


def fake_request(ip, headers=None):
    return NS(client=NS(host=ip), headers={k.lower(): v for k, v in (headers or {}).items()})


def main():
    # Sliding windows: the per-minute rule trips first and says how long to wait.
    lim = guard.SlidingWindowLimiter([(3, 60), (5, 3600)])
    assert [lim.check("a") for _ in range(3)] == [None, None, None]
    wait = lim.check("a")
    assert wait and 1 <= wait <= 60, wait
    assert lim.check("b") is None, "limits are per client"
    lim.hits["a"] = type(lim.hits["a"])([time.monotonic() - 120] * 4)  # 4 hits two minutes ago
    assert lim.check("a") is None and lim.check("a") and lim.check("a") > 60, "hourly rule still applies"
    print("✓ sliding windows: per-minute and per-hour rules, per client")

    # Concurrency: per client and overall.
    cg = guard.ConcurrencyGuard(total=2, per_client=1)
    assert cg.try_acquire("x") is None and cg.try_acquire("x") == "client"
    assert cg.try_acquire("y") is None and cg.try_acquire("z") == "global"
    cg.release("x")
    assert cg.try_acquire("z") is None
    print("✓ concurrency: one answer at a time per client, capped overall")

    # Daily budget: trips at the cap, survives a restart, resets the next day.
    path = Path(tempfile.mkdtemp()) / "spend.json"
    sg = guard.SpendGuard(0.01, path)
    usage = {"input": 50_000, "output": 5_000, "cache_read": 0, "cache_write": 0}  # $0.0075 on Haiku 5.5
    assert abs(sg.record(usage, "claude-haiku-5-5") - 0.0075) < 1e-9 and not sg.exhausted()
    sg.record(usage, "claude-haiku-5-5")
    assert sg.exhausted()
    assert guard.SpendGuard(0.01, path).exhausted(), "a restart keeps today's total"
    sg.day = "2000-01-01"
    assert not sg.exhausted(), "a new day starts at zero"
    assert guard.SpendGuard(0, path).exhausted() is False, "0 means no cap"
    sg = guard.SpendGuard(0.05, Path(tempfile.mkdtemp()) / "spend.json")
    holds = [sg.reserve(0.015) for _ in range(4)]
    assert holds == [True, True, True, False], "parallel answers can't reserve past the cap"
    sg.release(0.015)
    assert sg.reserve(0.015) and sg.status()["reserved_usd"] == 0.045
    sg.trip("anthropic_spend_limit")
    assert sg.exhausted() and not sg.reserve(), "an upstream spend limit stops calls for the day"
    print("✓ daily budget: trips at the cap, reservations, upstream trips, persists, resets daily")

    # Client identity: proxy headers ignored unless TRUST_PROXY; IPv6 grouped by /64.
    spoof = fake_request("203.0.113.9", {"X-Forwarded-For": "1.2.3.4", "CF-Connecting-IP": "5.6.7.8"})
    config.TRUST_PROXY = False
    assert guard.client_ip(spoof) == "203.0.113.9", "spoofed headers must be ignored by default"
    config.TRUST_PROXY = True
    assert guard.client_ip(spoof) == "5.6.7.8"
    assert guard.client_ip(fake_request("10.0.0.1", {"X-Forwarded-For": "6.6.6.6, 198.51.100.7"})) == "198.51.100.7"
    config.TRUST_PROXY = False
    assert guard.client_ip(fake_request("2001:db8:1:2:aaaa::1")) == guard.client_ip(fake_request("2001:db8:1:2:bbbb::9"))
    print("✓ client identity: spoof-resistant by default, IPv6 grouped by /64")

    # Browser tokens: genuine ones verify; forged, tampered and expired ones don't.
    tok = guard.issue_token()
    assert guard.verify_token(tok)
    tid, exp, sig = tok.split(".")
    assert guard.verify_token(f"{tid}.{int(exp) + 9999}.{sig}") is None, "can't extend the expiry"
    assert guard.verify_token(f"other.{exp}.{sig}") is None and guard.verify_token("junk") is None
    print("✓ tokens: signed, tamper-proof, expiring")

    # check_all: a blocked request isn't counted against the other limits.
    a = guard.SlidingWindowLimiter([(1, 60)], "a")
    b = guard.SlidingWindowLimiter([(5, 60)], "b")
    assert guard.check_all([(a, "k"), (b, "k")]) is None
    assert guard.check_all([(a, "k"), (b, "k")])[1] == "a" and len(b.hits["k"]) == 1
    print("✓ layered limits: one blocked request doesn't use up the others")

    # The real server.
    from app import server
    for lim in (guard.token_limiter, guard.ip_limiter, guard.global_limiter, guard.search_limiter,
                guard.issue_limiter, guard.feedback_limiter):
        lim.hits.clear()
        lim.clock = lambda: 1_000.0  # a slow machine must not let early requests age out of the window
    server.engine.client = None  # search-only answers: no API calls in this test
    server.syncer.maybe_sync = lambda: False  # and no background sync against the real sites
    client = TestClient(server.app)
    assert client.post("/api/chat", json={"message": "tutoring"}).status_code == 401, "token required"

    def chat_as(token):
        return client.post("/api/chat", json={"message": "tutoring"}, headers={"X-Chat-Token": token})

    t1 = client.post("/api/token").json()["token"]
    codes = [chat_as(t1).status_code for _ in range(6)]
    assert codes == [200] * 5 + [429], codes  # 5 per minute per browser
    r = chat_as(t1)
    assert int(r.headers["retry-after"]) > 0 and r.headers["cache-control"] == "no-store"
    t2 = client.post("/api/token").json()["token"]
    assert chat_as(t2).status_code == 200, "another browser on the same network isn't blocked"
    print("✓ server: token required; 5/min per browser; others on the same IP unaffected")

    for _ in range(25):  # 6 + 1 + 25 = 32 requests from one IP this minute (per-IP backstop is 30)
        last = chat_as(client.post("/api/token").json()["token"])
    assert last.status_code == 429, "the per-IP backstop still catches token farming"
    assert client.post("/api/chat", content=b"x" * 20_000,
                       headers={"Content-Type": "application/json", "X-Chat-Token": t2}).status_code == 413
    guard.search_limiter.hits.clear()
    codes = [client.get("/api/search", params={"q": "advising"}).status_code for _ in range(21)]
    assert codes[:20] == [200] * 20 and codes[-1] == 429
    print("✓ server: per-IP backstop, request-size cap and search limit all hold")
    for lim in (guard.token_limiter, guard.ip_limiter, guard.global_limiter, guard.search_limiter,
                guard.issue_limiter, guard.feedback_limiter):
        lim.hits.clear()
        lim.clock = lambda: 1_000.0  # a slow machine must not let early requests age out of the window
    print("All guard checks passed.")


if __name__ == "__main__":
    main()
