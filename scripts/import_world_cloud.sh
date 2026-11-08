#!/bin/bash
# Run scripts/import_world.py against the Cloud SQL database from .gcp.conf:
# starts the Cloud SQL Auth Proxy with your gcloud credentials, takes the
# app's database password from Secret Manager (it never touches disk) and
# points DATABASE_URL at the proxy. Arguments go to import_world.py.
#
#   scripts/import_world_cloud.sh --email me@example.com [--source ../veltzer.github.io]
#
# The import creates its tables if they are missing (create_all), so it can
# run before or after deploying the version that shows them.

set -euo pipefail

cd "$(dirname "${0}")/.."

# shellcheck source=.gcp.conf
source .gcp.conf
export CLOUDSDK_ACTIVE_CONFIG_NAME="${gcp_configuration_name}"

for tool in cloud-sql-proxy pg_isready
do
	if ! command -v "${tool}" > /dev/null
	then
		echo "${0}: ${tool} not found on PATH (cloud-sql-proxy: gcloud components install cloud-sql-proxy; pg_isready: apt install postgresql-client)" >&2
		exit 1
	fi
done

password="$(gcloud secrets versions access latest --secret "${gcp_service}-db-pass")"
connection_name="$(gcloud sql instances describe "${gcp_sql_instance}" --format 'value(connectionName)')"
port="${IMPORT_WORLD_PORT:-54330}"
proxy_log="$(mktemp)"
cloud-sql-proxy --gcloud-auth --port "${port}" "${connection_name}" > "${proxy_log}" 2>&1 &
proxy_pid="${!}"
cleanup() {
	kill "${proxy_pid}" 2> /dev/null || true
	rm -f "${proxy_log}"
}
trap cleanup EXIT

for _ in $(seq 50)
do
	pg_isready -q -h 127.0.0.1 -p "${port}" && break
	sleep 0.2
done
if ! pg_isready -q -h 127.0.0.1 -p "${port}"
then
	echo "${0}: the Cloud SQL Auth Proxy did not come up:" >&2
	cat "${proxy_log}" >&2
	exit 1
fi

# the password is URL-quoted so any character in it survives
quoted="$(PASSWORD="${password}" python -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["PASSWORD"], safe=""))')"
DATABASE_URL="postgresql+pg8000://${gcp_db_user}:${quoted}@127.0.0.1:${port}/${gcp_db_name}" \
	PYTHONPATH=src python scripts/import_world.py "$@"
