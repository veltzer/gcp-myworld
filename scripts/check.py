#!/usr/bin/env python

"""
Run the database checks (src/myworld/checks.py), the same ones an admin
runs from the Checks page, over every account.

  PYTHONPATH=src scripts/check.py             every check
  PYTHONPATH=src scripts/check.py logos ...   only these
  PYTHONPATH=src scripts/check.py --list      the checks there are

The database is DATABASE_URL (default: the local sqlite file); for Cloud SQL
run it through the proxy: scripts/with_cloud_db.sh scripts/check.py. Exits 1
when a check finds a problem, 2 when a name is not a check.
"""

import argparse
import sys

from sqlalchemy.orm import Session

from myworld.checks import CHECKS
from myworld.models import make_engine


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[1] if __doc__ else None,
        epilog="checks: " + ", ".join(CHECKS),
    )
    parser.add_argument("names", nargs="*", metavar="check", help="checks to run (default: all)")
    parser.add_argument("--list", action="store_true", help="list the checks and run none")
    args = parser.parse_args()
    if args.list:
        width = max(len(name) for name in CHECKS)
        for chosen in CHECKS.values():
            print(f"{chosen.name:<{width}}  {chosen.title}: {chosen.description}")
        return 0
    unknown = [name for name in args.names if name not in CHECKS]
    if unknown:
        print(f"check: no check called {', '.join(unknown)}; there are: {', '.join(CHECKS)}", file=sys.stderr)
        return 2
    engine = make_engine()
    print(engine.url.render_as_string(hide_password=True))
    failed = 0
    with Session(engine) as session:
        for name in args.names or CHECKS:
            chosen = CHECKS[name]
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
