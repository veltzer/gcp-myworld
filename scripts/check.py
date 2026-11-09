#!/usr/bin/env python

"""
Run the database checks (src/myworld/checks.py), the same ones an admin
runs from the Checks page, over every account.

  scripts/check.py                  every check
  scripts/check.py logos ...        only these
  scripts/check.py --dataset book   the checks of one dataset (as its page runs them)
  scripts/check.py --list           the checks there are, by dataset
  scripts/check.py --email me@x     skip the checks that account turned off

The database is DATABASE_URL (default: the local sqlite file); for Cloud SQL
run it through the proxy: scripts/with_cloud_db.sh scripts/check.py. Exits 1
when a check finds a problem, 2 when a name is not a check.
"""

import argparse
import os
import sys
from pathlib import Path

# the myworld package is in src/, not installed: find it from any directory, no
# PYTHONPATH needed; and work from the repository root, where the default
# DATABASE_URL (db.gi/myworld.sqlite) is, rather than make an empty one elsewhere
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld.checks import CHECKS, DATASETS
from myworld.models import DisabledCheck, User, make_engine


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[1] if __doc__ else None,
        epilog="checks: " + ", ".join(CHECKS),
    )
    parser.add_argument("names", nargs="*", metavar="check", help="checks to run (default: all)")
    parser.add_argument("--dataset", choices=list(DATASETS), help="run the checks of this dataset")
    parser.add_argument("--list", action="store_true", help="list the checks, by dataset, and run none")
    parser.add_argument("--email", help="skip the checks this account turned off (on the Checks page)")
    args = parser.parse_args()
    if args.list:
        width = max(len(name) for name in CHECKS)
        for dataset, dataset_name in DATASETS.items():
            print(f"{dataset_name} (--dataset {dataset}):")
            for chosen in CHECKS.values():
                if chosen.dataset == dataset:
                    print(f"  {chosen.name:<{width}}  {chosen.title}: {chosen.description}")
        return 0
    unknown = [name for name in args.names if name not in CHECKS]
    if unknown:
        print(f"check: no check called {', '.join(unknown)}; there are: {', '.join(CHECKS)}", file=sys.stderr)
        return 2
    if args.names and args.dataset:
        print("check: name checks or a dataset, not both", file=sys.stderr)
        return 2
    if args.dataset:
        args.names = [name for name, chosen in CHECKS.items() if chosen.dataset == args.dataset]
    engine = make_engine()
    print(engine.url.render_as_string(hide_password=True))
    failed = 0
    with Session(engine) as session:
        disabled: set[str] = set()
        if args.email:
            users = session.scalars(select(User).where(User.email == args.email)).all()
            if not users:
                print(f"check: no account for {args.email}", file=sys.stderr)
                return 2
            disabled = set(session.scalars(select(DisabledCheck.check_name).where(DisabledCheck.user_id.in_([u.id for u in users]))))
        for name in args.names or CHECKS:
            chosen = CHECKS[name]
            if name in disabled:
                print(f"off   {name}: turned off by {args.email}")
                continue
            result = chosen.run(session)
            if result.ok:
                print(f"ok    {name}: all {result.checked} {chosen.noun} pass")
                continue
            failed += 1
            print(f"FAIL  {name}: {len(result.problems)} problems in {result.checked} {chosen.noun}")
            for problem in result.problems:
                print(f"      {problem.subject}: {problem.message}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
