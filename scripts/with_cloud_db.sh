#!/bin/bash
# Run a command against the Cloud SQL database from .gcp.conf: starts the
# Cloud SQL Auth Proxy with your gcloud credentials, takes the app's
# database password from Secret Manager (it never touches disk) and runs the
# command with DATABASE_URL pointing at the proxy, which stops when the
# command ends. The port is CLOUD_DB_PORT (default 54330).
#
#   PYTHONPATH=src scripts/with_cloud_db.sh scripts/check.py
#   PYTHONPATH=src scripts/with_cloud_db.sh python scripts/import_world.py --email me@example.com

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
port="${CLOUD_DB_PORT:-54330}"
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
DATABASE_URL="postgresql+pg8000://${gcp_db_user}:${quoted}@127.0.0.1:${port}/${gcp_db_name}" "$@"
