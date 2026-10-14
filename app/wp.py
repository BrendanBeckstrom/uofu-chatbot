"""Read-only client for the public WordPress REST API, polite per host.

Only published-content endpoints are used (/wp/v2/pages, /wp/v2/posts). The API index also
lists admin routes; those need a login and this client never calls them.
"""

import asyncio
import json
import time
import urllib.robotparser
from urllib.parse import urlparse

import httpx

from . import config

FIELDS = "id,link,title,content,date,modified,type"


class Blocked(Exception):
    pass


class PoliteClient:
    """One shared HTTP client; requests to the same host are spaced at least `delay` seconds apart."""

    def __init__(self, delay: float, transport: httpx.AsyncBaseTransport | None = None):
        self.delay = delay
        self.http = httpx.AsyncClient(headers={"User-Agent": config.USER_AGENT}, timeout=90,
                                      follow_redirects=True, transport=transport)
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}
        self.requests = 0

    async def get(self, url: str, retries: int = 2, headers: dict | None = None, **params) -> httpx.Response:
        """GET with per-host spacing; timeouts, connection errors and 5xx are retried with backoff."""
        host = urlparse(url).hostname
        for attempt in range(retries + 1):
            async with self._locks.setdefault(host, asyncio.Lock()):
                wait = self._last.get(host, 0) + self.delay * (1 + attempt) - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    resp = await self.http.get(url, params=params or None, headers=headers)
                except (httpx.TimeoutException, httpx.TransportError):
                    if attempt == retries:
                        raise
                    continue
                finally:
                    self._last[host] = time.monotonic()
                    self.requests += 1
            if resp.status_code < 500 or attempt == retries:
                break
        if resp.status_code == 304:  # "not modified" answer to a conditional request; httpx would raise on it
            return resp
        if "html" in resp.headers.get("content-type", "") and "Attention Required! | Cloudflare" in resp.text[:3000]:
            raise Blocked(f"{host} blocked the request (Cloudflare). Check the User-Agent.")
        resp.raise_for_status()
        return resp

    async def aclose(self):
        await self.http.aclose()


def parse_wp_json(text: str):
    """A plugin on price.utah.edu echoes HTML before the REST JSON; skip to the real payload."""
    decoder = json.JSONDecoder()
    start = text.find('[{"id"')
    if start == -1:
        start = text.find("[")
    while start != -1:
        try:
            data, _ = decoder.raw_decode(text, start)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
        start = text.find("[", start + 1)
    raise ValueError("no JSON array found in REST response")


async def robots_ok(client: PoliteClient, base: str) -> float | None:
    """Raise if robots.txt disallows the REST API; return its crawl delay if it sets one."""
    rp = urllib.robotparser.RobotFileParser()
    try:
        resp = await client.http.get(f"{base}/robots.txt")
        rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
    except httpx.HTTPError:
        return None
    if not rp.can_fetch(config.USER_AGENT, f"{base}/wp-json/wp/v2/pages"):
        raise Blocked(f"robots.txt on {base} disallows the REST API for this user agent")
    return rp.crawl_delay(config.USER_AGENT)


async def fetch_all(client: PoliteClient, base: str, kind: str, modified_after: str | None = None,
                    fields: str = FIELDS, on_page=None) -> list[dict]:
    """Every published item of a kind (pages/posts), or only those modified after a timestamp."""
    items, page, total_pages = [], 1, 1
    while page <= total_pages:
        params = {"per_page": 100, "page": page, "_fields": fields, "orderby": "modified", "order": "desc"}
        if modified_after:
            params["modified_after"] = modified_after
        resp = await client.get(f"{base}/wp-json/wp/v2/{kind}", **params)
        total_pages = int(resp.headers.get("X-WP-TotalPages", 1) or 1)
        items.extend(parse_wp_json(resp.text))
        if on_page:
            on_page(kind, page, total_pages, len(items))
        page += 1
    return items


async def newest_modified(client: PoliteClient, base: str, kind: str) -> str | None:
    """The cheap freshness probe: one ~200 byte request for the most recently edited item."""
    resp = await client.get(f"{base}/wp-json/wp/v2/{kind}", per_page=1, orderby="modified",
                            order="desc", _fields="id,modified")
    items = parse_wp_json(resp.text)
    return items[0]["modified"] if items else None
