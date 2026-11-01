# Price Engineering Assistant (proof of concept)

An AI chat assistant for [price.utah.edu](https://www.price.utah.edu/), the John and Marcia Price College of
Engineering website. It answers visitor questions from the college's own web content and links its sources.

- **Try the beta:** https://uofuchatbot.web.app (ask the project lead for the password)
- **Latest evaluation:** [October 2026 beta evaluation (PDF)](docs/reports/beta-evaluation-2026-10-21.pdf)
- **Latest site audit:** [October 2026 site content audit (PDF)](audit/results/2026-10-21/site-content-audit-2026-10-21.pdf)

To run it locally:

| URL | What it is |
| --- | --- |
| http://localhost:8000/ | Demo copy of the landing page with the working chat widget |
| http://localhost:8000/designs | Three design concepts plus a recommendation, for presenting |
| http://localhost:8000/api/search?q=scholarships | Raw search results, handy for tuning retrieval |

## Quick start

```bash
cd ~/Desktop/UofUChatBot
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # first time only

.venv/bin/python -m app.sync build          # index all 8 sites (polite crawl, ~15-25 min, once)
.venv/bin/uvicorn app.server:app --reload --port 8000
```

Then open http://localhost:8000. After the first build, the server keeps the index current by itself.

For anything beyond your own laptop, run a single worker with a connection cap
(`--workers 1 --limit-concurrency 100`), because the rate limits live in memory; see
[docs/SECURITY.md](docs/SECURITY.md).

**Without an API key** the widget runs in *search-only demo mode*: it shows the most relevant pages it found,
so you can test the scraping and UI right away.

**Model:** Claude Haiku 5.5 (`CLAUDE_MODEL` in `.env`). At $0.10 / $0.50 per million input / output tokens, a typical
question should cost a fraction of a cent; `data/usage.jsonl` records the real numbers. Switch to
`claude-sonnet-5-5` or `claude-opus-5-5` if the eval shows it needs more reasoning.

**To turn on AI answers:** `cp .env.example .env`, paste your key into `ANTHROPIC_API_KEY`, and restart the
server. The header dot turns green.

## How it works

```
 price.utah.edu + 7 department sites           Trumba calendar (college events)
 (WordPress REST API, public & read-only)       (public JSON feed)
        │                                              │
        │ build once, then "what changed?" checks      │ read live, cached 15 min
        ▼                                              │
 app/sync.py ──► data/docs.json ──► app/index.py       │
                 (~5k pages+posts)   BM25 search       │
                                        │              │
 visitor ─► web/widget.js ─SSE─► app/server.py ─► app/chat.py
                                                  1. search the index for the question
                                                  2. Claude (Haiku 5.5) answers, calling tools as needed:
                                                       search_site(query)     index, new wording
                                                       fetch_page(url)        live read of any *.utah.edu page
                                                       get_events(query, …)   live college calendar
                                                  3. stream the answer back with dated sources
```

### Sources

| Source | What | How it's read |
| --- | --- | --- |
| price.utah.edu | 285 pages, ~1,090 news posts | WordPress REST API, 100 items per request |
| ece, mech, bme, che, civil, mse, cs `.utah.edu` | ~1,170 pages, ~2,300 news posts | same API, same code |
| Department PDFs (~76) | handbooks, 4-year plans, flowcharts, requirement checklists | found in the saved pages, text extracted page by page |
| handbook.cs.utah.edu | the CS, Data Science and Software Development handbooks (newest year) | crawled from each handbook's site map |
| Campus office pages (8) | WUE, the Bursar's undergraduate tuition page and fee PDFs, first-generation support, the robotics minor | a fixed list, `CAMPUS_PAGES` in `app/documents.py` |
| Trumba `uu-college-of-engineering` | events, seminars, academic deadlines | public JSON feed, live per question |
| any `*.utah.edu` page or PDF | details the index lacks | live read by the `fetch_page` tool |

Every request identifies itself honestly and waits 10 seconds between requests to the same site, as each
site's `robots.txt` asks. Only published-content endpoints are used. The API also lists admin routes; those
require a login and are never called. Graduating-student profiles ("portfolio" items) are deliberately not
indexed.

### Keeping it current

The approach mirrors what support-bot vendors do (stored index plus live reads for time-sensitive
questions), but WordPress tells us what changed, so it can be much fresher than their weekly or daily
re-crawls.

1. **Change checks, only when people are asking.** When a question arrives and a site hasn't been checked
   in `SYNC_TTL_MINUTES` (default 30), the server asks each site for its most recently edited page and post.
   That's 2 requests of about 200 bytes each. If anything is newer, it fetches only those items
   (`modified_after`) and swaps in a rebuilt index. The question being asked is answered from the current
   index meanwhile, so nobody waits. No questions means zero requests.
2. **Deletions.** A deleted or unpublished page never shows up as "changed," so once every
   `RECONCILE_DAYS` (default 7) the sync also compares page IDs. A live read that 404s drops the page
   immediately.
3. **Live sources for "now."** Claude calls `get_events` for anything about events or upcoming dates, and
   re-reads a page live when its source is old or lists dates that have passed. Every search result and
   source chip shows the page's last-updated date, so stale content is visible to both Claude and the
   reader.

Manual control:

```bash
.venv/bin/python -m app.sync update      # check all sites for changes now
.venv/bin/python -m app.sync reconcile   # update + deletion check
.venv/bin/python -m app.sync documents   # handbooks, plans and flowcharts (weekly on its own)
.venv/bin/python -m app.sync status      # per-site counts, last check, newest edit, errors
curl -X POST localhost:8000/api/sync     # same check through the running server
```

Thin pages: some pages build their content from theme blocks, so the API returns a stub. The build reads
those pages' rendered HTML instead (cached in `data/raw/<site>/rendered.json`, refreshed when the page is
edited).

## Measuring accuracy

`evals/questions.json` holds real visitor questions with the page that answers each one and the facts a
correct answer must contain, verified against the sites on the date in each question's `as_of` field. Several
are deliberately time-sensitive: events, deadlines on pages that haven't been updated, and someone's current
role.

```bash
.venv/bin/python -m evals.run retrieval   # no key: does the first search find the right page?
.venv/bin/python -m evals.run selftest    # no key: graders accept reference answers, reject empty ones
.venv/bin/python -m evals.run answers     # full bot; --reps 2 to check consistency (about $0.25)
.venv/bin/python -m evals.run baseline    # no key: the college site's own search box, for comparison (~12 min)
.venv/bin/python -m evals.converse serve  # then `say` to hold a multi-turn test conversation
```

Each answer is graded with separate checks (cites an expected page, contains the required facts, avoids
known-wrong claims, mentions a real event from the live calendar, politely redirects off-topic requests).
API failures are logged separately and never counted as wrong answers. Results, full transcripts and a
`summary.json` with pass rates and their 95% ranges go to `evals/results/<timestamp>/`. Questions marked
`origin: persona-…` came from simulated-student testing and track known problems. Add your own
questions, especially ones the ambassadors hear often.

Each question has a tier ([Eval tiers](docs/MAKING_CHANGES.md#eval-tiers)). **Must-pass** questions (crisis
replies, out-of-scope declines, prompt injection) have to pass every run. **Known gaps** fail for a recorded
reason, such as a page that isn't indexed. Everything else is **expected to pass** and is read as a pass rate,
since one answer can vary from run to run. Run just the must-pass questions with
`.venv/bin/python -m evals.run answers --only gate --reps 3` (about 3 cents).

## Testing and refining

- **Feedback.** Thumbs up/down in the widget append to `data/feedback.jsonl` (question, answer, rating).
- **Cost and latency.** Every AI answer appends token counts and seconds to `data/usage.jsonl`.
- **Retrieval.** Use `/api/search?q=...` to see what the index returns, and `/api/events?q=seminar` for the
  calendar. Shorthand aliases (ECE, BME, grad…) are in `ALIASES` in `app/index.py`.
- **Behavior.** Edit `SYSTEM_TEMPLATE` in `app/chat.py`. Use `CHATBOT_EFFORT` in `.env` to trade speed for
  thoroughness.
- **Tests (free, offline, also run by CI on every pull request).** `tests.test_chat_loop` (answer loop with a
  scripted fake model), `tests.test_documents` (which PDFs are picked, degree-plan parsing), `tests.test_sync`
  (fake WordPress site) and `tests.test_guard` (rate limits, tokens, spend cap). Run each with
  `.venv/bin/python -m tests.<name>`.

## Documentation

| Doc | For |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | how the code works, following one question from widget to answer |
| [docs/MAKING_CHANGES.md](docs/MAKING_CHANGES.md) | recipes for common changes, and the pull-request routine |
| [docs/SECURITY.md](docs/SECURITY.md) | scope, abuse and cost controls, research, open questions for the university |
| [docs/DATA_PLAN.md](docs/DATA_PLAN.md) | what usage data to save, why, for how long, and how it maps to Firestore or AWS (draft) |
| [docs/DEPLOY.md](docs/DEPLOY.md) | the hosted beta: Cloud Run, Firebase Hosting, the beta password, reading the logs |
| [docs/SITE_AUDIT.md](docs/SITE_AUDIT.md) | the site content audit: finding outdated or conflicting information on the college's own sites |
| [docs/reports/](docs/reports/) | evaluation reports to share; the [October 2026 beta evaluation](docs/reports/beta-evaluation-2026-10-21.pdf) opens right in the browser |
| [CLAUDE.md](CLAUDE.md) | rules and commands for Claude Code sessions in this repo |

## Hosted beta

Testers use https://uofuchatbot.web.app, behind a shared password. The server runs on Google Cloud Run and
the pages on Firebase Hosting. Every question and answer is saved to Firestore for 90 days so we can review
them, and testers are told so on the login page. [docs/DEPLOY.md](docs/DEPLOY.md) covers deploying, the
password and reading the logs.

## Security, abuse and cost protection

Short version (details, research and a launch checklist in [docs/SECURITY.md](docs/SECURITY.md)):

- **Stays on topic.** A small Haiku "scope gate" labels each question first. Off-topic requests (LeetCode,
  recipes, essays, jailbreaks) get a fixed reply: *"I'm scoped to University of Utah questions…"*.
  Coursework requests get a pointer to tutoring. Messages about suicide, self-harm or danger get crisis
  resources (988, the 24/7 HMHI crisis line, the University Counseling Center) and aren't logged.
- **Rate limits.** Each browser gets a signed token: 5 messages/min, 30/hour, 100/day. A looser per-IP
  backstop (30/min) keeps a campus Wi-Fi network from being throttled as one person. A global cap allows
  30/min, and only one answer runs at a time per browser.
- **Spend cap.** At most $5/day (`DAILY_BUDGET_USD`). When it's reached, the bot shows search results
  without AI until midnight. Also set a monthly spend limit on a dedicated Anthropic workspace; the Default
  workspace can't have one.
- **Safe output.** Only utah.edu links are clickable, the page reader can't reach internal addresses, and a
  canary catches attempts to dump the system prompt.
- **Privacy.** uNIDs, emails and phone numbers are redacted from logs, and the widget asks people not to
  share them.

## Embedding on a real page

The widget is a single file that renders inside a Shadow DOM, so it won't clash with the WordPress theme:

```html
<script src="https://YOUR-HOST/widget.js" defer></script>
```

Optional attributes: `data-api` (backend origin), `data-open="true"`, `data-load-fonts="false"`, and
`data-adobe-fonts="<project id>"` to use the University's brand fonts (Myriad Pro and Factoria) from its Adobe
Fonts project. Colors follow the [University web guidelines](https://brand.utah.edu/digital/web-guidelines/). The page
can also call `PriceAssistant.open()` or `PriceAssistant.ask("question")`. The demo wires the nav search icon
to the assistant.

### Preview on the live site (optional, your browser only)

With the server running, create a bookmark whose URL is:

```
javascript:(()=>{const s=document.createElement('script');s.src='http://localhost:8000/widget.js';s.dataset.api='http://localhost:8000';s.dataset.loadFonts='false';s.dataset.open='true';document.body.appendChild(s)})()
```

Open https://www.price.utah.edu/ and click the bookmark. Chrome will ask whether the site may access devices
on your local network. Allow it for this demo. The overlay only exists in your tab and changes nothing on the
real site.

## Known limitations (it's a POC)

- Conversations live in server memory and are lost on restart. The hosted beta restarts after it's been
  idle for a while, so an open conversation starts over.
- Department sites that aren't WordPress, and other U offices (admissions, registrar), are only read live.
- PDFs that are scanned images (several Mechanical Engineering flowcharts) have no text to read.
- Keyword search (BM25) can miss paraphrases. Claude compensates by re-searching, and embeddings would be a
  natural next step.
- Rate limits and the spend counter live in memory, so the server must run as a single process
  (see docs/SECURITY.md for the multi-server version).
- Before going public: an accessibility review (WCAG 2.1 AA), a privacy and data-retention policy, cost caps,
  a scheduled re-index, and the web team's sign-off on crawling and hosting.

## Project layout

```
app/config.py     settings: sites, freshness windows, model (all overridable in .env)
app/wp.py         polite, read-only WordPress REST client
app/sync.py       build / change-only update / deletion check (CLI + background)
app/documents.py  handbooks, degree plans and flowcharts (PDFs) and the CS handbook site
app/store.py      document store (data/docs.json) and per-site sync state
app/extract.py    shortcode / HTML / PDF → clean text, chunking
app/index.py      BM25 search index
app/events.py     college calendar (Trumba feed)
app/live.py       live page reads + WordPress search fallback
app/chat.py       Claude tool-use loop, sessions, system prompt
app/scope.py      scope gate, decline wording, prompt-leak canary
app/guard.py      rate limits, browser tokens, the beta password, concurrency, daily spend cap
app/records.py    question, feedback and spend records: local files or Firestore
app/privacy.py    redaction of identifiers in logs
app/pricing.py    per-model token prices
app/server.py     FastAPI: chat (SSE), sync, events, feedback, status, static pages
web/widget.js     embeddable chat widget
web/login.html    the hosted beta's password page
web/wake.js       the "Starting up" screen while the hosted server wakes
web/index.html    demo landing page
web/designs.html  design concepts
docs/             ARCHITECTURE, MAKING_CHANGES, SECURITY, DATA_PLAN, DEPLOY
deploy/           setup, secrets and deploy scripts for the hosted beta
audit/            read-only scan and lookups for the site content audit (.claude/workflows/site-audit.js)
Dockerfile        the Cloud Run server image (.gcloudignore picks what's uploaded)
firebase.json     Firebase Hosting and Firestore rules (firestore.rules)
tests/            offline tests; tests/fixtures.py is their small made-up corpus
.github/          CI workflow (runs the tests on every pull request), PR checklist and CODEOWNERS (who approves)
CLAUDE.md         guidance for Claude Code
evals/            accuracy questions and the eval runner
```
