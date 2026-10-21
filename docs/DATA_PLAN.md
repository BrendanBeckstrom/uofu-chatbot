# Usage data plan

**Status: draft for discussion, October 14, 2026.** It covers what the assistant should record about its use,
why, and for how long. Where the data is stored (Firestore or AWS) is still open, so the plan works with
either; [Storage options](#storage-options) shows how it maps to both. Nothing here is built yet beyond
what [Today](#today) describes.

## What the data has to answer

**For the college:**
1. How many people use the assistant, when, and how often they come back.
2. What they ask about, broken down by future and current students.
3. What it couldn't answer, meaning content the websites are missing or hiding.
4. Whether the answers are good: thumbs up/down, declines, errors and speed.
5. What it costs per day and per month.

**For maintainers:** which questions errored or were slow, and real questions to add to the eval.

**For the project's record (and Brendan's resume):** unique users, questions answered, error rate and
uptime, as aggregate numbers only.

Anything that doesn't serve one of these questions isn't collected.

## Principles

- **Collect the minimum.** No names, uNIDs, emails or IP addresses are stored. "Users" are anonymous
  browser IDs: a one-way hash of the random token the widget gets on first use. They count browsers, not
  people.
- **Logged on the server.** The server already sees every question because it has to answer it, so it
  writes the record then. There's no tracking script in the browser and no ad-tech vendor, and ad blockers
  don't distort the counts.
- **Redact before storing.** uNIDs, emails, phone numbers and SSN-like numbers are removed from any text
  before it's saved (`app/privacy.py`).
- **Text expires; counts don't.** Question and answer text is kept for a short window, then deleted. Daily
  totals with no text are kept long-term.
- **Never store crisis messages.** If the scope gate labels a message `crisis`, only the fact that it
  happened is recorded.
- **Logging never breaks chat.** Records are written in the background. If the database is down, the
  answer still goes out and the record is dropped and counted.

## What gets saved

Four record types. Field names are the same whichever storage is chosen.

### 1. Question: one per message, answered or not

| Field | Example | Why |
| --- | --- | --- |
| `id` | `"q_7f3a…"` | links feedback and widget clicks to the question |
| `ts` | `"2026-10-14T18:42:30Z"` | when, in UTC |
| `day` | `"2026-10-14"` | Salt Lake City date, for daily totals |
| `user` | `"a1b2c3d4e5f6"` | anonymous browser ID; counts unique and returning users |
| `session` | `"9c1e…"` | anonymous conversation ID; conversation length |
| `turn` | `2` | position in the conversation |
| `audience` | `"current"` | future or current student, from the welcome switch, if picked |
| `device` | `"mobile"` | `mobile` or `desktop` only, derived from the browser string, which isn't stored |
| `question` | `"How do I apply as a transfer student?"` | what people ask (redacted, ≤ 500 characters; empty for crisis) |
| `answer` | `"Transfer students apply…"` | reviewing bad answers (≤ 4,000 characters) |
| `topic` | `"admissions"` | from the scope gate: admissions, programs_courses, degree_planning, advising_support, research, events, careers, campus_life, people_contacts, other |
| `gate` | `"in_scope"` | in_scope, out_of_scope, coursework, injection, crisis |
| `outcome` | `"answered"` | answered, declined, crisis, cached, search_only, error |
| `gap` | `true` | the answer said it couldn't find or confirm something |
| `sources` | `["https://www.price.utah.edu/…"]` | which pages answer questions; up to 5 |
| `tools` | `{"search": 1, "read": 1, "events": 0}` | how hard it worked |
| `seconds` | `4.2` | speed |
| `cost_usd` | `0.0015` | spend |
| `tokens` | `{"input": 12, "output": 410, "cache_read": 5000, "cache_write": 8000}` | cost breakdown |
| `model` | `"claude-haiku-5-5"` | comparisons when the model changes |
| `error` | `"timeout"` | error type when `outcome` is `error` |
| `version` | `"1a90251"` | app version (git commit), to compare before and after a change |

### 2. Feedback: thumbs up/down

| Field | Example | Why |
| --- | --- | --- |
| `id`, `ts`, `day` | | as above |
| `question_id` | `"q_7f3a…"` | links to the question record instead of copying its text |
| `rating` | `1` or `-1` | satisfaction |
| `comment` | `"The deadline is wrong"` | optional, redacted, ≤ 1,000 characters |

### 3. Widget activity (optional; see open question 5)

`opened`, `audience_selected`, `suggestion_clicked` (which example question), `contact_opened` and
`link_clicked` (which URL), each with `id`, `ts`, `day`, `user` and `device`. These show how many people
open the assistant but don't ask anything, and which example questions and contacts get used. They would
come from a small, rate-limited endpoint on our own server, not a third-party script.

### 4. Daily summary: one per day, no text

Computed each night from the records above:

- unique users and returning users
- questions, broken down by outcome, topic and audience
- thumbs up and down
- median and 95th-percentile seconds
- cost
- busiest hour
- mobile share
- content gaps
- widget opens

This is what dashboards read, so a chart never has to scan thousands of question records.

### Not saved

- IP addresses: used only in memory for rate limits, then gone
- browser tokens, full browser strings, cookies
- the system prompt, tool outputs and page text the bot read
- the text of crisis messages

## Retention (proposed; needs Privacy Office sign-off)

| Data | Kept |
| --- | --- |
| Question and answer text, feedback comments | 90 days, then the text fields are deleted |
| Question and feedback records without text | 1 year |
| Widget activity | 90 days (already folded into daily summaries) |
| Daily summaries | indefinitely (no text, no IDs) |

Both Firestore and DynamoDB can delete records automatically from an `expire_at` date on each record
(TTL), so retention doesn't depend on a cleanup job.

## What the college would see

A dashboard built from the daily summaries:

- daily and weekly users
- questions per day
- topics over time
- the most-asked questions
- the "couldn't answer" list (content to add or surface on the sites)
- percent thumbs-up
- decline and error rates
- speed and cost per month
- future vs. current split
- busiest hours and mobile share

Seeing individual question text should be limited to named maintainers.

## Storage options

The record shapes above map directly onto either choice:

| | Firestore (Firebase) | AWS |
| --- | --- | --- |
| Where records go | collections `questions`, `feedback`, `widget_events`, `daily` | DynamoDB tables with the same names (key: `day` + `ts#id`), or one Postgres database |
| Writes from the server | `firebase-admin` with a service account | `boto3` with an IAM role |
| Automatic expiry | TTL policy on `expire_at` | DynamoDB TTL on `expire_at` (Postgres: nightly delete) |
| Cost at ~1,000 questions/day | ~4,000 writes/day, within the free daily quota (20K writes, 50K reads) | pennies a month on DynamoDB on-demand |
| Dashboards | read `daily` records; Looker Studio via BigQuery export | read `daily` items; QuickSight, or SQL if Postgres |

If AWS is chosen, I'd recommend Postgres over DynamoDB when people want to ask ad-hoc questions of the
data ("show transfer questions from last week"). DynamoDB is simpler to run but harder to query. Either way,
the app gets one `record(event)` function with interchangeable back ends: a local file for development, plus
Firestore, DynamoDB or Postgres in production. Switching later means changing settings, not code.

## Today: the hosted beta

Built in `app/records.py`. The hosted beta writes to Firestore; local runs write `data/usage.jsonl` and
`data/feedback.jsonl`. [DEPLOY.md](DEPLOY.md) covers reading them.

- **Question records:**
  - who and when: `id`, `ts`, `day`, `user`, `session`, `turn`, `audience`
  - what was said: `question` (redacted, ≤ 1,000 characters; empty for crisis), `answer` (redacted, in full),
    `sources`
  - what happened: `outcome`, `topic`, `gate`, `gap`, `error`
  - cost and speed: `seconds`, `cost_usd`, `model`, `version`, token counts (`input`, `output`,
    `cache_read`, `cache_write`, `calls`)
  - `expire_at`
- **Feedback records:** `id`, `ts`, `day`, `user`, `question_id`, `rating`, `comment`, and for now copies of the
  question and answer.
- **Spend:** one `spend/<day>` record with the day's total, so the daily cap survives restarts.
- **Retention:** Firestore deletes each record 90 days after it's written (a TTL policy on `expire_at`). The
  plan's year of text-free records isn't built; for the beta, everything goes at 90 days.
- **Not built yet:** `tools`, `device`, widget activity and daily summaries.

## Open questions

1. **Firestore or AWS?** Firestore for the beta, in the maintainer's Firebase project (decided 2026-10-21).
   The long-term home is still open, and the schema doesn't change either way.
2. **Keep answer text?** Yes for the beta: every question and answer is saved for 90 days, and the login
   page tells testers (decided 2026-10-21).
3. **Retention periods:** are 90 days of text and 1 year of records acceptable to the Privacy Office?
4. **Who can see individual questions,** as opposed to totals only?
5. **Track widget activity** (opens, clicks)? It's needed for "how many people opened it but didn't ask".
6. **Mobile vs. desktop:** is the coarse device class worth recording?
7. **Public numbers:** which totals can be shared outside the team, for example on a resume or in a report?
