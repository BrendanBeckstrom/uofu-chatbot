# Settings shared by the deploy scripts. Override any of them from the environment, e.g.
#   PROJECT=my-fork ./deploy/deploy.sh
PROJECT="${PROJECT:-uofuchatbot}"        # the Firebase / Google Cloud project
REGION="${REGION:-us-central1}"          # Cloud Run region; the Firestore database is here too
SERVICE="${SERVICE:-price-assistant}"    # the Cloud Run service
SERVER_ACCOUNT="chatbot-server@${PROJECT}.iam.gserviceaccount.com"

export CLOUDSDK_CORE_PROJECT="$PROJECT"
if [[ -n "${ACCOUNT:-}" ]]; then          # which of your Google logins gcloud uses
  export CLOUDSDK_CORE_ACCOUNT="$ACCOUNT"
fi
