"""College events from the U's Trumba calendar (the one in price.utah.edu's footer).

Trumba publishes each calendar as a public JSON feed and accepts a date window:
https://www.trumba.com/calendars/uu-college-of-engineering.json?startdate=20261101&days=30
"""

import html
import re
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

from . import config

FEED = "https://www.trumba.com/calendars/{calendar}.json"
TAG_RE = re.compile(r"<[^>]+>")
_cache: dict[tuple, tuple[float, list]] = {}
_http = httpx.AsyncClient(headers={"User-Agent": config.USER_AGENT}, timeout=20)


def today() -> date:
    return datetime.now(ZoneInfo(config.TIMEZONE)).date()


def _clean(value: str) -> str:
    text = TAG_RE.sub(" ", html.unescape(value or "").replace("<br />", "\n").replace("<br>", "\n"))
    return re.sub(r"[ \t ]+", " ", text).strip()


async def fetch_window(start: date, days: int) -> list[dict]:
    key = (config.TRUMBA_CALENDAR, start.isoformat(), days)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < config.EVENTS_CACHE_TTL:
        return hit[1]
    resp = await _http.get(FEED.format(calendar=config.TRUMBA_CALENDAR),
                           params={"startdate": start.strftime("%Y%m%d"), "days": days})
    resp.raise_for_status()
    events = resp.json()
    _cache[key] = (time.time(), events)
    return events


def _room(event: dict) -> str:
    for field in event.get("customFields") or []:
        if field.get("label") == "Room Name/Number" and field.get("value"):
            return _clean(field["value"])
    return ""


def simplify(event: dict) -> dict:
    location = _clean(event.get("location", ""))
    room = _room(event)
    if room and room not in location:
        location = f"{location}, {room}" if location else room
    return {
        "title": _clean(event.get("title", "")),
        "when": _clean(event.get("dateTimeFormatted", "")) or event.get("startDateTime", ""),
        "start": event.get("startDateTime", ""),
        "location": location,
        "calendar": (event.get("categoryCalendar") or "").replace("|", " / "),
        "canceled": bool(event.get("canceled")),
        "url": event.get("permaLinkUrl") or event.get("webLink") or "",
        "description": _clean(event.get("description", "")),
    }


async def search_events(query: str = "", start: date | None = None, days: int = 14, limit: int = 15) -> list[dict]:
    """Events in [start, start+days), optionally filtered by keywords (any word may match)."""
    start = start or today()
    days = max(1, min(days, 180))
    events = [simplify(e) for e in await fetch_window(start, days)]
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2]
    if words:
        def score(e):
            hay = f"{e['title']} {e['calendar']} {e['location']} {e['description']}".lower()
            return sum(w in hay for w in words) + 2 * sum(w in e["title"].lower() for w in words)
        events = [e for e in events if score(e) > 0]
        events.sort(key=lambda e: (-score(e), e["start"]))
    return events[:limit]


def format_events(events: list[dict], start: date, days: int, query: str) -> str:
    window = f"{start:%B %-d, %Y} + {days} days"
    if not events:
        what = f" matching “{query}”" if query else ""
        return (f"No events{what} on the Price College of Engineering calendar for {window}. "
                f"The full calendar is at https://www.price.utah.edu/calendar")
    lines = [f"Price College of Engineering calendar, {window} (today is {today():%A, %B %-d, %Y}):"]
    for i, e in enumerate(events, 1):
        lines.append(
            f"\n[{i}] {e['title']}{'  ** CANCELED **' if e['canceled'] else ''}\n"
            f"When: {e['when']}\n"
            + (f"Where: {e['location']}\n" if e["location"] else "")
            + (f"Calendar: {e['calendar']}\n" if e["calendar"] else "")
            + f"Link: {e['url']}\n"
            + (f"Details: {e['description'][:350]}{'…' if len(e['description']) > 350 else ''}" if e["description"] else "")
        )
    return "\n".join(lines)
