#!/bin/bash
# Deploy the myworld app to Cloud Run. Everything the service needs
# (Cloud SQL attachment, env vars, secrets, scaling, service account) lives
# here as flags, so a redeploy always converges the service to what this
# script says. One-time project setup is scripts/setup.sh.

set -euo pipefail

cd "$(dirname "${0}")/.."

# shellcheck source=/dev/null
source .gcp.conf
export CLOUDSDK_ACTIVE_CONFIG_NAME="${gcp_configuration_name}"

if [[ -z "${gcp_oauth_client_id}" ]]; then
	echo "gcp_oauth_client_id is empty in .gcp.conf; create the OAuth client first (doc/deploy.md)" >&2
	exit 1
fi

PROJECT_ID="$(gcloud config get-value project)"
SERVICE_ACCOUNT="${gcp_service}-app-sa@${PROJECT_ID}.iam.gserviceaccount.com"
INSTANCE_CONNECTION_NAME="${PROJECT_ID}:${gcp_region}:${gcp_sql_instance}"

# Stamp what is about to be deployed so the app can serve it back via
# /app/version. The Cloud Run revision name is not known before the deploy;
# the app reads it at runtime from the K_REVISION env var instead.
jq -n \
	--arg deploy_date "$(date --utc --iso-8601=seconds)" \
	--arg git_describe "$(git describe --always --dirty --tags)" \
	'{deploy_date: $deploy_date, git_describe: $git_describe}' > build_info.json

ENV_VARS="INSTANCE_CONNECTION_NAME=${INSTANCE_CONNECTION_NAME}"
ENV_VARS+=",DB_USER=${gcp_db_user}"
ENV_VARS+=",DB_NAME=${gcp_db_name}"
ENV_VARS+=",GOOGLE_CLIENT_ID=${gcp_oauth_client_id}"

exec gcloud run deploy "${gcp_service}" \
	--source . \
	--region "${gcp_region}" \
	--allow-unauthenticated \
	--service-account "${SERVICE_ACCOUNT}" \
	--add-cloudsql-instances "${INSTANCE_CONNECTION_NAME}" \
	--set-env-vars "${ENV_VARS}" \
	--set-secrets "DB_PASS=${gcp_service}-db-pass:latest,SECRET_KEY=${gcp_service}-secret-key:latest" \
	--max-instances 2 \
	--quiet
