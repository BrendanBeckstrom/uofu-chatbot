#!/usr/bin/env bash
# One-time setup of a Google Cloud / Firebase project for the beta (docs/DEPLOY.md). Safe to re-run.
# The project must be on the Blaze plan first, because Cloud Run needs a billing account.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  firestore.googleapis.com secretmanager.googleapis.com firebasehosting.googleapis.com

# The database location is permanent.
if ! gcloud firestore databases describe --database="(default)" >/dev/null 2>&1; then
  gcloud firestore databases create --location="$REGION" --type=firestore-native
fi

# The server runs as its own account that can use Firestore and nothing else; deploy/secrets.sh lets it
# read its secrets.
if ! gcloud iam service-accounts describe "$SERVER_ACCOUNT" >/dev/null 2>&1; then
  gcloud iam service-accounts create chatbot-server --display-name="Price assistant server (Cloud Run)"
fi
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SERVER_ACCOUNT" \
  --role=roles/datastore.user --condition=None >/dev/null

# Firestore deletes each record once its expire_at time passes (LOG_RETENTION_DAYS).
for group in questions feedback; do
  gcloud firestore fields ttls update expire_at --collection-group="$group" --enable-ttl --async >/dev/null
done

echo "Setup done. Next: ./deploy/secrets.sh, then ./deploy/deploy.sh"
