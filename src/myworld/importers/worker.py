"""
What a Cloud Run Jobs execution of the import job runs (myworld.importers.jobs):

    python -m myworld.importers.worker <run id>

It does that queued run (core.execute) against the database the service
uses, and ends. It exits 0 once the run is kept, whether it was done or
failed: the run says how it went, and the job is not retried.
"""

import argparse
import logging

from myworld import importers
from myworld.models import make_engine


def main() -> None:
    parser = argparse.ArgumentParser(description="Do one queued import run.")
    parser.add_argument("run_id", type=int, help="the import_runs row to do")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    engine = make_engine()
    try:
        importers.execute(engine, args.run_id)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
