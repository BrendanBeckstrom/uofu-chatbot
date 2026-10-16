# Price Engineering Assistant

An AI chat assistant for price.utah.edu (University of Utah, John and Marcia Price College of Engineering). It
answers from the college's and departments' public web content, handbooks and events calendar, and links its
sources. FastAPI backend, Claude Haiku 5.5 through the official `anthropic` SDK, and an embeddable
vanilla-JS widget.

How it works: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Change recipes:
[docs/MAKING_CHANGES.md](docs/MAKING_CHANGES.md). Security and cost: [docs/SECURITY.md](docs/SECURITY.md).

## Commands

```bash
.venv/bin/uvicorn app.server:app --reload --port 8000   # run locally (single process only)
.venv/bin/python -m app.sync build | update | reconcile | documents | status
.venv/bin/python -m tests.test_chat_loop                 # these five are free and offline; run before every PR
.venv/bin/python -m tests.test_documents
.venv/bin/python -m tests.test_sync
.venv/bin/python -m tests.test_guard
.venv/bin/python -m tests.test_analytics
.venv/bin/python -m app.analytics --days 7              # usage report: people, questions, topics, gaps
.venv/bin/python -m evals.run selftest                   # free; checks the eval graders
.venv/bin/python -m evals.run retrieval                  # free; needs the local index
.venv/bin/python -m evals.run answers                    # real API calls, about $0.05; ask before running
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
  returned 504s.
- **Changes go through pull requests.** `main` rejects direct pushes; merging needs green CI and the code
  owner's approval (`.github/CODEOWNERS`).
- **Never commit** `.env` or `data/`. The API key exists only in `.env` and the host's secret settings.
- **Model:** `claude-haiku-5-5` unless the maintainers decide otherwise. A model change needs a `PRICES`
  entry in `app/pricing.py` and an answer-eval run.

## Gotchas

- The effort setting is `CHATBOT_EFFORT`. Never read generic `CLAUDE_*` environment names: a shell-wide
  `CLAUDE_EFFORT` once silently overrode the app's setting.
- With `tool_choice: none` and no instruction, Haiku 5.5 can end a turn with no text. The loop adds
  `FINAL_NUDGE` and retries once (`app/chat.py`). Keep that when editing the loop.
- `SYSTEM_TEMPLATE` is frozen per session. Conversation history only grows; failed turns are removed whole,
  never edited.
- PDF links on the WordPress sites are often inside page-builder buttons, stored URL-encoded as
  `url:%2F…pdf`. `app/documents.py` handles both forms.
- Rate limits, sessions and the answer cache are in memory, so run exactly one server process.
- `tests/fixtures.py` is the test corpus. Tests must not depend on `data/` or the network, because CI has
  neither.
