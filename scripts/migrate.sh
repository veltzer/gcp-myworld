#!/bin/bash
# Schema migrations, kept by Alembic: every change to the tables is one
# numbered step in scripts/migrations/versions/, and the database remembers
# which it is at (its alembic_version table), so each step runs once. Safe
# and cheap to run any time: it ends with one line saying what was done.
#
#   scripts/migrate.sh          the Cloud SQL database from .gcp.conf
#   scripts/migrate.sh --local  the local sqlite file (db.gi/myworld.sqlite or DATABASE_URL)
#   scripts/migrate.sh [--local] --drift   only say how the database differs from the models
#   scripts/migrate.sh [--local] --to 0003 stop at that step: when a change adds
#                               before the deploy and drops after it, the steps
#                               that add are run first, and the rest after the deploy
#
# A new step: change the models, then
#   alembic -c scripts/migrations/alembic.ini revision --autogenerate -m "what changed"
# against a database that is at the head, read what it wrote, and put its
# number in SCHEMA_REVISION (src/myworld/models.py). tests/migrations_test.py
# fails while the models and the migrations disagree.
#
# A database from before Alembic (tables, but no alembic_version) is first
# brought up to the first migration by scripts/history/migrate_legacy.sh,
# the script this replaced, and then marked as being there.
set -euo pipefail

cd "$(dirname "${0}")/.."

run=(scripts/with_cloud_db.sh)
legacy=()
step="upgrade"
target=()
expect_target=""
for argument in "$@"
do
	if [[ -n "${expect_target}" ]]
	then
		target=("${argument}")
		expect_target=""
		continue
	fi
	case "${argument}" in
		--to)
			expect_target="yes"
			;;
		--local)
			run=()
			legacy=(--local)
			;;
		--drift)
			step="drift"
			;;
		*)
			echo "usage: ${0} [--local] [--drift] [--to REVISION]" >&2
			exit 2
			;;
	esac
done

state="$("${run[@]}" scripts/migrations/run.py state)"
if [[ "${step}" == "drift" ]]
then
	"${run[@]}" scripts/migrations/run.py drift
elif [[ "${state}" == "legacy" ]]
then
	scripts/history/migrate_legacy.sh "${legacy[@]}"
	"${run[@]}" scripts/migrations/run.py baseline
else
	"${run[@]}" scripts/migrations/run.py upgrade "${target[@]}"
fi
