"""
Checks of the small lists a user keeps: the types, the relations and the devices.
"""

from collections.abc import Callable

from sqlalchemy.orm import Session

from myworld.checks.core import (
    Result,
    check,
    ids,
    one_of,
    problem,
    rows,
    twice,
)
from myworld.models import (
    AudioBook,
    AudioCourse,
    Device,
    Organization,
    OrganizationType,
    PersonOrganization,
    PersonOrganizationType,
    PersonRelation,
    PersonRelationType,
    PersonType,
    PodcastEpisode,
    RelationType,
    YouTubeVideo,
    organization_relation_types,
    person_type_links,
)

type _Enumeration = type[OrganizationType | PersonType | RelationType | PersonRelationType | PersonOrganizationType | Device]


def _enumeration_checks(dataset: str, model: _Enumeration, used: Callable[[Session], set[int]]) -> None:
    """ The checks every enumeration has: each value used, described, and not there twice. """
    one = one_of(dataset)
    noun = f"{one}s"

    def check_used(session: Session) -> Result:
        all_rows, in_use = rows(session, model), used(session)
        return Result(checked=len(all_rows), problems=[problem(r, "is used by nothing") for r in all_rows if r.id not in in_use])

    def check_described(session: Session) -> Result:
        all_rows = rows(session, model)
        return Result(checked=len(all_rows), problems=[problem(r, "has no description") for r in all_rows if not r.description.strip()])

    def check_twice(session: Session) -> Result:
        all_rows = rows(session, model)
        return Result(checked=len(all_rows), problems=twice(all_rows, lambda row: (row.owner_id, row.name.strip().lower()), "name", one))

    check_used.__doc__ = f"Every {one}, of every account, is used by at least one row; one used by nothing can go."
    check_described.__doc__ = f"Every {one}, of every account, has a description, so its tooltip and page say what it means."
    check_twice.__doc__ = f"No account has two {noun} of the same name (ignoring case and spaces at the ends)."
    prefix = dataset.removesuffix("s")
    check(f"{prefix}-used", f"Every {one} is used", noun, dataset)(check_used)
    check(f"{prefix}-descriptions", f"Every {one} has a description", noun, dataset)(check_described)
    check(f"{prefix}-duplicates", f"No {one} is listed twice", noun, dataset)(check_twice)


@check("device-photos", "Every device has a photo", "devices", "devices")
def check_device_photos(session: Session) -> Result:
    """ Every device, of every account, has a photo (scripts/fetch_pictures.py --only devices takes Wikipedia's). """
    devices = rows(session, Device)
    return Result(checked=len(devices), problems=[
        problem(d, "has no photo") for d in devices if d.image_id is None
    ])


@check("person-type-photos", "Every profession has a photo", "professions", "person-types")
def check_profession_photos(session: Session) -> Result:
    """ Every profession, of every account, has a photo (scripts/fetch_pictures.py --only professions takes Wikipedia's). """
    kinds = rows(session, PersonType)
    return Result(checked=len(kinds), problems=[
        problem(k, "has no photo") for k in kinds if k.image_id is None
    ])


_enumeration_checks("organization-types", OrganizationType, lambda session: ids(session, Organization.type_id))


_enumeration_checks("person-types", PersonType, lambda session: ids(session, person_type_links.c.person_type_id))


_enumeration_checks("relation-types", RelationType, lambda session: ids(session, organization_relation_types.c.relation_type_id))


_enumeration_checks("person-relation-types", PersonRelationType, lambda session: ids(session, PersonRelation.relation_type_id))


_enumeration_checks("person-organization-types", PersonOrganizationType, lambda session: ids(session, PersonOrganization.relation_type_id))


_enumeration_checks("devices", Device, lambda session: ids(session, AudioCourse.device_id, AudioBook.device_id, PodcastEpisode.device_id, YouTubeVideo.device_id))
