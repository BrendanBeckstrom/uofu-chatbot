#!/usr/bin/env bash
# Deploys the beta (docs/DEPLOY.md): the server to Cloud Run, then the pages to Firebase Hosting.
#
#   ./deploy/deploy.sh           # both
#   ./deploy/deploy.sh server    # code, prompt or search-index changes
#   ./deploy/deploy.sh pages     # login page, demo page or widget changes
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh
WHAT="${1:-all}"

[[ -f data/docs.json ]] || { echo "data/docs.json is missing. Build the index first: python -m app.sync build"; exit 1; }
VERSION="$(git rev-parse --short HEAD)"
if [[ -n "$(git status --porcelain -- app web requirements.txt Dockerfile)" ]]; then
  VERSION="$VERSION-modified"
  echo "Note: deploying changes that aren't committed yet (version $VERSION)."
fi

if [[ $WHAT == all || $WHAT == server ]]; then
  # One instance at most: rate limits, sessions and the answer cache live in the server's memory.
  gcloud run deploy "$SERVICE" --source . --region "$REGION" --quiet \
    --service-account "$SERVER_ACCOUNT" --allow-unauthenticated \
    --min-instances 0 --max-instances 1 --cpu 1 --memory 1Gi --cpu-boost --timeout 120 \
    --set-env-vars "^@^LOG_BACKEND=firestore@AUTO_SYNC=false@TRUST_PROXY=true@TOKEN_TTL_HOURS=168@APP_VERSION=$VERSION@ALLOWED_ORIGINS=https://$PROJECT.web.app,https://$PROJECT.firebaseapp.com" \
    --set-secrets "ANTHROPIC_API_KEY=anthropic-api-key:latest,CHAT_TOKEN_SECRET=chat-token-secret:latest,BETA_PASSWORD=beta-password:latest"
fi

if [[ $WHAT == all || $WHAT == pages ]]; then
  API="$(gcloud run services describe "$SERVICE" --region "$REGION" --format 'value(status.url)')"
  rm -rf build/hosting
  mkdir -p build/hosting
  cp web/*.html web/widget.js web/wake.js build/hosting/
  printf 'window.PRICE_ASSISTANT_API = "%s";\n' "$API" > build/hosting/config.js
  firebase deploy --only hosting,firestore:rules --project "$PROJECT"
fi

echo "Live at https://$PROJECT.web.app"
