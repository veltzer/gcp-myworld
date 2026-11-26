"""
Checks of what each account lent, and of the websites it keeps.
"""


from typing import TYPE_CHECKING

from myworld.checks.core import (
    Result,
    check,
    problem,
    rows,
)
from myworld.models import Loan, Website

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@check("loan-borrowers", "Every loan says who has it", "loans", "loans")
def check_loan_borrowers(session: Session) -> Result:
    """ Every loan, of every account, names the person it was lent to (one of the account's people). """
    found = rows(session, Loan)
    return Result(checked=len(found), problems=[problem(loan, "is lent to no one known") for loan in found if loan.person_id is None])


@check("website-topics", "Every website says what it is about", "websites", "websites")
def check_website_topics(session: Session) -> Result:
    """ Every website, of every account, has a topic ("Free study", ...), which its page filters by. """
    found = rows(session, Website)
    return Result(checked=len(found), problems=[problem(w, "has no topic") for w in found if not w.topic])
