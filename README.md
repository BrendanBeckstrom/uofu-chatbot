# Price Engineering Assistant (proof of concept)

An AI chat assistant for [price.utah.edu](https://www.price.utah.edu/), the John and Marcia Price College of
Engineering website. It answers visitors' questions from the college's and departments' public pages, handbooks
and events calendar, and links its sources. It runs on Claude Haiku 5.5.

**Status:** a password-protected beta for internal testing, at https://uofuchatbot.web.app (ask the project lead
for the password). It isn't on the college website yet; [docs/GOING_LIVE.md](docs/GOING_LIVE.md) covers what
that takes.

**Latest reports:**
- [Beta evaluation, October 2026](docs/reports/beta-evaluation-2026-10-21.pdf)
- [Site content audit, October 2026](audit/results/2026-10-21/site-content-audit-2026-10-21.pdf)
- [all reports](docs/reports/)

## How it works

```
 price.utah.edu + 7 department sites           Trumba calendar (college events)
 (WordPress REST API, public & read-only)       (public JSON feed)
        │                                              │
        │ build once, then "what changed?" checks      │ read live, cached 15 min
        ▼                                              │
 app/sync.py ──► data/docs.json ──► app/index.py       │
 (+ handbook PDFs)                   BM25 search       │
                                        │              │
 visitor ─► web/widget.js ─SSE─► app/server.py ─► app/chat.py
                                                  1. search the index for the question
                                                  2. Claude (Haiku 5.5) answers, calling tools as needed:
                                                       search_site(query)     index, new wording
                                                       fetch_page(url)        live read of any *.utah.edu page
                                                       get_events(query, …)   live college calendar
                                                  3. stream the answer back with dated sources
```

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) follows one question from the widget to the answer.

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # first time only; Python 3.11+ (CI uses 3.14)
brew install pango                          # first time only: draws the chat-summary PDF (on Linux: see Dockerfile)
cp .env.example .env                        # then paste an Anthropic API key into ANTHROPIC_API_KEY

.venv/bin/python -m app.sync build          # index the 8 sites (polite crawl, about 15-25 minutes, once)
.venv/bin/python -m app.sync documents      # handbooks, plans and flowcharts (after build)
.venv/bin/uvicorn app.server:app --reload --port 8000
```

Then open http://localhost:8000, a demo copy of the college landing page with the working widget. After the
first build, the server keeps the index current by itself. Without an API key, the widget runs in
*search-only mode*: it shows the most relevant pages instead of an AI answer.

Handy while working:
- http://localhost:8000/api/search?q=scholarships shows raw search results.
- `.venv/bin/python -m app.sync status` shows what was checked when.
- Run exactly one server process. Rate limits, conversations and the answer cache live in its memory.

## Documentation

| Doc | For |
| --- | --- |
| [docs/MAKING_CHANGES.md](docs/MAKING_CHANGES.md) | **start here to change something:** the routine for every change, recipes for common ones, rebuilding the index |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | how the code works, the protections (rate limits, spending cap, scope gate), data files, tests and evals |
| [docs/DEPLOY.md](docs/DEPLOY.md) | the hosted beta: Cloud Run, Firebase Hosting, the beta password, reading the logs |
| [docs/GOING_LIVE.md](docs/GOING_LIVE.md) | what's beta-only, the decisions still open, embedding on the college site, hosting options, questions for university offices |
| [docs/SITE_AUDIT.md](docs/SITE_AUDIT.md) | the site content audit: outdated or conflicting information on the college's own sites |
| [docs/reports/](docs/reports/) | finished evaluation and research reports |
| [CLAUDE.md](CLAUDE.md) | rules and commands for Claude Code sessions in this repo |

## Checks

Six offline tests and a check of the eval graders run free on every pull request (CI). An answer eval with real API calls measures accuracy
(about $0.18 a pass). [docs/MAKING_CHANGES.md](docs/MAKING_CHANGES.md#the-routine-for-every-change) lists the
commands and how to read the results.
