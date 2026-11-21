"""
Checks of the shared lists of names: the kinds of place (Museum, Concert
venue, ...) and the types of visit (Museum visit, ...).
"""

from sqlalchemy.orm import Session

from myworld.checks.core import (
    Result,
    check,
    ids,
    problem,
    rows,
    twice,
)
from myworld.models import PlaceKind, Visit, VisitType, place_kind_links


@check("place-kind-used", "Every place kind has a place", "place kinds", "place-kinds")
def check_place_kind_used(session: Session) -> Result:
    """ Every kind of place is the kind of at least one place; one no place is of can go. """
    kinds, used = rows(session, PlaceKind), ids(session, place_kind_links.c.kind_id)
    return Result(checked=len(kinds), problems=[problem(kind, "no place is of it") for kind in kinds if kind.id not in used])


@check("place-kind-duplicates", "No place kind is listed twice", "place kinds", "place-kinds")
def check_place_kind_duplicates(session: Session) -> Result:
    """ No two kinds of place have the same name (ignoring case and spaces at the ends). """
    kinds = rows(session, PlaceKind)
    return Result(checked=len(kinds), problems=twice(kinds, lambda kind: kind.name.strip().lower(), "name", "place kind"))


@check("visit-type-used", "Every visit type has a visit", "visit types", "visit-types")
def check_visit_type_used(session: Session) -> Result:
    """ Every type of visit is the type of at least one visit, of any account; one no visit is of can go. """
    kinds, used = rows(session, VisitType), ids(session, Visit.type_id)
    return Result(checked=len(kinds), problems=[problem(kind, "no visit is of it") for kind in kinds if kind.id not in used])


@check("visit-type-duplicates", "No visit type is listed twice", "visit types", "visit-types")
def check_visit_type_duplicates(session: Session) -> Result:
    """ No two types of visit have the same name (ignoring case and spaces at the ends). """
    kinds = rows(session, VisitType)
    return Result(checked=len(kinds), problems=twice(kinds, lambda kind: kind.name.strip().lower(), "name", "visit type"))
