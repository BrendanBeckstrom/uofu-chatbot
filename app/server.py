"""Web server: demo and login pages, design concepts, embeddable widget and the chat API.

Run locally:  .venv/bin/uvicorn app.server:app --reload --port 8000
Hosted, it runs on Cloud Run (docs/DEPLOY.md).
"""

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, guard, records
from .chat import ChatEngine, anon_user, log_usage
from .events import search_events, today
from .index import SearchIndex
from .privacy import redact
from .store import Store
from .sync import Syncer


def _docs_mtime() -> float:
    try:
        return config.DOCS_PATH.stat().st_mtime
    except FileNotFoundError:
        return 0.0


store = Store()
engine = ChatEngine(SearchIndex(store.docs) if store.docs else None)
_loaded_mtime = _docs_mtime()


async def rebuild_index():
    """After a background sync changed documents, swap in a fresh index."""
    global _loaded_mtime
    engine.index = await asyncio.to_thread(SearchIndex, dict(store.docs))
    _loaded_mtime = _docs_mtime()


syncer = Syncer(store, on_change=rebuild_index, log=lambda m: print(f"[sync] {m}", flush=True))
engine.on_missing = syncer.remove_url


async def reload_if_rebuilt():
    """A `python -m app.sync build/update` from the terminal rewrote docs.json: load it."""
    global _loaded_mtime
    mtime = _docs_mtime()
    if not mtime or syncer.running or mtime - _loaded_mtime < 1:
        return
    _loaded_mtime = mtime
    fresh = await asyncio.to_thread(Store)
    store.docs, store.state = fresh.docs, fresh.state
    engine.index = await asyncio.to_thread(SearchIndex, dict(store.docs))


@asynccontextmanager
async def lifespan(_app):
    yield
    await asyncio.to_thread(records.flush)
    if syncer._client:
        await syncer._client.aclose()


app = FastAPI(title="Price Engineering Assistant (POC)", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    # Local testing, plus the real site so the widget can be previewed there via the bookmarklet.
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?|https://(www\.)?price\.utah\.edu",
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Chat-Token"],
)

NO_CACHE = {"Cache-Control": "no-cache"}
ANSWER_TIMEOUT = 90  # seconds; a hung stream can't hold a concurrency slot forever


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    """Reject oversized request bodies before they're parsed."""
    if request.method == "POST":
        length = request.headers.get("content-length")
        if length is None and request.url.path not in ("/api/token", "/api/sync"):
            return JSONResponse({"detail": "Content-Length required."}, status_code=411)
        if length is not None and (not length.isdigit() or int(length) > config.MAX_BODY_BYTES):
            return JSONResponse({"detail": "Request too large."}, status_code=413)
    return await call_next(request)


def too_many(message: str, retry_after: float, status: int = 429) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=status,
                        headers={"Retry-After": str(int(retry_after + 0.999)), "Cache-Control": "no-store"})


def wait_text(seconds: float) -> str:
    if seconds < 90:
        return f"{int(seconds + 0.999)} seconds"
    if seconds < 5400:
        return f"{int(seconds / 60 + 0.999)} minutes"
    return f"{seconds / 3600:.0f} hours"


def light_limit(request: Request, limiter: guard.SlidingWindowLimiter):
    """Search, events and feedback: cheap, but still capped so they can't be hammered."""
    wait = limiter.check(guard.client_ip(request))
    if wait:
        raise HTTPException(429, f"Too many requests. Try again in {wait_text(wait)}.",
                            headers={"Retry-After": str(int(wait + 0.999)), "Cache-Control": "no-store"})


def local_only(request: Request):
    if not request.client or request.client.host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(403, "Only available from this machine.")


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=config.MAX_MESSAGE_CHARS)
    session_id: str | None = Field(default=None, max_length=64)
    audience: Literal["prospective", "current"] | None = None


class FeedbackIn(BaseModel):
    session_id: str | None = Field(default=None, max_length=64)
    question_id: str = Field(default="", max_length=40)
    rating: int = Field(ge=-1, le=1)
    question: str = Field(default="", max_length=1500)
    answer: str = Field(default="", max_length=8000)
    comment: str = Field(default="", max_length=1000)


@app.post("/api/token")
async def token(request: Request):
    """A signed per-browser token. The widget gets one on first use and sends it with each message.
    With BETA_PASSWORD set, the login page sends {"password": ...} and only the right one gets a token."""
    ip = guard.client_ip(request)
    if config.BETA_PASSWORD:
        wait = guard.login_limiter.peek(ip)  # only wrong passwords count, so a room of testers can sign in
        if wait:
            return too_many(f"Too many wrong passwords. Try again in {wait_text(wait)}.", wait)
        raw = await request.body()
        try:
            attempt = str(json.loads(raw).get("password", "")) if 0 < len(raw) <= 1024 else ""
        except (ValueError, AttributeError):
            attempt = ""
        if not guard.password_ok(attempt):
            if attempt:
                guard.login_limiter.hit(ip)
            return JSONResponse({"detail": "wrong_password" if attempt else "password_required"},
                                status_code=401, headers={"Cache-Control": "no-store"})
    wait = guard.issue_limiter.check(ip)
    if wait:
        return too_many(f"Too many new sessions from this network. Try again in {wait_text(wait)}.", wait)
    return JSONResponse({"token": guard.issue_token(), "ttl_hours": config.TOKEN_TTL_HOURS},
                        headers={"Cache-Control": "no-store"})


@app.post("/api/chat")
async def chat(body: ChatIn, request: Request):
    tid = guard.verify_token(request.headers.get("x-chat-token"))
    if not tid:
        return JSONResponse({"detail": "token_required"}, status_code=401, headers={"Cache-Control": "no-store"})
    ip = guard.client_ip(request)
    limited = guard.check_all([(guard.token_limiter, tid), (guard.ip_limiter, ip), (guard.global_limiter, "all")])
    if limited:
        wait, which = limited
        if which == "global":
            return too_many("The assistant is getting a lot of questions right now. Please try again shortly.", wait)
        return too_many(f"You've sent a lot of messages. Please try again in {wait_text(wait)}.", wait)
    key = tid
    busy = guard.concurrency.try_acquire(key)
    if busy:
        msg = ("Please wait for the current answer to finish." if busy == "client"
               else "The assistant is busy right now. Please try again in a few seconds.")
        return too_many(msg, 5, status=429 if busy == "client" else 503)

    await reload_if_rebuilt()
    if config.AUTO_SYNC:
        syncer.maybe_sync()  # background "what changed?" check if the last one is older than SYNC_TTL_MINUTES

    async def events():
        def sse(ev):
            name = ev.pop("event")
            return f"event: {name}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
        try:
            async with asyncio.timeout(ANSWER_TIMEOUT):
                async for ev in engine.answer(body.session_id, body.message.strip(), body.audience, user=tid):
                    yield sse(ev)
        except TimeoutError:
            log_usage(body.message, {"error": "timeout", "user": anon_user(tid)}, ANSWER_TIMEOUT, 0)
            yield sse({"event": "error", "text": "That took too long. Please try again."})
            yield sse({"event": "done"})
        finally:
            guard.concurrency.release(key)
            try:
                await asyncio.to_thread(records.flush)  # before the response ends and Cloud Run pauses the CPU
            except asyncio.CancelledError:
                pass

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/reset")
async def reset(body: dict):
    engine.sessions.reset(str(body.get("session_id", "")))
    return {"ok": True}


@app.post("/api/feedback")
async def feedback(body: FeedbackIn, request: Request):
    tid = guard.verify_token(request.headers.get("x-chat-token"))
    if not tid:
        return JSONResponse({"detail": "token_required"}, status_code=401, headers={"Cache-Control": "no-store"})
    light_limit(request, guard.feedback_limiter)
    fields = body.model_dump()
    fields["session_id"] = (fields["session_id"] or "")[:8]
    ts = records.now_local()
    records.save("feedback", {"id": records.new_id("f"), "ts": ts, "day": ts[:10], "user": anon_user(tid),
                              **{k: redact(v) if isinstance(v, str) else v for k, v in fields.items()}})
    await asyncio.to_thread(records.flush)
    return {"ok": True}


@app.get("/api/status")
async def status():
    await reload_if_rebuilt()
    return {
        "ai_enabled": engine.client is not None,
        "login_required": bool(config.BETA_PASSWORD),
        "logs": config.LOG_BACKEND,
        "ai_issue": "daily_budget" if guard.spend.exhausted() else await engine.check_health(),
        "spend": guard.spend.status(),
        "scope_gate": config.SCOPE_GATE,
        "model": config.MODEL if engine.client else None,
        "index": engine.index.stats() if engine.index else None,
        "sync": {"running": syncer.running, "ttl_minutes": config.SYNC_TTL_MINUTES, "sites": syncer.status()},
        "events_calendar": config.TRUMBA_CALENDAR,
    }


@app.post("/api/sync")
async def sync_now(request: Request, reconcile: bool = False):
    """Run a change check right now (this machine only): curl -X POST localhost:8000/api/sync"""
    local_only(request)
    if syncer.running:
        return {"started": False, "reason": "a sync is already running"}
    results = await syncer.sync_all(reconcile=reconcile)
    return {"changes": results}


@app.get("/api/search")
async def search(request: Request, q: str, k: int = 8):
    """Debug view of raw retrieval, handy for tuning: /api/search?q=graduate+admissions"""
    light_limit(request, guard.search_limiter)
    q = q[:config.MAX_MESSAGE_CHARS]
    await reload_if_rebuilt()
    return await engine.search(q, k=min(k, 20))


@app.get("/api/events")
async def events_feed(request: Request, q: str = "", days: int = 14, limit: int = 15):
    """Upcoming events from the college calendar (also used by the demo page footer)."""
    light_limit(request, guard.events_limiter)
    q = q[:200]
    try:
        return await search_events(q, today(), max(1, min(days, 180)), limit=min(limit, 50))
    except Exception:
        raise HTTPException(502, "The events calendar couldn't be reached.")


@app.get("/api/news")
async def news(n: int = 4):
    return engine.index.latest_posts(min(n, 12)) if engine.index else []


@app.get("/")
async def home():
    return FileResponse(config.WEB_DIR / "index.html", headers=NO_CACHE)


@app.get("/designs")
async def designs():
    return FileResponse(config.WEB_DIR / "designs.html", headers=NO_CACHE)


@app.get("/login.html")
async def login_page():
    return FileResponse(config.WEB_DIR / "login.html", headers=NO_CACHE)


@app.get("/config.js")
async def page_config():
    """Pages served from here call this same server. deploy/deploy.sh writes the Firebase Hosting copy,
    which points at Cloud Run instead."""
    return Response('window.PRICE_ASSISTANT_API = "";\n', media_type="application/javascript", headers=NO_CACHE)


@app.get("/widget.js")
async def widget():
    return FileResponse(config.WEB_DIR / "widget.js", media_type="application/javascript", headers=NO_CACHE)


@app.get("/wake.js")
async def wake():
    return FileResponse(config.WEB_DIR / "wake.js", media_type="application/javascript", headers=NO_CACHE)


app.mount("/static", StaticFiles(directory=config.WEB_DIR), name="static")
