"""
Checks of the certifications each account holds: who issued each, and what
kind it is.
"""


from typing import TYPE_CHECKING

from myworld.checks.core import (
    Result,
    check,
    problem,
    rows,
)
from myworld.models import CERTIFICATION_KINDS, Certification

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@check("certification-issuers", "Every certification has the organization that issued it", "certifications", "certifications")
def certification_issuers(session: Session) -> Result:
    """ Every certification, of every account, names the organization that issued it: its card shows that one's logo and links its website. """
    found = rows(session, Certification)
    return Result(checked=len(found), problems=[problem(c, "has no issuing organization") for c in found if c.organization_id is None])


@check("certification-kinds", "Every certification says what kind it is", "certifications", "certifications")
def certification_kinds(session: Session) -> Result:
    """ Every certification, of every account, says what kind it is: instructor (may teach the course) or professional (has the skill). """
    found = rows(session, Certification)
    kinds = " or ".join(CERTIFICATION_KINDS)
    return Result(checked=len(found), problems=[problem(c, f"has no kind ({kinds})") for c in found if c.kind not in CERTIFICATION_KINDS])
