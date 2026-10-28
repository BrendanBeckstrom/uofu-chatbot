# Site content audit

A check of the college's own websites for information that is outdated, contradictory, unreachable or unreadable.
It produces a report (`audit/results/<date>/site-content-audit-<date>.pdf`) for the assistant team. The first one is
[October 21, 2026](../audit/results/2026-10-21/site-content-audit-2026-10-21.pdf).

## Why we run it

The assistant answers from the college and department websites, so a wrong or outdated page becomes a wrong answer.
The October 2026 evaluation found several errors that weren't the assistant's fault, such as two different scholarship
deadlines on the same page and calendar withdrawal dates two weeks earlier than the Registrar's. The audit:

- separates "the bot is wrong" from "the page is wrong" when we review bad answers;
- gives us a concrete, useful list to bring to the college's web team and departments;
- makes the assistant better for free once the pages are fixed.

## It doesn't change the assistant

The audit only **reads** our saved copy of the sites (`data/`) and the live pages. It never writes to `data/`,
never re-crawls the sites into the index, and never changes the model, prompt or code the assistant answers with. It's
safe to run while the beta is being tested.

## How it works

1. **Automatic scan** (`audit/scan.py`, free). Over the saved copy it lists:
   - pages not updated in three or more years, and which recently updated pages still link to them;
   - evergreen pages that put a passed date next to words like "deadline", "register" or "apply";
   - PDFs with pages that contain no text (image-only plans and forms that screen readers and search can't read);
   - leftover-looking pages still public (URLs ending in `-dnu`, `-2`, `-old` and similar);
   - with `--links`, links on recently updated pages to utah.edu pages we don't have, checked live. Requests are 10
     seconds apart per site, as the sites' `robots.txt` asks, and only the 50 most-linked targets per site are
     checked. The rest are counted in `links_unchecked`.

   Everything the scan finds is a candidate, not a finding.
2. **Agent cross-check** (the `site-audit` workflow in `.claude/workflows/site-audit.js`). Five agents each take a
   topic: admissions and costs; the academic calendar and events; advising and contacts; policies, requirements and
   plans; and broken, stale or unreadable pages. Each reads the saved copy with `audit/lookup.py`, checks the live
   pages and the official sources (Registrar, Admissions, Financial Aid, Bursar, department pages), and reports
   findings with quoted evidence. A second agent per topic then re-checks every finding live and tries to refute it.
   Only findings that survive go into the report. The agents use Claude Code, not the project's Claude API key.
3. **Report.** A summary, problems by site, the high-severity findings in full with quoted evidence, the rest as
   a table, and the scan's lists, as an HTML page and a PDF in `audit/results/<date>/`.

## Running it

```bash
.venv/bin/python -m audit.scan --links        # about 10 minutes; writes audit/results/<date>/scan.json
```

Then, in Claude Code, ask it to run the site-audit workflow with today's date and that scan file:
`args: {"date": "<date>", "scan": "audit/results/<date>/scan.json"}`. The workflow's agents follow the read-only and
polite-fetching rules in the script. Save what the workflow returns as `audit/results/<date>/findings.json`, then:

```bash
.venv/bin/python -m audit.report audit/results/<date> --pdf   # site-content-audit-<date>.html and .pdf, same folder
```

The report keeps findings the verifier confirmed or marked uncertain, counts the refuted ones, and appends the
scan's lists (broken links, old pages still linked, leftover pages, image-only PDFs). If two topics reported the
same problem, add `"duplicate_of": "<the other finding's title>"` to one of them in findings.json before building.

`audit/lookup.py` is handy on its own:

```bash
.venv/bin/python -m audit.lookup search "withdrawal deadline"
.venv/bin/python -m audit.lookup page https://www.price.utah.edu/scholarships
.venv/bin/python -m audit.lookup events --days 60
```

Commit each run's `audit/results/<date>/` folder, so the next run can be compared with it. The report names college
staff and their emails; all of it comes from the public pages it checks.

## How often

Before each semester's registration period, and after a big content change on the sites. Compare with the previous
report to see what was fixed.
