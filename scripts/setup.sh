#!/bin/bash
# One-time project setup for the myworld app; deploying afterwards is
# gcloud_run_deploy.sh (utils-bash). Safe to re-run: every step
# skips what already exists. The OAuth client ID cannot be scripted and is
# created by hand (see doc/deploy.md), then pasted into .gcp.conf.
#
# Cost warning: this creates a Cloud SQL instance, which is billed per hour
# whether or not the app is used.

set -euo pipefail

cd "$(dirname "${0}")/.."

# shellcheck source=/dev/null
source .gcp.conf
export CLOUDSDK_ACTIVE_CONFIG_NAME="${gcp_configuration_name}"

PROJECT_ID="$(gcloud config get-value project)"
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
SERVICE_ACCOUNT_NAME="${gcp_service}-app-sa"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "project ${PROJECT_ID} (${PROJECT_NUMBER})"

echo "== enabling APIs"
gcloud services enable \
	run.googleapis.com \
	cloudbuild.googleapis.com \
	artifactregistry.googleapis.com \
	sqladmin.googleapis.com \
	secretmanager.googleapis.com

echo "== service account the app runs as"
if ! gcloud iam service-accounts describe "${SERVICE_ACCOUNT}" >/dev/null 2>&1; then
	gcloud iam service-accounts create "${SERVICE_ACCOUNT_NAME}" \
		--display-name "${gcp_service} Cloud Run service"
fi
for role in roles/cloudsql.client roles/secretmanager.secretAccessor; do
	gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
		--member "serviceAccount:${SERVICE_ACCOUNT}" \
		--role "${role}" \
		--condition None \
		--quiet >/dev/null
done
# Cloud Build (used by `gcloud run deploy --source`) deploys as the compute
# default service account and needs to be allowed to act as the app's SA.
gcloud iam service-accounts add-iam-policy-binding "${SERVICE_ACCOUNT}" \
	--member "serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
	--role roles/iam.serviceAccountUser \
	--quiet >/dev/null

echo "== Cloud SQL instance ${gcp_sql_instance}"
if ! gcloud sql instances describe "${gcp_sql_instance}" >/dev/null 2>&1; then
	gcloud sql instances create "${gcp_sql_instance}" \
		--database-version POSTGRES_17 \
		--edition ENTERPRISE \
		--tier db-f1-micro \
		--region "${gcp_region}" \
		--storage-type HDD \
		--storage-size 10GB \
		--no-storage-auto-increase \
		--availability-type zonal \
		--backup-start-time 03:00
fi
if ! gcloud sql databases describe "${gcp_db_name}" --instance "${gcp_sql_instance}" >/dev/null 2>&1; then
	gcloud sql databases create "${gcp_db_name}" --instance "${gcp_sql_instance}"
fi

echo "== secrets"
create_secret_if_missing() {
	local name="${1}"
	if gcloud secrets describe "${name}" >/dev/null 2>&1; then
		return 1
	fi
	gcloud secrets create "${name}" --replication-policy automatic
}
if create_secret_if_missing "${gcp_service}-db-pass"; then
	DB_PASS="$(openssl rand -base64 30 | tr -d '/+=')"
	printf '%s' "${DB_PASS}" | gcloud secrets versions add "${gcp_service}-db-pass" --data-file -
	if gcloud sql users list --instance "${gcp_sql_instance}" --format 'value(name)' | grep -qx "${gcp_db_user}"; then
		gcloud sql users set-password "${gcp_db_user}" --instance "${gcp_sql_instance}" --password "${DB_PASS}"
	else
		gcloud sql users create "${gcp_db_user}" --instance "${gcp_sql_instance}" --password "${DB_PASS}"
	fi
fi
if create_secret_if_missing "${gcp_service}-secret-key"; then
	openssl rand -hex 32 | tr -d '\n' | gcloud secrets versions add "${gcp_service}-secret-key" --data-file -
fi

echo "== done"
if [[ -z "${gcp_oauth_client_id}" ]]; then
	echo "next: create the OAuth client (doc/deploy.md) and set gcp_oauth_client_id in .gcp.conf"
fi
echo "then: gcloud_run_deploy.sh"
