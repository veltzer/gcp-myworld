"""
Checks of the groups.
"""


from typing import TYPE_CHECKING

from myworld.checks.core import (
    Result,
    check,
    ids,
    problem,
    rows,
    squashed,
    twice,
)
from myworld.models import (
    Group,
    concert_groups,
    group_members,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@check("group-members", "Every group has its members", "groups", "groups")
def check_group_members(session: Session) -> Result:
    """ Every group, of every account, has at least one member (a person). """
    groups, with_members = rows(session, Group), ids(session, group_members.c.group_id)
    return Result(checked=len(groups), problems=[problem(group, "has no members") for group in groups if group.id not in with_members])


@check("group-used", "Every group performed somewhere", "groups", "groups")
def check_group_used(session: Session) -> Result:
    """ Every group, of every account, performed at at least one concert. """
    groups, used = rows(session, Group), ids(session, concert_groups.c.group_id)
    return Result(checked=len(groups), problems=[problem(group, "performed at no concert") for group in groups if group.id not in used])


@check("group-photos", "Every group has a photo", "groups", "groups")
def check_group_photos(session: Session) -> Result:
    """ Every group, of every account, has a photo (scripts/fetch_pictures.py takes Wikipedia's, or one of a member). """
    groups = rows(session, Group)
    return Result(checked=len(groups), problems=[problem(group, "has no photo") for group in groups if group.image_id is None])


@check("group-duplicates", "No group is listed twice", "groups", "groups")
def check_group_duplicates(session: Session) -> Result:
    """ No account has two groups of the same name (ignoring case and spaces). """
    groups = rows(session, Group)
    return Result(checked=len(groups), problems=twice(groups, lambda g: (g.owner_id, squashed(g.name)), "name", "group"))
