"""
A test importer, seen and run by admins only: it imports nothing, and
takes SECONDS (five minutes) doing it, saying so every SAY_EVERY seconds.
It is there to see what long runs look like on the Imports page, several
at a time if wanted, and that their jobs keep going without the page.
"""

import time
from typing import TYPE_CHECKING, Any

from myworld.importers.core import Importer, Report, register

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from myworld.models import User

SECONDS = 300
SAY_EVERY = 30
SLEPT = "seconds slept"


def run(_session: Session, _owner: User, _params: dict[str, Any], report: Report) -> None:
    report.say(f"Sleeping for {SECONDS} seconds")
    slept = 0
    while slept < SECONDS:
        step = min(SAY_EVERY, SECONDS - slept)
        time.sleep(step)
        slept += step
        report.count(SLEPT, step)
        report.say(f"{slept} of {SECONDS} seconds")
    report.say("Woke up")


IMPORTER = register(Importer(
    name="sleep",
    title="Sleep (a test, for admins)",
    description=(
        f"Imports nothing and takes {SECONDS // 60} minutes doing it, saying so every {SAY_EVERY} seconds: for seeing "
        "how long runs go. Run it as many times as you like, at once too."
    ),
    dataset=None,
    params=(),
    run=run,
    admin_only=True,
))
