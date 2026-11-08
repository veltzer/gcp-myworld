#!/bin/bash
# Run scripts/import_world.py against the Cloud SQL database from .gcp.conf,
# through scripts/with_cloud_db.sh. Arguments go to import_world.py.
#
#   scripts/import_world_cloud.sh --email me@example.com [--source ../veltzer.github.io]
#
# The import creates its tables if they are missing (create_all), so it can
# run before or after deploying the version that shows them.

set -euo pipefail

cd "$(dirname "${0}")/.."

PYTHONPATH=src exec scripts/with_cloud_db.sh python scripts/import_world.py "$@"
