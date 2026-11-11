# Price Engineering Assistant

An AI chat assistant for price.utah.edu (University of Utah, John and Marcia Price College of Engineering). It
answers from the college's and departments' public web content, handbooks and events calendar, and links its
sources. FastAPI backend, Claude Haiku 5.5 through the official `anthropic` SDK, and an embeddable
vanilla-JS widget.

Where to read:
- Change recipes, including rebuilding `data/`: [docs/MAKING_CHANGES.md](docs/MAKING_CHANGES.md)
- How it works, and the protections (rate limits, spending cap, scope gate): [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- The password-protected beta (Cloud Run, Firebase Hosting, Firestore logs): [docs/DEPLOY.md](docs/DEPLOY.md)
- What's beta-only, open decisions and hosting research for going public: [docs/GOING_LIVE.md](docs/GOING_LIVE.md)
- Auditing the college's own pages: [docs/SITE_AUDIT.md](docs/SITE_AUDIT.md)

## Commands

```bash
.venv/bin/uvicorn app.server:app --reload --port 8000   # run locally (single process only)
.venv/bin/python -m app.sync build | update | reconcile | documents | status
.venv/bin/python -m tests.test_chat_loop                 # these six are free and offline; run before every PR
.venv/bin/python -m tests.test_documents
.venv/bin/python -m tests.test_sync
.venv/bin/python -m tests.test_guard
.venv/bin/python -m tests.test_analytics
.venv/bin/python -m tests.test_summary                    # the chat-summary PDF; needs Pango (brew install pango)
.venv/bin/python -m app.analytics --days 7              # usage report: people, questions, topics, gaps
.venv/bin/python -m evals.run selftest                   # free; checks the eval graders
.venv/bin/python -m evals.run retrieval                  # free; needs the local index
.venv/bin/python -m evals.run answers                    # real API calls, about $0.18 a pass; ask before running
.venv/bin/python -m evals.run answers --only gate --reps 3   # must-pass cases only, about 3 cents; before a deploy
.venv/bin/python -m evals.run answers --only recruiting      # the future-student cases, about 3 cents
.venv/bin/python -m evals.summaries                       # six real chats and their summary PDFs, about 3 cents
.venv/bin/python -m evals.run regrade --dir evals/results/<run>   # free; re-score saved answers after fixing a case
.venv/bin/python -m evals.converse say <name> "<message>"  # one real API call; needs `evals.converse serve` running
./deploy/deploy.sh server | pages                        # update the hosted beta; ask before running
.venv/bin/python -m audit.scan --links                   # site content audit candidates; read-only, ~10 min
.venv/bin/python -m audit.lookup search "<words>"         # search the saved sites without the server
```

## Rules

- **Ground every fact.** Names, phone numbers, emails, deadlines, requirements and costs, whether in prompts,
  eval questions, widget text or docs, must come from a utah.edu page you actually read. Never fill them in
  from memory.
- **Keep comments sparse.** Comment only what would surprise a reader, and explain everything else in
  `docs/`. When a change affects how something works or how to change it, update the matching doc in the
  same change.
- **Spending money.** Anything that calls the Claude API (the answer eval, manual test questions) costs the
  project money. Say what it will cost and get a yes first. The tests use a scripted fake client and cost
  nothing.
- **Be polite to the university's servers.** Keep the 10-second per-site delay (from `robots.txt`) and make
  requests one at a time per site. Several department sites share a backend, and heavy parallel API queries
  returned 504s. Long crawls (`app.sync build` or `documents`, `audit.scan --links`, `evals.run baseline`) run
  for 10 minutes or more against those sites: say how long and ask first. The site-audit workflow
  (`.claude/workflows/site-audit.js`) also starts many agents.
- **Changes go through pull requests.** `main` rejects direct pushes; merging needs green CI and the code
  owner's approval (`.github/CODEOWNERS`, to be removed when the project moves to the university). The
  maintainer merges; don't merge or bypass the rule yourself.
- **Deploying changes what testers see.** Run `deploy/deploy.sh` only when asked, from merged code.
  `deploy/secrets.sh` is for the maintainer to run in their own terminal; never read or print secrets.
- **Never commit** `.env` or `data/`. The API key exists only in `.env` and the host's secret settings.
- **Model:** `claude-haiku-5-5` unless the maintainers decide otherwise. A model change needs a `PRICES`
  entry in `app/pricing.py` and an answer-eval run.
- **Beta-only settings are deliberate.** The beta password, the combined rate limit, the $5 daily cap and the
  sleeping server, among others (full list in `docs/GOING_LIVE.md`), are for internal testing. Leave them as
  they are unless asked. When something becomes beta-only or a decision is put off, add it to
  `docs/GOING_LIVE.md`.
- **Don't write code for an undecided host.** Where the public version runs (AWS or elsewhere) isn't decided.
  The migration notes are in `docs/GOING_LIVE.md`.

## Gotchas

- The effort setting is `CHATBOT_EFFORT`. Never add generic `CLAUDE_*` environment names: a shell-wide
  `CLAUDE_EFFORT` once silently overrode the app's setting. `CLAUDE_MODEL` predates this rule and is the one
  exception still in use.
- With `tool_choice: none` and no instruction, Haiku 5.5 can end a turn with no text. The loop adds
  `FINAL_NUDGE` and retries once (`app/chat.py`). Keep that when editing the loop.
- `SYSTEM_TEMPLATE` is frozen per session. Conversation history only grows; failed turns are removed whole,
  never edited.
- PDF links on the WordPress sites are often inside page-builder buttons, stored URL-encoded as
  `url:%2F…pdf`. `app/documents.py` handles both forms.
- Rate limits, sessions and the answer cache are in memory, so run exactly one server process.
- Firebase Hosting cuts requests off at 60 seconds, so the pages call Cloud Run directly. The address comes
  from `config.js`, which `deploy/deploy.sh` writes for Hosting and the server serves locally.
- The hosted server sleeps after about 15 idle minutes and takes up to 2 minutes to start. Cloud Run turns
  away requests that arrive meanwhile, and browsers see a network error, not a 500. Pages wait with
  `web/wake.js` and the widget retries after `waitForServer()`; a failed status check must never count as
  "no password needed".
- Cloud Run pauses the CPU once a response ends. Firestore writes are queued on a thread and flushed
  (`records.flush()`) before each response closes; keep that when adding endpoints that write records.
- `.gcloudignore` decides what's uploaded to Cloud Build. It must keep excluding `.env` and everything in
  `data/` except `docs.json`. Check with `gcloud meta list-files-for-upload .`.
- Automatic content checks (`AUTO_SYNC`) need all of `data/`, not just `docs.json`. With only `docs.json`
  the server never checks for edits. With `sync_state.json` but no `raw/`, the PDF refresh drops every PDF
  (docs/ARCHITECTURE.md, "Keeping content current on a server").
- `tests/fixtures.py` is the test corpus. Tests must not depend on `data/` or the network, because CI has
  neither.
