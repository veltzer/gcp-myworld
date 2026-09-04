#!/bin/bash
# Map the custom domain (gcp_domain in .gcp.conf) to the Cloud Run service
# and print the DNS records to create at the registrar (Cloudflare). Safe to
# re-run: it creates the mapping only if missing and always prints the
# records, which is also how to check the certificate status later.
#
# Prerequisites, both one-time and by hand (see doc/deploy.md):
#   - the service is deployed (gcloud_run_deploy.sh)
#   - the domain is verified for your Google account (`gcloud domains verify`)

set -euo pipefail

cd "$(dirname "${0}")/.."

# shellcheck source=/dev/null
source .gcp.conf
export CLOUDSDK_ACTIVE_CONFIG_NAME="${gcp_configuration_name}"
: "${gcp_domain:?must be set in .gcp.conf}"

echo "== domain mapping ${gcp_domain} -> ${gcp_service} (${gcp_region})"
if ! gcloud beta run domain-mappings describe --domain "${gcp_domain}" --region "${gcp_region}" >/dev/null 2>&1; then
	gcloud beta run domain-mappings create --service "${gcp_service}" --domain "${gcp_domain}" --region "${gcp_region}"
fi

echo "== DNS records to create at the registrar for ${gcp_domain} (proxy off / DNS only)"
gcloud beta run domain-mappings describe --domain "${gcp_domain}" --region "${gcp_region}" \
	--flatten status.resourceRecords \
	--format 'table[no-heading](status.resourceRecords.type, status.resourceRecords.rrdata)'

echo "== status (the certificate is issued once the records resolve; can take up to an hour)"
gcloud beta run domain-mappings describe --domain "${gcp_domain}" --region "${gcp_region}" \
	--flatten status.conditions \
	--format 'table(status.conditions.type, status.conditions.status, status.conditions.message)'
