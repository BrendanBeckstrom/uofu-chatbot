# Going live on price.utah.edu

Today the assistant runs as a password-protected beta for internal testing, on the maintainer's own accounts
([DEPLOY.md](DEPLOY.md)). This page is for whoever takes it live on the college website with the university.
It covers:

- what's set up only for the beta
- the decisions that are still open, and why they can't be made yet
- what we learned about the website and about hosting (November 2026)
- the questions for university offices
- a launch checklist

Nothing here is decided unless it says so. The repo, the Google Cloud project and the API key belong to the
student who built it and will move to university accounts before the handoff.

## Set up only for the beta

These are deliberate for internal testing. Each needs changing before the public can use it. The limits and
the budget are the defaults in `app/config.py`, so they apply anywhere until they're changed. The rest are
set in `deploy/deploy.sh`.

| What | In the beta | On the public site |
| --- | --- | --- |
| Shared password (`BETA_PASSWORD`, `web/login.html`) | Only testers get a browser token | No password: the site is public. Remove the secret and the login page. Anyone can then get a token, so consider Cloudflare Turnstile in front of `/api/token`. |
| Limit for everyone combined (`GLOBAL_CHAT_LIMITS`: 30 questions a minute, 600 an hour) and 8 answers at once (`MAX_CONCURRENT_ANSWERS`) | Caps the beta's total use | A public site limits each visitor: per browser (`TOKEN_LIMITS`) and per IP (`IP_LIMITS`), which already exist. A cap this low would turn everyone away during one busy minute. Raise it well above measured peak traffic, or remove it. |
| Daily spending cap (`DAILY_BUDGET_USD`: $5) | Plenty for testing | Raise to match real traffic, together with a monthly limit on the university's Anthropic workspace. |
| Server shuts down after about 15 idle minutes and takes up to 2 minutes to start (`--min-instances 0`, `web/wake.js`) | Saves money | Keep one server running; visitors won't wait. |
| Pages allowed to call the server | The two Firebase Hosting addresses (`ALLOWED_ORIGINS`), plus `localhost` and `(www.)price.utah.edu`, which `app/server.py` always allows for the bookmarklet preview | Add any department site that shows the widget to `ALLOWED_ORIGINS`. Browsers block the widget on pages not allowed. |
| Browser tokens last a week (`TOKEN_TTL_HOURS=168` in `deploy/deploy.sh`) | Testers stay signed in | The default (24 hours) is fine. |
| Question and answer records kept 90 days in the maintainer's Firebase project | Testers are told on the login page | Decided with the Privacy Office (see below). |
| Crawler name: `PriceChatbotPOC/0.1 (University of Utah student proof-of-concept)` | Honest for a student project | An official name with a contact address (`SCRAPER_USER_AGENT`). |
| The server also serves the demo page (`/`) and a raw search view (`/api/search`) | Handy for testing | Not needed by the widget. |

Content refreshing only when someone redeploys (`AUTO_SYNC=false`) is fine to keep. To have the server refresh
itself instead, see "Keeping content current on a server" in [ARCHITECTURE.md](ARCHITECTURE.md).

## Known security issues

An independent code review on November 11, 2026 found these. It found no way to run code, inject HTML into the
widget, or read the secrets.

**Fixed:** the answer cache ignored symbols, so a first question with hidden text (invisible characters, or
letters like ⓐⓑⓒ) shared a cache entry with the plain question. Its answer could then have reached everyone
asking the plain question for 6 hours. Now such a message is answered fresh and never cached (`_cache_key()` in
`app/chat.py`, tested in `tests/test_chat_loop.py`).

**Accepted for the beta.** These were left on purpose, because only invited testers use the beta. Fix each one
before the public can reach it.

| Issue | Why it's fine for now | Fix before going public |
| --- | --- | --- |
| **IPs can be faked on the beta.** With `TRUST_PROXY=true`, `client_ip()` (`app/guard.py`) believes a `CF-Connecting-IP` header. Cloud Run has no Cloudflare in front, so anyone can send one. That gets around the password's 10-tries limit and every per-IP limit. | Few people know the beta exists, and the $5 daily cap limits what someone past the password could spend. | Read `CF-Connecting-IP` only under a separate Cloudflare-only setting. On Cloud Run, use the `X-Forwarded-For` entry Cloud Run adds (check its format first). |
| **One script can crowd out everyone.** Browser tokens are free to get, and the combined limits and the 8 answers at once are shared by all visitors. `/api/search` needs no token, and its live WordPress fallback waits in the same per-site queue as the chat's page reads. | Only matters with public traffic. | Turnstile before tokens; a per-IP share of the combined limit; a token on `/api/search`, or no live fallback there. |
| **Memory can be run out.** `/api/token` reads the whole request body before checking its size; the reviewer confirmed a 300 MB body was accepted. The limiters' key cap (`MAX_KEYS`) isn't enforced, and the page and calendar caches never drop entries. | A crash restarts the server; it only resets limits, open chats and spend reservations. | Cap the token body while reading; make `MAX_KEYS` drop the oldest keys; give the caches a size limit. |
| **The chat-summary PDF keeps any link an answer contained** (see below). | A bad link would first have to get into an answer, and only testers download PDFs. | Run `allowed_url()` in `check()`, or keep only links the session actually read. |
| **Conversations aren't tied to their browser token,** and `/api/reset` needs no token. | Misuse needs a leaked 128-bit session ID. | Reject a token that doesn't match the session's user; require one on reset. |
| **Privacy gaps.** Redaction misses forms like "u 1234567" and "U-1234567", and names. A crisis message the gate misses, or that arrives while the gate is failing, is logged in full. Feedback stores the question and answer text the browser sends. | It's a beta: testers are told chats are saved and asked to leave out personal details. The university's privacy review comes with going live. | Wider patterns; don't log turns whose answer is the crisis reply; store feedback by question ID only. |
| **Small crashes.** A URL with a bad port raises in the source list, which ends the answer stream. A non-ASCII token header returns a 500. | They only affect the request that triggers them. | Catch the `ValueError` and the `TypeError`. |

### Links in the chat-summary PDF

The widget makes only `utah.edu` links clickable. The take-home PDF (`app/summary.py`) is looser: `check()` keeps
a link if any of the chat's answers contained it, whatever its site. So if text planted in a page or a question
got the bot to write a link to another site, the widget would show it as plain text, but the PDF would print
it as a working link on a University-branded page. Two other things to know:

- "Any `*.utah.edu`" also covers pages people host themselves on university servers.
- The fix is small: keep a highlight's or key point's link only if `allowed_url()` accepts it, or only if the
  chat actually read that page.

Also: `app/config.py` reads `CLAUDE_MODEL`, the kind of generic `CLAUDE_*` name CLAUDE.md warns against.
Renaming it (for example to `CHATBOT_MODEL`) would change the setting's name everywhere it's documented.

## Decisions that can't be made yet

Each depends on something we don't know yet. Keep the current behavior until it's known.

- **Where the server runs.** The university has agreements with AWS, Microsoft Azure and Google Cloud, and
  UIT's Cloud Center of Excellence helps choose ([cloud.utah.edu](https://cloud.utah.edu/)). It depends on
  who will maintain it. The beta is on Google Cloud. "Hosting options we looked at" below covers what a move
  involves.
- **How Claude is reached and paid for.** Options: an Anthropic API key on a university account, Amazon
  Bedrock, or Claude Platform on AWS. It depends on purchasing and on the university's AI tool approval. On
  November 9, 2026, [ai.utah.edu/tools](https://ai.utah.edu/tools/) listed Claude as "Under review", with
  approved tools limited to public data. New tools go through the AI Tool Form, reviewed by IT, information
  security and legal ([FAQ](https://ai.utah.edu/faq.php)).
- **Where conversations are kept.** In the server's memory. A restart ends the open chats, and a second server
  wouldn't see the first one's chats or limits. Keep it this way until hosting and traffic are known. If more
  than one server is ever needed, move sessions, rate limits, the day's spend and the answer cache to a shared
  store such as Redis.
- **Rate-limit and budget numbers.** They need real traffic. Nobody knows yet how many students share one
  campus Wi-Fi address, which decides how loose `IP_LIMITS` must be.
- **Usage records.** What's kept, for how long, who may read individual questions, and where it lives. That's
  for the Privacy Office. Today every question and answer is kept for 90 days, with uNIDs, emails and phone
  numbers redacted. The storage is swappable (`app/records.py`). Ideas never built: widget-activity records
  (opens and clicks), daily summaries without text, and keeping text-free records for a year.
- **The university's privacy and security review.** The university will apply its own standards. Expect
  questions about sending chat text to Anthropic, about a privacy statement (Rule 4-003F), and about the logs.
- **Crisis reply wording** (`CRISIS` in `app/scope.py`, and the support card in the widget's Contact tab) needs
  sign-off from the University Counseling Center.
- **Accessibility review** of the widget as embedded (WCAG 2.1 AA).

### Things that will go stale

Much of the college's content is old: on November 11, 2026, 45% of pages and 86% of news posts were more than
2 years old (ARCHITECTURE.md, "Old sources"). The bot flags old sources and names the office to ask, but the
real fix is updating the sites ([SITE_AUDIT.md](SITE_AUDIT.md)). Facts typed into the code by hand also go
stale and need re-checking each semester:

- each department's office contact (`SITES` in `app/config.py`, checked 2026-11-11)
- the college office's contact, in `SYSTEM_TEMPLATE` (`app/chat.py`) and the widget's Contact tab
- crisis resources, in `CRISIS` (`app/scope.py`, checked 2026-10-14) and the widget's Contact tab
- the campus office pages (`CAMPUS_PAGES` in `app/documents.py`)
- the eval answers, each dated by its `as_of` field (`evals/questions.json`)

## The college website (checked November 11, 2026)

- **What it runs:** price.utah.edu and six department sites run WordPress (PHP) on WP Engine, behind
  Cloudflare. mse.utah.edu is served from a college server (`flame.coe.utah.edu`).
  - The theme is Uncode with the WPBakery page builder.
  - The college has its own plugins (`coe`, `wpbakery-coe-elements`, `coe-job-board`), so someone writes
    WordPress code for it.
- **No Content-Security-Policy header,** so an added script isn't blocked. The site loads Google Analytics.
- **WP Engine only runs WordPress,** so the Python server has to be hosted elsewhere. Rewriting the bot as a
  WordPress plugin would mean porting it to PHP and running long streaming answers on the website's own
  server. Not recommended.

### Putting the widget on a page

The widget is one file that draws itself inside a Shadow DOM, so it won't clash with the theme:

```html
<script src="https://YOUR-SERVER/widget.js" defer></script>
```

- **Optional attributes:**
  - `data-api`: the server's address, if it isn't where `widget.js` came from
  - `data-open="true"`: start with the chat open
  - `data-load-fonts="false"`: don't load the fallback fonts
  - `data-adobe-fonts="<project id>"`: the University's Myriad Pro and Factoria
- **From the page's own scripts:** `PriceAssistant.open()` and `PriceAssistant.ask("question")`.
- **Who adds it:** anyone with WordPress admin can paste the line, so nobody needs access to the web team's
  code. A pilot on one page could use a WPBakery Raw HTML element.

**Preview on the live site, in your browser only.** With the server running locally, make a bookmark whose
address is the line below. Open https://www.price.utah.edu/ and click the bookmark. Chrome asks whether the
site may reach your local network; allow it. Nothing changes on the real site.

```
javascript:(()=>{const s=document.createElement('script');s.src='http://localhost:8000/widget.js';s.dataset.api='http://localhost:8000';s.dataset.loadFonts='false';s.dataset.open='true';document.body.appendChild(s)})()
```

## Hosting options we looked at (November 2026)

No AWS code was written on purpose: the destination isn't decided, and it can't be tested without an account.

### What any host needs

- **One always-on container.** The `Dockerfile` runs anywhere, and every setting comes from the environment.
- **One process.** Conversations and limits live in memory (see above).
- **Answers stream for up to 90 seconds.** Any proxy or load balancer in front must allow that. Firebase
  Hosting cuts requests off at 60 seconds, which is why the beta's pages call Cloud Run directly.

### Moving to AWS

- **Claude:**
  - The client is created once, in `ChatEngine.__init__` (`app/chat.py`). The scope gate and the summary
    reuse it.
  - Two AWS routes, both in the installed `anthropic` SDK:
    - **Amazon Bedrock**, run by AWS: `AsyncAnthropicBedrockMantle`. Bedrock lists Claude Haiku 5.5. Its
      model IDs have an `anthropic.` prefix; check the exact ID on the model card.
    - **Claude Platform on AWS**, run by Anthropic: `AsyncAnthropicAWS`. The same API and model IDs, with AWS
      sign-in and billing.
  - What the bot uses (streaming, tools, effort, structured output, prompt caching) is available on both.
  - Bedrock has no Models API, which `fallback_args()` in `app/chat.py` calls on every question until it gets
    an answer. Skip that call there.
  - Bedrock's prices are set by AWS: update `PRICES` in `app/pricing.py`, then run the answer eval.
- **Hosting:** one always-on container, for example ECS Fargate with one task. Lambda doesn't fit, because of
  the memory-held state and the streaming answers.
- **Records:**
  - Add a DynamoDB or Postgres class to `app/records.py` with the same methods as `Firestore`: `save`, `read`,
    `get_spend`, `put_spend` and `flush`.
  - `app/guard.py` (the spend cap) and `app/analytics.py` (`--firestore`) check for Firestore by name; point
    them at the new one.
- **Secrets:** Secret Manager becomes AWS Secrets Manager.
- **Deploy scripts:** `deploy/` is written for Google Cloud and Firebase and would be replaced.

### Amazon Bedrock AgentCore

AgentCore is AWS's platform for running agents. Its Runtime hosts agent code with each user session in its own
microVM (up to 8 hours), and it adds memory, a gateway, identity and monitoring services. It works with Claude
([overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)).
It's a poor fit for this bot:

1. **Separate sessions break the shared state.** The bot shares its rate limits, spend cap, answer cache and
   search index across all visitors. With one microVM per session, each of those would need an outside store,
   and every session would load the index again.
2. **Callers need AWS credentials or an OAuth token**
   ([inbound auth](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html)). An
   anonymous visitor has neither, so a public server would still sit in front to hand out tokens, apply limits
   and pass the stream through.
3. **Its strengths are things this bot deliberately doesn't do:** acting for a signed-in user, running code,
   using a browser, long multi-agent jobs. This bot has three read-only tools.

It would be worth another look if the university standardizes on it for all its agents, or if the bot starts
acting for signed-in students.

## Questions for university offices

Grouped by who can answer them.

**API key and billing** (college finance or the Dean's office, UIT)
- Whose Anthropic account? It should be university-owned. Who's the admin, and which cost center pays?
- What monthly budget, and who gets the spending alerts? The Default workspace can't have a spending limit, so
  make a workspace for the chatbot. Testing cost about $0.001–0.003 per answer.
- Does a university cloud agreement cover Claude (Bedrock, Vertex AI)? That could simplify purchasing and
  data terms.

**Connecting to the website** (web team, college Marketing & Communications)
- Who can add the script line, and where: the theme, a header/footer setting, or one page first?
- Where should the server live, and at what address (for example `assistant.price.utah.edu`)? Who manages DNS
  and HTTPS for price.utah.edu?
- Is it OK to keep reading the public WordPress API? Can the bot's user agent be allowed in Cloudflare so syncs
  aren't blocked?
- Where should the launcher appear on desktop and mobile, and who can switch it off quickly?

**Hosting and ownership** (UIT or college IT)
- Which cloud account or server, and who maintains it?
- Where does the code live (a university GitHub organization)? Who owns it? It was built by a student
  ambassador, so check the university's intellectual property policy.

**Privacy, security and accessibility** (Information Security Office, Privacy Office, accessibility)
- What does the formal review need from us?
- Can question logs be kept? For how long, and who can see them? Is a privacy notice needed?
- Is sending chat text to Anthropic allowed (Rule 4-003F)? Is a zero-data-retention agreement needed?
- Who does the WCAG 2.1 AA review?

**Content and safety** (Marketing & Communications, Student Affairs, advising, Counseling Center)
- Who approves the crisis wording?
- Which topics must always go to a person: admissions decisions, financial aid, Title IX, disability
  accommodations?
- Who hears about pages the bot finds outdated or conflicting? The site content audit lists them.
- Should it cover Admissions, Financial Aid or the Registrar? Today those are read live, not indexed.
- Who approves the name, the "unofficial, experimental" disclaimer and the use of University branding? Who
  reads the thumbs up and down?

**Pilot and launch**
- One page, ambassadors only, or a fixed time window? What counts as success, and who signs off?

## Launch checklist

- [ ] Server, API key and records on university accounts
- [ ] `.github/CODEOWNERS` removed, or changed to the new maintainer, along with the code-owner approval in
      the "Protect main" ruleset. Until then every merge needs the student's approval.
- [ ] Anthropic workspace for the chatbot with a monthly limit and alerts; the key used during development
      rotated
- [ ] Privacy and security review done; retention decided; privacy notice published if needed
- [ ] Beta settings changed (table above): no password, limits and budget sized, always on, the site in
      `ALLOWED_ORIGINS` (department sites; price.utah.edu is already allowed)
- [ ] Behind Cloudflare or a load balancer: the server accepts traffic only from it, and `TRUST_PROXY=true` is
      set. Otherwise anyone can fake their IP and dodge the per-IP limits.
- [ ] Turnstile in front of new browser tokens
- [ ] The issues accepted for the beta (above) fixed, with a test for each
- [ ] Monitoring: cost and errors per day, and alerts at 50/80/100% of the daily cap
- [ ] Crisis wording approved; accessibility review done
- [ ] Gate cases pass three times (`evals.run answers --only gate --reps 3`), plus a full answer eval
