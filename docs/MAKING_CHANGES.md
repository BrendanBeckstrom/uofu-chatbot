# Making changes

Recipes for the changes people make most, and the routine for getting a change in safely. You don't need to
know the whole codebase; each recipe names the one place to edit and how to check it worked.
[ARCHITECTURE.md](ARCHITECTURE.md) explains how the pieces fit together.

**Using Claude Code?** It reads [CLAUDE.md](../CLAUDE.md) automatically, so you can describe the change in
plain words, for example *"add 'How do I join a student club?' to the current-student example questions"*,
and review what it proposes.

## The routine for every change

1. **Make a branch.** `main` is protected and rejects direct pushes. In GitHub's web editor, choose "Create a
   new branch" when you commit. Without write access to the repo, fork it and open the pull request from your
   fork.
2. **Make the change** using a recipe below.
3. **Run the checks** (about 30 seconds, free, no API key needed):
   ```bash
   .venv/bin/python -m tests.test_chat_loop
   .venv/bin/python -m tests.test_documents
   .venv/bin/python -m tests.test_sync
   .venv/bin/python -m tests.test_guard
   .venv/bin/python -m tests.test_analytics
   ```
4. **If you changed what the bot says or how it searches,** also run the real-answer eval. It costs
   about $0.12 (or $0.25 with `--reps 2`):
   ```bash
   .venv/bin/python -m evals.run answers
   ```
   Compare the pass rate with the last run (each run is saved in `evals/results/`).
5. **Open a pull request.** GitHub runs the same checks automatically (the "CI" check). If it's red, click
   "Details" to see which check failed and why.
6. **Get it reviewed.** A pull request can be merged only when CI is green and the code owner listed in
   `.github/CODEOWNERS` has approved it. New commits after an approval need a fresh approval. The rule is the
   "Protect main" ruleset under the repo's Settings → Rules; the repo admin can bypass it from a pull
   request, for their own changes.

## Recipes

### Change how the bot answers (tone, rules, what it should do)

Edit `SYSTEM_TEMPLATE` in `app/chat.py`. It's plain English, organized under headings: Scope, How to answer,
Time-sensitive questions, Degree planning, Style, and Untrusted content and privacy. Keep instructions
positive ("Lead with the direct answer") rather than lists of don'ts, and run the answer eval afterwards.
Conversations that are already open keep the old prompt until the user starts a new chat.

### Change the decline, coursework or crisis wording

Edit `DECLINE`, `DECLINE_COURSEWORK` or `CRISIS` in `app/scope.py`. The eval looks for the phrase "I'm
scoped to University of Utah questions" (`DECLINE_MARKERS` in `evals/run.py`), so update that too if you
reword the opening. **Crisis wording and phone numbers need sign-off from the University Counseling Center;**
re-check them on counselingcenter.utah.edu before changing them.

### Change the welcome message, example questions or Contact tab

All in `web/widget.js`:

- **Welcome message:** `renderWelcome()`
- **Example questions** for future and current students: `SUGGESTIONS`
- **Contact tab links:** `CONTACTS`, plus `renderContact()` for the college office and support cards
- **The beta's login page** is a separate file, `web/login.html`
- **Colors and fonts:** the CSS variables at the top of `CSS` (`--red`, `--head`, …). Follow the University's
  [web guidelines](https://brand.utah.edu/digital/web-guidelines/):
  - Use only the core colors: Utah Red `#BE0000`, black, white and Zion Cinder Cone `#707271`.
  - Accent colors (Red Rocks `#890000`, Salt Flat Grey `#E2E6E6`, Mountain Green `#6CC24A`, Wasatch Sunrise
    `#FFB81D`, …) are for small details only, never headings or links, and at most 10% of the design.
  - Fonts are Myriad Pro (text) and Factoria (headings), served from the University's Adobe Fonts project:
    set `data-adobe-fonts="<project id>"` on the script tag. Without it, the widget falls back to the
    Google fonts that price.utah.edu uses today.

Reload the page to see changes; the server sends the widget uncached. Only link utah.edu pages you have
opened and checked.

### Make search find the right page

1. See what search returns: http://localhost:8000/api/search?q=your+question
2. If people use a word the site doesn't, add it to `ALIASES` in `app/index.py` (for example "dorm" →
   "housing").
3. Add the question to `evals/questions.json` (next recipe) so it stays fixed.
4. Run `.venv/bin/python -m evals.run retrieval`.

### Add a question to the eval

Add an entry to `evals/questions.json`:

```json
{
  "id": "short-unique-id",
  "category": "student-support",
  "question": "Where can I get tutoring for physics?",
  "expect_urls": ["price.utah.edu/tutoring-resources"],
  "must_include": [["tutoring", "TA hours"]],
  "reference": "A correct answer in one or two sentences.",
  "as_of": "2026-10-14"
}
```

- `must_include` is a list of groups; the answer needs one phrase from every group.
- Optional fields:
  - `must_not_include`: known-wrong statements
  - `decline: true` or `decline: false`: should it refuse?
  - `time_sensitive: true`
- Check facts against the live site, never from memory.
- `origin` (where the question came from) and `evidence` (the page text you checked) are optional notes for
  reviewers; the graders ignore them.
- If a grader turns out too strict (it failed a good answer), fix the case and re-score the saved run for free:
  `.venv/bin/python -m evals.run regrade --dir evals/results/<run>`.
- Run `.venv/bin/python -m evals.run selftest`. It confirms your reference answer passes the graders and an
  empty answer fails.

### Include or leave out a PDF (handbooks, plans, flowcharts)

In `app/documents.py`:

- `INCLUDE` / `EXCLUDE` are patterns matched against the file name.
- `SKIP_URLS` always leaves a specific file out.
- `MIN_YEAR` is the oldest year kept.

Then run `.venv/bin/python -m app.sync documents`. Its log shows how many were selected and updated. If
you change how PDF text is extracted (`app/extract.py`), raise `EXTRACTOR_VERSION` so saved files are
re-read.
`tests/test_documents.py` has examples of what should and shouldn't be picked; add one for your change.

### Add another department or college website

Add it to `SITES` in `app/config.py` (it must be a WordPress site, and check its `robots.txt` first), then
run `.venv/bin/python -m app.sync build --site newkey`. Mention it in `SYSTEM_TEMPLATE`, where the sites are
listed.

### Change rate limits, the daily budget or the model

These are settings, not code; put them in `.env` (see `.env.example`):

- `TOKEN_LIMITS="5/60,30/3600,100/86400"`: per browser, as "messages/seconds" rules.
- `DAILY_BUDGET_USD=5`: past this, the bot shows search results without AI until midnight.
- `CLAUDE_MODEL=claude-haiku-5-5`: if you switch, add the model's prices to `PRICES` in `app/pricing.py`
  and run the answer eval.
- `CHATBOT_EFFORT=low`: higher is slower and more thorough.

Restart the server after editing `.env`.

### Refresh the content by hand

```bash
.venv/bin/python -m app.sync update      # pages and news edited since the last check
.venv/bin/python -m app.sync documents   # handbooks, plans, flowcharts
.venv/bin/python -m app.sync status      # what was checked when, and any errors
```

The hosted beta doesn't refresh itself; run `./deploy/deploy.sh server` afterwards to ship the new index.

### Put a change on the hosted beta

After the pull request is merged, from `main`:

```bash
./deploy/deploy.sh server    # anything in app/, or a refreshed index
./deploy/deploy.sh pages     # anything in web/
```

[DEPLOY.md](DEPLOY.md) explains what each step does, how to read the server's logs and how to roll back.

### Change the beta password

Run `./deploy/secrets.sh beta-password` in your own terminal (it asks for the new password without showing
it), then `./deploy/deploy.sh server`. Every tester is signed out and needs the new password.

## Things to avoid

- **Don't invent facts** in prompts, eval questions, example answers or widget text. Names, phone numbers,
  deadlines and requirements must come from a utah.edu page you've checked.
- **Don't commit `.env` or anything in `data/`.** `.gitignore` already excludes them. The API key lives
  only in `.env` locally and in the host's secret settings.
- **Don't speed up the crawler.** The 10-second delay is what the sites' `robots.txt` asks for, and some
  department sites share a server.
- **Don't run the answer eval in a loop.** Each run costs money; one run per meaningful change is plenty.
