# Hosting the beta

The beta runs on Google Cloud through Firebase, under the `uofuchatbot` project. This page covers how it
fits together, how to deploy a change, the beta password, and how to read what testers asked.

## What runs where

| Piece | Where | What it does |
| --- | --- | --- |
| Pages | Firebase Hosting, https://uofuchatbot.web.app | The login page (`web/login.html`), the demo page, the widget and the design concepts. Static files only. |
| Server | Cloud Run, service `price-assistant` in `us-central1` | The same FastAPI app as locally (`app/`), built from the `Dockerfile` with the search index (`data/docs.json`) inside. |
| Logs | Firestore, `(default)` database in `us-central1` | One record per question and per thumbs up/down, and the day's spend (`app/records.py`). |
| Secrets | Secret Manager | `anthropic-api-key`, `chat-token-secret` (signs browser tokens) and `beta-password`. |

The pages call the Cloud Run server directly, not through Firebase Hosting. Hosting cuts off any request
at 60 seconds, and a streamed answer can take up to 90. `deploy/deploy.sh` writes `config.js` into the
Hosting copy of the pages with the server's address. Locally the server serves a `config.js` that points
at itself.

The server runs as its own service account, `chatbot-server`. It can use Firestore and read its three
secrets, and nothing else. `firestore.rules` gives browsers no access at all.

## Settings on Cloud Run

`deploy/deploy.sh` sets these on top of the defaults in `app/config.py`:

| Setting | Value | Why |
| --- | --- | --- |
| `LOG_BACKEND` | `firestore` | The server's disk is wiped on every restart, so logs and the day's spend go to Firestore. |
| `AUTO_SYNC` | `false` | Cloud Run pauses the CPU between requests, so a background content check wouldn't finish. Content is refreshed by redeploying. |
| `TRUST_PROXY` | `true` | Cloud Run puts the visitor's IP in `X-Forwarded-For`; without it every visitor would share one rate limit. |
| `TOKEN_TTL_HOURS` | `168` | Testers stay signed in for a week. |
| `ALLOWED_ORIGINS` | the two Firebase Hosting addresses | Lets those pages call the server. |
| `APP_VERSION` | the git commit | Saved on each question record, to compare answers before and after a change. |
| `BETA_PASSWORD`, `ANTHROPIC_API_KEY`, `CHAT_TOKEN_SECRET` | from Secret Manager | |

The server is capped at one instance (`--max-instances 1`), because rate limits, conversations and the answer
cache live in its memory. When nobody has used it for a while, Cloud Run shuts it down. The next visitor
waits a few extra seconds while it starts, and any open conversation starts over.

## Deploying a change

Merge the change first, then from `main`:

```bash
./deploy/deploy.sh           # server and pages
./deploy/deploy.sh server    # code, prompt or search-index changes (about 3–5 minutes)
./deploy/deploy.sh pages     # login page, demo page or widget changes (under a minute)
```

The script uses whichever Google login `gcloud` and `firebase` are signed in with. To pick one, run
`ACCOUNT=you@example.com ./deploy/deploy.sh`.

**Refreshing the content:** the index ships inside the server, so update it locally and redeploy:

```bash
.venv/bin/python -m app.sync update      # pages and news edited since the last check
.venv/bin/python -m app.sync documents   # handbooks, plans, flowcharts
./deploy/deploy.sh server
```

**If something's wrong:** the server's logs are at
https://console.cloud.google.com/run/detail/us-central1/price-assistant/logs?project=uofuchatbot, or run
`gcloud run services logs read price-assistant --region us-central1`. To roll back, choose an earlier
revision under "Revisions" in the same console page and send it all traffic.

## The beta password

Testers open https://uofuchatbot.web.app, enter the shared password on the login page, and get a browser
token that lasts a week. The server issues tokens only for the right password. Ten wrong tries from one
network pause sign-ins there for 10 minutes.

To change the password, run this in your own terminal. It asks for the new password without showing it:

```bash
./deploy/secrets.sh beta-password
./deploy/deploy.sh server
```

Changing it signs every tester out, because tokens are signed with a key derived from the password.

## Reading the logs

**In the console:** https://console.firebase.google.com/project/uofuchatbot/firestore/data shows the
`questions` and `feedback` collections. Each question record has:
- the question and the full answer (redacted, with crisis messages never stored)
- `outcome`: answered, declined, crisis, cached, search_only or error
- `topic`, `gate`, `audience`, `gap`, `sources`
- `seconds`, `cost_usd`, token counts and `version`

Feedback records point at their question through `question_id`. [DATA_PLAN.md](DATA_PLAN.md) lists every
field.

**As a report:**

```bash
gcloud auth application-default login                 # once
GOOGLE_CLOUD_PROJECT=uofuchatbot .venv/bin/python -m app.analytics --firestore --days 7
```

Firestore deletes each record 90 days after it's written (`LOG_RETENTION_DAYS`, through a TTL policy on
`expire_at`).

## Cost

The project is on the Blaze plan, which Cloud Run requires. A beta this size should stay inside the free
tiers: Firestore allows 20,000 writes and 50,000 reads a day, and each question takes about three writes.
Blaze has no hard spending cap, so keep the budget alert in the Firebase console's Usage and billing page.

Claude usage is billed separately by Anthropic and is still capped by `DAILY_BUDGET_USD` ($5 a day by
default). The spend counter lives in Firestore, so a restart doesn't reset it.

## Setting up a new project

This is only needed for a fresh project, such as the university's own fork:

1. Create a Firebase project and upgrade it to Blaze.
2. Sign in: `gcloud auth login` and `firebase login`.
3. Point the scripts at it: set `PROJECT` (and `REGION`) in `deploy/config.sh`, and the project in
   `.firebaserc`.
4. Run `./deploy/setup.sh`. It enables the services, creates the Firestore database (its location is
   permanent), creates the server's service account and turns on record expiry.
5. Run `./deploy/secrets.sh` in your own terminal. It stores the Claude key from `.env`, makes a
   token-signing key, and asks for the beta password.
6. Build the index if you haven't (`python -m app.sync build`, then `documents`), and run
   `./deploy/deploy.sh`.
