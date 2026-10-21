#!/usr/bin/env bash
# Stores the server's secrets in Google Secret Manager (docs/DEPLOY.md). Run it in your own terminal:
# it reads the Claude API key from .env and asks for the beta password, and never prints either.
#
#   ./deploy/secrets.sh                      # first time: everything that's missing, plus the API key
#   ./deploy/secrets.sh beta-password        # change the beta password (signs every tester out)
#   ./deploy/secrets.sh anthropic-api-key    # after changing ANTHROPIC_API_KEY in .env
#
# Then run ./deploy/deploy.sh server so the server picks up the new values.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh
WHICH="${1:-missing}"

exists() { gcloud secrets describe "$1" >/dev/null 2>&1; }

put() {  # stores stdin as the newest version of secret $1, readable only by the server's account
  if exists "$1"; then
    gcloud secrets versions add "$1" --data-file=- >/dev/null
  else
    gcloud secrets create "$1" --replication-policy=automatic --data-file=- >/dev/null
  fi
  gcloud secrets add-iam-policy-binding "$1" --member="serviceAccount:$SERVER_ACCOUNT" \
    --role=roles/secretmanager.secretAccessor >/dev/null
  echo "✓ $1 saved"
}

if [[ $WHICH == missing || $WHICH == anthropic-api-key ]]; then
  key=$(sed -nE "s/^ANTHROPIC_API_KEY=['\"]?([^'\"[:space:]]+)['\"]?.*/\1/p" .env | head -n 1)
  [[ -n $key ]] || { echo "No ANTHROPIC_API_KEY found in .env"; exit 1; }
  printf '%s' "$key" | put anthropic-api-key
fi

if [[ $WHICH == chat-token-secret ]] || { [[ $WHICH == missing ]] && ! exists chat-token-secret; }; then
  python3 -c 'import secrets; print(secrets.token_urlsafe(32), end="")' | put chat-token-secret
fi

if [[ $WHICH == beta-password ]] || { [[ $WHICH == missing ]] && ! exists beta-password; }; then
  read -rsp "Beta password for testers (typing is hidden): " pw; echo
  read -rsp "Type it again: " pw2; echo
  [[ -n $pw && $pw == "$pw2" ]] || { echo "The two didn't match (or were empty). Nothing saved."; exit 1; }
  printf '%s' "$pw" | put beta-password
fi

echo "Done. Run ./deploy/deploy.sh server to use the new values."
