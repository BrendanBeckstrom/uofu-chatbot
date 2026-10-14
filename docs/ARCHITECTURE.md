# How the code works

This explains how the Price Engineering Assistant is put together, for whoever maintains it next. Read the
[README](../README.md) first for setup. For step-by-step changes ("how do I change X?"), see
[MAKING_CHANGES.md](MAKING_CHANGES.md). Security and cost controls are in [SECURITY.md](SECURITY.md).

The code keeps comments to a minimum on purpose; this document and those two are where the explanations live.

## The big picture

The assistant has three parts:

1. **A local copy of the college's websites.** `app/sync.py` copies every published page and news post from
   price.utah.edu and the seven department sites through their public WordPress API. `app/documents.py` adds
   the departments' handbooks, 4-year plans and flowcharts (PDFs) and the CS handbook website. Everything
   lands in `data/docs.json`, and `app/index.py` builds a keyword search index from it.
2. **An answer loop.** For each question, `app/chat.py` searches that index, then lets Claude (Haiku 5.5)
   answer. Claude can search again, read any utah.edu page or PDF live, and check the college events
   calendar. The answer streams back with links to the pages used.
3. **A chat widget.** `web/widget.js` is one self-contained script that any page can include. It draws the
   chat window and talks to the server.

`app/server.py` (FastAPI) connects them, and `app/guard.py` sits in front of the answer loop to stop abuse and
cap spending.

## What happens when someone asks a question

1. **Widget** (`web/widget.js`): on first use it gets a signed browser token from `POST /api/token`. It sends
   `POST /api/chat` with the message, the session ID and, if the visitor picked one on the welcome screen,
   their audience (`prospective` or `current`). The token is stored in `localStorage`, the conversation in
   `sessionStorage`.
2. **Server** (`app/server.py`, `chat()`):
   - Checks the token, then the rate limits per browser, per IP and overall (`guard.check_all`), then the
     limit on answers running at once.
   - Kicks off a background "has the site changed?" check if one is due (`Syncer.maybe_sync`).
   - Streams the answer as server-sent events, with a 90-second ceiling.
3. **Answer loop** (`app/chat.py`, `ChatEngine._answer`):
   1. With no API key, or no credits, it returns search results without AI (`_offline_answer`).
   2. It enforces the per-conversation caps (turns, context size) and reserves money from the daily budget
      (`guard.spend`).
   3. A repeated first question is served from a 6-hour answer cache.
   4. It searches the index **and** asks the scope gate (`app/scope.py`) about the message at the same time.
      The gate is a tiny Haiku call that labels the message `in_scope`, `out_of_scope`, `coursework`,
      `injection` or `crisis`. Every label except `in_scope` gets a fixed, pre-written reply and stops there.
      Crisis messages get support resources and are not written to the log.
   5. Claude gets the system prompt (`SYSTEM_TEMPLATE`), the conversation so far, and this turn's search
      results. It may call up to 3 rounds of tools:
      - `search_site`: the local index
      - `fetch_page`: a live read of any utah.edu page, or an indexed PDF a few pages at a time
      - `get_events`: the live college calendar

      The last round has tools switched off and a nudge to write the answer.
   6. While text streams out, it watches for the prompt-leak canary. If the canary shows up, the answer is
      replaced and the turn is dropped.
   7. It records tokens and cost (`data/usage.jsonl`, `data/spend.json`) and sends the source links.
4. **Widget** shows what the bot is doing ("Searching…", "Reading…"), then renders the streamed answer (only
   utah.edu links are clickable), source chips with dates, and thumbs up/down.

## Where the knowledge comes from

### Website pages and news (`app/sync.py`, `app/wp.py`, `app/store.py`)

- **Build** (`python -m app.sync build`) downloads every published page and post, 100 per request, waiting 10
  seconds between requests to the same site as each site's `robots.txt` asks. Raw API responses are kept in
  `data/raw/<site>/` so the index can be rebuilt offline (`--offline`).
- **Update** asks each site for its single most recently edited page and post (2 tiny requests). It then
  downloads only items edited after the last check (`modified_after`). The server does this in the background
  when a question arrives and the last check is over 30 minutes old.
- **Reconcile** runs weekly and finds pages that were deleted or unpublished by comparing ID lists.
- **Thin pages:** some pages build their content from theme blocks, so the API returns almost nothing. For
  those, the build reads the rendered HTML instead (`_fill_thin`).
- WPBakery page-builder markup (`[vc_row]…`) is stripped in `app/extract.py`. Base64 "raw HTML" blocks are
  decoded.

### Planning documents (`app/documents.py`)

Handbooks, 4-year plans, flowcharts and requirement checklists are mostly PDFs. They answer the "plan my
schedule" questions.

- **Finding them:** it scans the HTML of the pages already saved by the site sync for links to `.pdf` files.
  Many links are buttons whose URL is stored URL-encoded in page-builder markup (`link="url:%2F…pdf"`), so it
  looks for both forms. Nothing extra is requested from the sites to find them.
- **Choosing which ones** (`select_pdfs`):
  - A PDF is kept if its name matches `INCLUDE` (handbook, plan, flowchart, checklist, requirements…), or
    if a page linking to it does (a page titled "Flowcharts", for example). Names matching `EXCLUDE` are
    dropped either way: lesson plans, maps, sample exams, exam study guides, forms…
  - The year must be `MIN_YEAR` (5 years back) or later. The year is read from the name ("2026-2027",
    "26-27", "CY 26") or, failing that, from the upload folder.
  - Only the newest version of each document is kept: "2025-2026-Civil-Flowchart" and
    "2026-2027-Civil-Flowchart" belong to the same family (`_family`). Plans for different catalog years
    with different names (Mechanical Engineering's "4-year-Flow-Chart-…-21-22" and "4Y-Trad-Calc-CY-26")
    are all kept on purpose, because students follow the catalog year they started under.
  - URLs in `SKIP_URLS` are always left out.
- **The CS handbook** is its own website (handbook.cs.utah.edu). The newest year of each program's handbook
  is crawled from its site map.
- **Reading PDFs** (`app/extract.py`):
  - `pypdf` runs in layout mode, so a semester grid stays as "fall course | spring course" on one line.
  - Each page is stored with a `[Page N]` marker. A PDF is indexed page by page, so search results say
    which page matched, and `fetch_page` returns a few pages at a time instead of a whole 40-page handbook.
  - **Degree plans** print each year's label ("Freshman year (28 credits)") beside the middle of its rows,
    so in flat text a year's first row lands above its label. `_label_plan_years` adds up the credits row
    by row to find where each year really starts, then writes a `[Freshman year (28 credits)]` heading
    above it. Without this, the model put sophomore courses in freshman year.
  - The original PDFs are kept in `data/raw/documents/`. When `EXTRACTOR_VERSION` goes up, saved files are
    re-read offline instead of downloaded again.
  - Scanned-image PDFs have no text and can't be read.
- **Keeping them current:** each file's `ETag`/`Last-Modified` is saved. The weekly refresh asks "has this
  changed?", which costs one tiny request for an unchanged file. Run it by hand with
  `python -m app.sync documents`.

### Search (`app/index.py`)

The index is a BM25 keyword index over ~1,400-character chunks:

- A match in a page's title or URL counts extra.
- News posts are weighted a little below evergreen pages.
- At most 2 results come from the same folder, so a dozen near-empty sibling pages can't crowd out the
  overview page.
- `ALIASES` expands shorthand like "ECE" or "dorm".

The server rebuilds the index when `data/docs.json` changes on disk.

### Live reads (`app/live.py`) and events (`app/events.py`)

`fetch_page` reads any `*.utah.edu` page or PDF:

- It checks that the host resolves to a public address, re-checks every redirect, caps the size, and caches
  results for an hour.
- An indexed PDF is served from the index without a network request.

The calendar comes from the college's public Trumba JSON feed (`uu-college-of-engineering`), cached for 15
minutes.

## Usage statistics (`app/analytics.py`)

Every answer, decline and error adds one line to `data/usage.jsonl`:

- an anonymous user ID (a hash of the browser token, so "people per day" can be counted without cookies or
  trackers)
- the redacted question
- the scope label and a topic, both from the scope gate's single call
- the audience
- whether the answer admitted it couldn't find something (`gap`)
- seconds and cost

`python -m app.analytics --days 30` turns this into a report: people per day, questions, error rate, topics,
the most-asked questions, and recent questions it couldn't fully answer (content to add or surface on the
site). `--json` gives the same numbers for a dashboard. Eval runs log to their own results folder, so they
don't count as visitors. When the app moves to a host, these lines can go to a database or Firestore
instead; the report only needs the same fields.

## Data files

Everything in `data/` is generated and git-ignored. It's safe to delete; rebuild with `python -m app.sync
build` and `python -m app.sync documents`.

| Path | What | Written by |
| --- | --- | --- |
| `data/docs.json` | every indexed page, post, PDF and handbook page | sync |
| `data/sync_state.json` | per-site freshness: last check, newest edit, errors | sync |
| `data/raw/<site>/` | raw API responses and rendered HTML for thin pages | sync |
| `data/raw/documents.json` | extracted text and cache headers for each document | `app/documents.py` |
| `data/raw/documents/` | the original PDF files, for offline re-extraction | `app/documents.py` |
| `data/usage.jsonl` | one line per answer or error: anonymous user, redacted question, gate label, topic, audience, gap, tokens, cost, seconds | chat |
| `data/feedback.jsonl` | thumbs up/down with the question and answer (redacted) | server |
| `data/spend.json` | today's spend, so a restart doesn't reset the daily cap | guard |
| `data/.token_secret` | key that signs browser tokens (set `CHAT_TOKEN_SECRET` in production) | guard |

## Settings

Every setting lives in `app/config.py` and can be overridden in `.env`. `.env.example` lists them all. The
ones people change most:

- `CLAUDE_MODEL`
- `CHATBOT_EFFORT`
- `MAX_TOOL_STEPS`
- `DAILY_BUDGET_USD`
- the `*_LIMITS` rate limits
- `SYNC_TTL_MINUTES`
- `RECONCILE_DAYS`

## Tests and evals

| Command | Needs | Covers |
| --- | --- | --- |
| `python -m tests.test_chat_loop` | nothing | the answer loop with a scripted fake Claude: tools, caps, cache, refusals, the scope gate, crisis replies, PDFs, audience |
| `python -m tests.test_documents` | nothing | which PDFs get picked and how versions are matched |
| `python -m tests.test_sync` | nothing | build, change-only update and deletion check against a fake WordPress site |
| `python -m tests.test_guard` | nothing | rate limits, tokens, spend cap, request-size limits |
| `python -m tests.test_analytics` | nothing | the usage report's counts |
| `python -m evals.run selftest` | internet (calendar) | the eval graders accept good answers and reject empty ones |
| `python -m evals.run retrieval` | the local index | does the first search find the right page? |
| `python -m evals.run answers` | API key, about $0.05 a run | the real bot on every question in `evals/questions.json` |

The tests use `tests/fixtures.py`, a handful of made-up documents, so they run anywhere, including CI.

## Design decisions worth knowing

- **The system prompt is fixed for the whole conversation.** It's built once per session, with the date and
  random canary. Changing it mid-conversation would break prompt caching and Claude's saved reasoning.
- **History only grows.** A turn that fails, is refused or leaks is removed whole, so the history never holds
  a tool call without its result.
- **Empty replies.** With tools switched off on the last round, Haiku 5.5 sometimes ends without writing
  anything. The loop sends a "write your answer now" nudge (`FINAL_NUDGE`) and retries once. If it's still
  empty, the visitor gets search results instead of a blank bubble.
- **The effort setting is `CHATBOT_EFFORT`, not `CLAUDE_EFFORT`.** A shell-wide `CLAUDE_EFFORT` meant for
  another tool once ran this app at maximum effort without anyone noticing.
- **Be gentle with the department sites.** Several appear to share one server. Heavy API queries sent to all
  of them at once returned 504 errors, so keep requests sequential per site and small.
- **One server process.** Rate limits, sessions and the answer cache live in memory. Running several
  processes would split them; SECURITY.md describes the Redis version for scaling up.
- **Fallback models** are requested only when the model lists `allowed_fallback_models`. Haiku 5.5 lists
  none.
