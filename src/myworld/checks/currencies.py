"""
Checks of the currencies.
"""

from typing import TYPE_CHECKING

from sqlalchemy import select

from myworld.checks.core import Result, check, problem, rows
from myworld.models import Currency, country_currencies

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@check("currency-names", "Every currency has a name", "currencies", "currencies")
def check_currency_names(session: Session) -> Result:
    """ Every currency has a name, not only its code. """
    currencies = rows(session, Currency)
    return Result(checked=len(currencies), problems=[problem(c, "has no name") for c in currencies if not c.name.strip()])


@check("currency-used", "Every currency is some country's", "currencies", "currencies")
def check_currency_used(session: Session) -> Result:
    """ Every currency is paid in by at least one country (the Countries page says which). """
    currencies, used = rows(session, Currency), set(session.scalars(select(country_currencies.c.currency_id)))
    return Result(checked=len(currencies), problems=[problem(c, "is no country's") for c in currencies if c.id not in used])
