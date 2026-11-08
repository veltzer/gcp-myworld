#!/usr/bin/env python

"""
Load concerts, museum visits, people and companies, with their images, into
the database for one user.

The source is a directory laid out the way veltzer.github.io keeps them:
data/yaml/{concerts,museums,people,organizations}.yaml, the photos in
static/images/ (concert-*.jpg named by each concert's image field,
museum-<internal_id>.jpg for the first visit of each museum, which every
later visit of the same museum shares) and the organization logos in
data/logos/.

Companies are every organization plus every company a person names that is
not one of them; each person is linked to the companies they name.

Everything the user had in these tables is replaced, in one transaction, so
the script is safe to run again. Unknown fields in the YAML stop the import
rather than being dropped, so nothing is lost on the way in.

The user must have signed in at least once; pass the email they signed in
with (and --subject when that email has several accounts, e.g. Google and
GitHub).

  PYTHONPATH=src scripts/import_world.py --email me@example.com [--source ../veltzer.github.io]

The database is DATABASE_URL (default: the local sqlite file); for Cloud SQL
see doc/deploy.md.
"""

import argparse
import datetime
import hashlib
import mimetypes
import sys
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from myworld.models import (
    Company,
    Concert,
    Image,
    Museum,
    Person,
    User,
    concert_people,
    make_engine,
    museum_people,
    person_companies,
)

DATE_FIELDS = {"date_utcz", "date_ymd", "date_my", "date_y", "date_timezone"}
PERSON_FIELDS = {"name", "company", "description"}
CONCERT_FIELDS = DATE_FIELDS | {
    "name", "performers", "event", "genre", "venue", "city", "country", "with", "tickets",
    "broadcast", "review", "remark", "image", "image_source", "image_license", "image_author",
}
# organization fields that have a column of their own; logo names the logo file
ORGANIZATION_COLUMNS = {"name", "functions", "status", "website", "location", "address", "what_happened", "remark"}
# kept as they are in companies.details
ORGANIZATION_DETAILS = {
    "id", "slug", "logo_kind", "logo_source", "logo_license", "logo_note", "old_url", "location_geo",
    "israel_office", "israel_office_geo", "former_website", "former_location", "former_location_geo",
    "address_source", "geo", "sources", "from_date",
}
ORGANIZATION_FIELDS = ORGANIZATION_COLUMNS | ORGANIZATION_DETAILS | {"logo"}
# internal_id only names the image file; it is not stored
MUSEUM_FIELDS = DATE_FIELDS | {
    "name", "city", "rating", "review", "remark", "url", "tickets", "with", "internal_id",
}


class WorldImportError(Exception):
    pass


def _items(source: Path, name: str, fields: set[str]) -> list[dict[str, Any]]:
    path = source / "data" / "yaml" / f"{name}.yaml"
    with path.open(encoding="UTF8") as fp:
        items = yaml.safe_load(fp)["items"]
    for item in items:
        unknown = set(item) - fields
        if unknown:
            raise WorldImportError(f"{path}: {item.get('name')!r} has fields this import does not know: {sorted(unknown)}")
    return items


def _dates(item: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"date_timezone": item.get("date_timezone", "")}
    if "date_utcz" in item:
        stamp = datetime.datetime.fromisoformat(str(item["date_utcz"]))
        out["date_utcz"] = stamp.astimezone(datetime.UTC).replace(tzinfo=None)
    if "date_ymd" in item:
        out["date_ymd"] = datetime.date.fromisoformat(str(item["date_ymd"]))
    if "date_my" in item:
        value = str(item["date_my"])
        month, year = value.split("-")
        if len(month) != 2 or len(year) != 4:
            raise WorldImportError(f"{item['name']!r}: date_my {value!r} is not MM-YYYY")
        out["date_my"] = value
    if "date_y" in item:
        out["date_y"] = int(item["date_y"])
    return out


def _person_companies(item: dict[str, Any]) -> list[str]:
    """ company in people.yaml: one name, or a list of names. """
    value = item.get("company", [])
    names = [value] if isinstance(value, str) else list(value)
    if len(set(names)) != len(names):
        raise WorldImportError(f"people.yaml: {item['name']!r} names a company twice")
    return names


def _json_safe(value: Any) -> Any:
    """ YAML may hand over dates; JSON columns want strings. """
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def find_owner(session: Session, email: str, subject: str | None) -> User:
    users = session.execute(select(User).where(User.email == email)).scalars().all()
    if subject is not None:
        users = [u for u in users if u.google_sub == subject]
    if not users:
        raise WorldImportError(f"no account for {email}{f' with subject {subject}' if subject else ''}: sign in once first")
    if len(users) > 1:
        subjects = ", ".join(u.google_sub for u in users)
        raise WorldImportError(f"{email} has several accounts, pick one with --subject: {subjects}")
    return users[0]


def import_world(session: Session, owner: User, source: Path) -> dict[str, int]:
    """ Replace owner's concerts, museums, people, companies and images with those under source. Does not commit. """
    people_items = _items(source, "people", PERSON_FIELDS)
    organization_items = _items(source, "organizations", ORGANIZATION_FIELDS)
    concert_items = _items(source, "concerts", CONCERT_FIELDS)
    museum_items = _items(source, "museums", MUSEUM_FIELDS)
    image_dir = source / "static" / "images"

    # the link rows explicitly: sqlite does not enforce ON DELETE CASCADE unless asked to
    session.execute(delete(concert_people).where(concert_people.c.concert_id.in_(select(Concert.id).where(Concert.owner_id == owner.id))))
    session.execute(delete(museum_people).where(museum_people.c.museum_id.in_(select(Museum.id).where(Museum.owner_id == owner.id))))
    session.execute(delete(person_companies).where(person_companies.c.person_id.in_(select(Person.id).where(Person.owner_id == owner.id))))
    for model in (Concert, Museum, Person, Company, Image):
        session.execute(delete(model).where(model.owner_id == owner.id))
    session.flush()

    images: dict[str, Image] = {}

    def image(path: Path, required: bool) -> Image | None:
        filename = path.name
        if filename in images:
            return images[filename]
        if not path.exists():
            if required:
                raise WorldImportError(f"missing image {path}")
            return None
        data = path.read_bytes()
        content_type = mimetypes.guess_type(filename)[0]
        if content_type is None or not content_type.startswith("image/"):
            raise WorldImportError(f"{path}: not an image type")
        images[filename] = Image(
            owner_id=owner.id, filename=filename, content_type=content_type,
            sha256=hashlib.sha256(data).hexdigest(), data=data,
        )
        session.add(images[filename])
        return images[filename]

    companies: dict[str, Company] = {}
    for item in organization_items:
        if item["name"] in companies:
            raise WorldImportError(f"organizations.yaml: {item['name']!r} appears twice")
        company = Company(
            owner_id=owner.id,
            name=item["name"],
            functions=list(item.get("functions", [])),
            **{key: item.get(key, "") for key in sorted(ORGANIZATION_COLUMNS - {"name", "functions"})},
            details={key: _json_safe(item[key]) for key in sorted(ORGANIZATION_DETAILS) if key in item},
            # logos live in data/, as logos/<slug>.svg
            image=image(source / "data" / item["logo"], required=True) if "logo" in item else None,
        )
        companies[company.name] = company
        session.add(company)
    organizations = len(companies)

    people: dict[str, Person] = {}
    for item in people_items:
        if item["name"] in people:
            raise WorldImportError(f"people.yaml: {item['name']!r} appears twice")
        names = _person_companies(item)
        for name in names:
            if name not in companies:
                companies[name] = Company(owner_id=owner.id, name=name)
                session.add(companies[name])
        person = Person(
            owner_id=owner.id, name=item["name"], description=item.get("description", ""),
            companies=[companies[name] for name in names],
        )
        people[person.name] = person
        session.add(person)

    def with_people(item: dict[str, Any]) -> list[Person]:
        if len(set(item["with"])) != len(item["with"]):
            raise WorldImportError(f"{item['name']!r}: a name appears twice in with")
        missing = [name for name in item["with"] if name not in people]
        if missing:
            raise WorldImportError(f"{item['name']!r}: with names not in people.yaml: {missing}")
        return [people[name] for name in item["with"]]

    for item in concert_items:
        session.add(Concert(
            owner_id=owner.id,
            name=item["name"],
            performers=list(item.get("performers", [])),
            event=item.get("event", ""),
            genre=item.get("genre", ""),
            venue=item.get("venue", ""),
            city=item.get("city", ""),
            country=item.get("country", ""),
            tickets=item.get("tickets"),
            broadcast=bool(item.get("broadcast", False)),
            review=item.get("review", ""),
            remark=item.get("remark", ""),
            image=image(image_dir / item["image"], required=True) if "image" in item else None,
            image_source=item.get("image_source", ""),
            image_license=item.get("image_license", ""),
            image_author=item.get("image_author", ""),
            people=with_people(item),
            **_dates(item),
        ))

    # every visit of a museum shows the photo of its first (lowest internal_id) visit
    first_visit: dict[str, int] = {}
    for item in museum_items:
        first_visit[item["name"]] = min(first_visit.get(item["name"], item["internal_id"]), item["internal_id"])
    for item in museum_items:
        session.add(Museum(
            owner_id=owner.id,
            name=item["name"],
            city=item.get("city", ""),
            rating=item.get("rating"),
            review=item.get("review", ""),
            remark=item.get("remark", ""),
            url=item.get("url", ""),
            tickets=item.get("tickets"),
            image=image(image_dir / f"museum-{first_visit[item['name']]}.jpg", required=False),
            people=with_people(item),
            **_dates(item),
        ))
    session.flush()
    return {
        "people": len(people), "companies": len(companies), "organizations": organizations,
        "concerts": len(concert_items), "museums": len(museum_items), "images": len(images),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1] if __doc__ else None)
    parser.add_argument("--email", required=True, help="email of the account that will own the data")
    parser.add_argument("--subject", help="the account's subject (users.google_sub) when the email has several")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent.parent.parent / "veltzer.github.io")
    args = parser.parse_args()
    engine = make_engine()
    with Session(engine) as session:
        try:
            owner = find_owner(session, args.email, args.subject)
            counts = import_world(session, owner, args.source)
        except WorldImportError as e:
            print(f"import_world: {e}", file=sys.stderr)
            return 1
        who = f"{owner.email} ({owner.google_sub})"
        session.commit()
    summary = ", ".join(f"{count} {what}" for what, count in counts.items())
    print(f"{engine.url.render_as_string(hide_password=True)}: imported for {who}: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
