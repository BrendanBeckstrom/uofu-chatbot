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
   chat window and talks to the server. The hosted beta's pages also load `web/wake.js`, which shows a
   "Starting up" screen while the sleeping server wakes ([DEPLOY.md](DEPLOY.md#settings-on-cloud-run)).

`app/server.py` (FastAPI) connects them, and `app/guard.py` sits in front of the answer loop to stop abuse and
cap spending. The hosted beta runs the same server on Cloud Run and the pages on Firebase Hosting, behind a
shared password; [DEPLOY.md](DEPLOY.md) covers that setup.

## What happens when someone asks a question

1. **Widget** (`web/widget.js`): on first use it gets a signed browser token from `POST /api/token`. In the
   hosted beta, the login page (`web/login.html`) gets the token instead, and only for the right password. It sends
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
      A follow-up is searched together with the previous question: one with fewer than 5 meaningful words,
      or one that points back with words like "those", "ones", "what about" or "more recent"
      (`FOLLOW_UP_RE`). Otherwise "can you find more recent ones?" would search for the newest news posts.
   5. Claude gets the system prompt (`SYSTEM_TEMPLATE`), the conversation so far, and this turn's search
      results. It may call up to 3 rounds of tools:
      - `search_site`: the local index
      - `fetch_page`: a live read of any utah.edu page, or an indexed PDF a few pages at a time
      - `get_events`: the live college calendar

      The last round has tools switched off and a nudge to write the answer.
   6. While text streams out, it watches for the prompt-leak canary. If the canary shows up, the answer is
      replaced and the turn is dropped.
   7. It saves a record of the question, the answer, its sources, tokens and cost (`app/records.py`), adds
      the cost to the day's spend, and sends the source links. The record's ID goes to the widget, so a
      thumbs up or down points at it.
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
    Claude can ask for specific pages (`pages: "9-11"`) or for the pages about a topic
    (`find: "credit hours required"`), which saves a tool round on long handbooks.
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

### Campus pages (`CAMPUS_PAGES` in `app/documents.py`)

Some common questions are answered by campus offices the college sites only link to: the WUE tuition rate
(Financial Aid), tuition and the engineering differential (the Bursar), first-generation
support, the robotics minor (the Robotics Center). These come from a fixed list of URLs instead of a whole site,
because those sites mostly cover the rest of the university and would crowd engineering pages out of search.

- They're fetched and refreshed with the planning documents (`python -m app.sync documents`), one request per
  URL, with the same per-site spacing. They're stored with `site: "campus"`; HTML pages get the type `page` and
  PDFs `pdf`, so search treats them like any other page or PDF.
- A title of `None` uses the page's own `<title>`, minus " - The University of Utah". The Bursar's fee PDFs get
  a title in the list, because their file names (`FreshSophTuitionFeeRes.pdf`) don't say what they are.
- **No dates for HTML pages.** These servers send no `Last-Modified`, or one that is just the time of the
  request, which would make every page look edited today. Search results show no date for them. PDFs keep the
  file date.
- Removing a URL from the list removes its page from the index at the next documents sync.
- **Leave out broad pages that overlap the college's own.** Admissions' university-wide scholarships page
  was tried and removed: it ranked first for engineering scholarship questions, so the bot answered from it
  and no longer found price.utah.edu/scholarships. Check the answer eval's scholarship cases after adding a page.
- **They aren't named in the prompt.** Listing them in `SYSTEM_TEMPLATE` and the `search_site` description cut
  how often the bot searched again (0.48–0.52 times per answer, against 0.58–0.73 without the list), and the
  expected-to-pass rate fell from 86–89% to 78–82% in the Oct 29 answer evals. Search ranks them first for
  their own questions without the hint.

### Search (`app/index.py`)

The index is a BM25 keyword index over ~1,400-character chunks:

- A match in a page's title or URL counts extra.
- News posts are weighted a little below evergreen pages.
- Anything older than `OLD_AFTER_YEARS` (2, in `app/config.py`) scores three quarters as much, so a newer
  page on the same topic comes first. Age means a post's publication date, or a page's or PDF's last update.
  This moved the retrieval eval from 60 to 61 of 77 on Nov 11, 2026.
- URLs in `NOT_INDEXED` (`app/config.py`) are left out entirely: two national salary news posts from 2013
  and 2017 that read like current U figures.
- At most 2 results come from the same folder, so a dozen near-empty sibling pages can't crowd out the
  overview page.
- `ALIASES` expands shorthand like "ECE" or "dorm".

The server rebuilds the index when `data/docs.json` changes on disk.

### Old sources

Much of the sites' content is old. On Nov 11, 2026, 45% of pages, 86% of news posts and 35% of PDFs were more
than 2 years old, and the top search result was that old for 44% of the eval questions. The bot flags old
sources rather than hiding them:

- Search results and page reads show each source's date, and once it's past 2 years, its age ("7 years
  old"). The code works this out, because Haiku is unreliable at date arithmetic.
- Under the results comes "Who has current information about the older sources": the office of the site each
  old result came from. The offices, with phone and general email, are the `office` entries in
  `config.SITES`, taken from each department's contact page or footer. Campus pages get the college office.
- The prompt's "Dates and old information" section has the bot look for something newer first (a newer
  result, one more search, or the live page). If nothing newer turns up, it gives what it found with its date,
  one sentence saying it's over 2 years old and may be out of date (for salaries, costs, statistics and
  rankings, too old to rely on), and that office. It leaves the note out for recent sources and for questions
  about past events.
- The `old-info` eval cases check both sides: an old salary page gets the note and the office, a fresh
  contact page and a past news story get none.

### Live reads (`app/live.py`) and events (`app/events.py`)

`fetch_page` reads any `*.utah.edu` page or PDF:

- It checks that the host resolves to a public address, re-checks every redirect, caps the size, and caches
  results for an hour.
- An indexed PDF is served from the index without a network request.

The calendar comes from the college's public Trumba JSON feed (`uu-college-of-engineering`), cached for 15
minutes.

## Chat summary PDF (`app/summary.py`, `POST /api/summary`)

Once a chat has an answer, the widget shows "Save chat summary (PDF)". The visitor gets a branded take-home
page: an AI summary of their chat on top, then "About the Price College", highlights picked for what they
talked about.

1. **The chat comes from the server**, not the browser: the session's own question-and-answer pairs. A
   transcript sent by the browser could be edited to make a U-branded PDF say anything. Only the browser that
   held the chat can download it, and only while the chat is open (30 idle minutes, and on the hosted beta, until
   the server sleeps). Declined and crisis turns are left out.
2. **Highlight candidates are found in code.** The chat's departments are the ones the visitor asked about (or,
   if they named none, ones the answers discuss at least three times). For each, one search per kind of
   highlight (`KINDS`: research and labs, student teams and competitions, hands-on projects, opportunities,
   industry ties, awards, student community) keeps up to 2 pages from that department's site, plus its 4
   newest news posts; with two or three departments, each gets half that. The college site adds one page per
   kind in `COLLEGE_KINDS`. Only pages under 2 years old that the chat didn't already cite are offered, and
   routine notices (seminars, staff news, giving pages) are skipped. A one-department chat offers about 20.
3. **One model call** (Haiku, thinking off, JSON schema output) writes the title, overview, key points, next
   steps and four to six highlights, each naming the page it came from, mixing kinds and, for a future
   student, favoring what undergraduates do. About a fifth of a cent. With thinking on, long chats ran out
   of output tokens before writing anything.
4. **Code checks everything before it's printed** (`check()`): every figure in a key point must appear in the
   chat's answers, and every figure in a highlight in its page; links are kept only if the chat gave them;
   comparisons with other schools are dropped; a ranking needs a year from the last 2 years, because pages
   updated this year still quote 2010 rankings. A big figure the page doesn't show is removed and the
   highlight kept; a money figure is shown the way the page writes it ("$30 million"), and amounts under
   $1,000 stay in the text. A page's date counts as part of the page ("in 2025" from a 2025 post).
5. **WeasyPrint** turns an HTML template into a tagged PDF/UA-1 file screen readers can follow. It uses the
   college's official logo file (`app/assets/`, unmodified from price.utah.edu), Utah Red with black and Zion
   Cinder Cone gray, and Source Sans 3, the face the brand site links for Myriad Pro (OFL, in
   `app/assets/fonts/`). The footer says it was written by AI and isn't an official service or decision.

The PDF isn't stored; a second download of the same chat reuses it. `python -m evals.summaries` runs six
real two-question chats and grades their summaries (about 3 cents; the PDFs are saved for a look).

## Usage records (`app/records.py`) and statistics (`app/analytics.py`)

Every answer, decline and error saves one question record:

- an anonymous user ID (a hash of the browser token, so "people per day" can be counted without cookies or
  trackers)
- the redacted question and answer, and the pages it cited
- the outcome (answered, declined, crisis, cached, search_only, error)
- the scope label and a topic, both from the scope gate's single call
- the audience
- whether the answer admitted it couldn't find something (`gap`)
- seconds, tokens, cost and the app version

Thumbs up and down save a feedback record that points at its question. Crisis messages are never stored.
[DATA_PLAN.md](DATA_PLAN.md) lists every field.

Where the records go depends on `LOG_BACKEND`:
- **Locally (`files`):** `data/usage.jsonl` and `data/feedback.jsonl`.
- **The hosted beta (`firestore`):** the Firestore collections `questions` and `feedback`, plus the day's spend in `spend`.

Firestore writes run on a background thread so they never slow an answer. The server waits for them
(`records.flush()`) before closing each response, because Cloud Run pauses the CPU once a response ends.

`python -m app.analytics --days 30` turns the records into a report: people per day, questions, error
rate, topics, the most-asked questions, and recent questions it couldn't fully answer (content to add or
surface on the site). `--firestore` reads the hosted beta's records, and `--json` gives the same numbers
for a dashboard. Eval runs log to their own results folder, so they don't count as visitors.

## Site content audit (`audit/`)

A separate, read-only check of the college's own pages for outdated or conflicting information. It reads `data/`
but never writes to it, so it doesn't affect answers. [SITE_AUDIT.md](SITE_AUDIT.md) explains it.

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
| `data/usage.jsonl` | one question record per answer, decline or error (locally; Firestore when hosted) | chat |
| `data/feedback.jsonl` | thumbs up/down, linked to the question record (locally; Firestore when hosted) | server |
| `data/spend.json` | today's spend, so a restart doesn't reset the daily cap (Firestore when hosted) | guard |
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
- `LOG_BACKEND`
- `BETA_PASSWORD`

The hosted beta's values are listed in [DEPLOY.md](DEPLOY.md).

## Tests and evals

| Command | Needs | Covers |
| --- | --- | --- |
| `python -m tests.test_chat_loop` | nothing | the answer loop with a scripted fake Claude: tools, caps, cache, refusals, the scope gate, crisis replies, PDFs, audience |
| `python -m tests.test_documents` | nothing | which PDFs get picked and how versions are matched |
| `python -m tests.test_sync` | nothing | build, change-only update and deletion check against a fake WordPress site |
| `python -m tests.test_guard` | nothing | rate limits, tokens, the beta password, spend cap, request-size limits |
| `python -m tests.test_analytics` | nothing | the usage report's counts; Firestore records and spend, against an in-memory fake |
| `python -m tests.test_summary` | Pango (`brew install pango`) | the chat-summary PDF: what the checks keep, highlight picks, the tagged PDF, the endpoint |
| `python -m evals.run selftest` | internet (calendar) | the eval graders accept good answers and reject empty ones |
| `python -m evals.run retrieval` | the local index | does the first search find the right page? |
| `python -m evals.summaries` | API key, about 3 cents | six real chats and their summary PDFs: coverage, highlights on topic, what the checks dropped |
| `python -m evals.run answers` | API key, about $0.18 per pass | the real bot on every question in `evals/questions.json`, reported by tier (must pass, expected to pass, known gaps; [MAKING_CHANGES.md](MAKING_CHANGES.md#eval-tiers)); writes `summary.json` with 95% ranges, median answer length and model calls per answer, and exits 1 if a must-pass case fails |
| `python -m evals.run regrade --dir …` | nothing | re-scores a saved run after a case is fixed |
| `python -m evals.run baseline` | internet, ~12 minutes | price.utah.edu's own search box vs. the assistant's first search |
| `python -m evals.converse` | API key, about $0.001 a message | multi-turn test conversations against a separate eval server, for people or agents |

The tests use `tests/fixtures.py`, a handful of made-up documents, so they run anywhere, including CI.

## Design decisions worth knowing

- **The system prompt is fixed for the whole conversation.** It's built once per session, with the date and
  random canary. Changing it mid-conversation would break prompt caching and Claude's saved reasoning.
- **History only grows.** A turn that fails, is refused or leaks is removed whole, so the history never holds
  a tool call without its result.
- **Future students get answers aimed at what they're deciding.** The "Future students and families" section
  of `SYSTEM_TEMPLATE` has the bot work out what a prospective student or parent is weighing (fit, cost,
  where it leads) and answer that with specifics from the pages it read, plus at most one fitting next step.
  It applies when the visitor chose "Future student" or their messages show they're choosing a college. It
  describes behavior only, with no page names or figures, for the same reason the campus pages aren't named.
  The research behind it, and what it deliberately avoids (comparisons with other schools, unsourced
  salaries, pressure), is in [the behavior report](reports/recruiting-behavior-2026-11-06.pdf) and
  [the research brief](reports/recruiting-research-2026-11-05.md). The `recruiting` eval category tests it.
- **Old sources are flagged, not hidden.** Anything over 2 years old still gets used, with its date, a short
  "may be out of date" note and who to ask. Dropping old pages would leave gaps where the sites have nothing
  newer; the assistant is a helper, and the office has the current answer. See "Old sources" above.
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
