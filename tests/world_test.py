"""
The concerts, museums, people and organizations: the import script and the API.
"""

from pathlib import Path

import import_world
import pytest
import webtest
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from myworld.models import (
    Concert,
    Image,
    Museum,
    Organization,
    OrganizationType,
    Person,
    User,
    concert_people,
    person_organizations,
)
from tests.conftest import sign_in

PEOPLE = """
items:
  - name: "Alice Friend"
    company: "Startup"
    description: "Old friend"
  - name: "Bob Buddy"
    company: ["Acme", "Startup"]
"""

ORGANIZATIONS = """
items:
  - id: 1
    name: "Acme"
    slug: "acme"
    functions: ["teaching", "consulting"]
    status: "acquired"
    what_happened: "Bought by Bigco"
    website: "https://acme.example"
    location: "Tel Aviv, Israel"
    address: "1 Main St"
    logo: "logos/acme.svg"
    geo: {"from": "location", "place": "Tel Aviv, Israel", "lat": 32.08, "lon": 34.78}
    sources: ["https://en.wikipedia.org/wiki/Acme"]
  - id: 2
    name: "Old School"
    type: "University"
    slug: "old-school"
    functions: ["education"]
    status: "active"
    from_date: 2008-03-21
"""

CONCERTS = """
items:
  - name: "The Band"
    performers: ["The Band"]
    genre: "rock"
    date_y: "1989"
    date_timezone: "Asia/Jerusalem"
    venue: "The Hall"
    country: "Israel"
    with: ["Alice Friend"]
    image: "concert-the-band.jpg"
    image_source: "https://commons.wikimedia.org/wiki/File:Band.jpg"
    image_license: "CC BY-SA 3.0"
    image_author: "Someone"
  - name: "Late Show"
    performers: ["Singer", "Bob Buddy", " Singer "]
    date_utcz: "2020-01-01T22:30:00Z"
    date_timezone: "Asia/Jerusalem"
    with: ["Alice Friend", "Bob Buddy"]
    tickets: 2
    broadcast: true
    image: "concert-the-band.jpg"
  - name: "Some Month"
    date_my: "03-2001"
    with: []
"""

MUSEUMS = """
items:
  - name: "The Louvre"
    date_ymd: "2010-03-01"
    date_timezone: "Europe/Paris"
    city: "Paris"
    rating: 9
    review: "Huge"
    with: ["Bob Buddy"]
    url: "https://www.louvre.fr/"
    internal_id: 15
  - name: "The Louvre"
    date_ymd: "2010-03-03"
    date_timezone: "Europe/Paris"
    city: "Paris"
    rating: 8
    review: "Again"
    with: []
    url: "https://www.louvre.fr/"
    internal_id: 17
  - name: "No Photo Museum"
    date_ymd: "2011-01-01"
    city: "London"
    rating: 5
    review: "ok"
    with: []
    url: ""
    internal_id: 20
"""


LOGO = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'


def write_source(root: Path, concerts: str = CONCERTS) -> Path:
    (root / "data" / "yaml").mkdir(parents=True)
    (root / "static" / "images").mkdir(parents=True)
    (root / "data" / "logos").mkdir(parents=True)
    for name, text in (("people", PEOPLE), ("concerts", concerts), ("museums", MUSEUMS), ("organizations", ORGANIZATIONS)):
        (root / "data" / "yaml" / f"{name}.yaml").write_text(text, encoding="UTF8")
    (root / "data" / "logos" / "acme.svg").write_bytes(LOGO)
    (root / "static" / "images" / "concert-the-band.jpg").write_bytes(b"\xff\xd8band")
    (root / "static" / "images" / "museum-15.jpg").write_bytes(b"\xff\xd8louvre")
    return root


def owner(session: Session, email: str = "alice@example.com") -> User:
    return import_world.find_owner(session, email, None)


@pytest.fixture(name="imported")
def fixture_imported(app: webtest.TestApp, engine: Engine, tmp_path: Path) -> webtest.TestApp:
    sign_in(app)
    with Session(engine) as session:
        counts = import_world.import_world(session, owner(session), write_source(tmp_path))
        session.commit()
    assert counts == {"people": 4, "organizations": 3, "organization types": 7, "concerts": 3, "museums": 3, "images": 3}
    return app


def test_requires_login(app: webtest.TestApp) -> None:
    for path in ("/api/concerts", "/api/museums", "/api/people", "/api/organizations", "/api/organization-types", "/api/images/1"):
        app.get(path, status=401)


def test_concerts(imported: webtest.TestApp) -> None:
    concerts = imported.get("/api/concerts").json
    # newest first, whatever the precision of the date
    assert [c["name"] for c in concerts] == ["Late Show", "Some Month", "The Band"]
    late, month, band = concerts
    assert late["date"] == "2020-01-01T22:30:00Z"
    assert late["date_precision"] == "time"
    assert late["with"] == ["Alice Friend", "Bob Buddy"]
    assert [p["name"] for p in late["people"]] == ["Alice Friend", "Bob Buddy"]
    assert late["tickets"] == 2
    assert late["broadcast"] is True
    assert month["date"] == "2001-03"
    assert month["date_precision"] == "month"
    assert month["image"] is None
    assert band["date"] == "1989"
    assert band["image_license"] == "CC BY-SA 3.0"
    # the two shows share one photo
    assert band["image"] == late["image"]


def test_performers_are_people(imported: webtest.TestApp) -> None:
    concerts = {c["name"]: c for c in imported.get("/api/concerts").json}
    people = {p["name"]: p["id"] for p in imported.get("/api/people").json}
    # a performer people.yaml does not have becomes a person; one it has is that person
    assert "The Band" in people
    assert "Singer" in people
    assert concerts["Late Show"]["performers"] == [
        {"id": people["Bob Buddy"], "name": "Bob Buddy"}, {"id": people["Singer"], "name": "Singer"},
    ]
    # performers and the people the user went with are separate lists
    assert concerts["Late Show"]["with"] == ["Alice Friend", "Bob Buddy"]
    assert concerts["Some Month"]["performers"] == []
    imported.post_json("/api/concerts", {"name": "x", "performers": [999]}, status=400)
    imported.post_json("/api/concerts", {"name": "x", "performers": ["Singer"]}, status=400)


def test_museums_share_the_first_visit_photo(imported: webtest.TestApp) -> None:
    museums = imported.get("/api/museums").json
    assert [m["name"] for m in museums] == ["No Photo Museum", "The Louvre", "The Louvre"]
    assert museums[0]["image"] is None
    assert museums[1]["image"] is not None
    assert museums[1]["image"] == museums[2]["image"]
    assert museums[2]["rating"] == 9
    assert museums[2]["with"] == ["Bob Buddy"]


def test_people_links_point_at_people(imported: webtest.TestApp) -> None:
    ids = {p["name"]: p["id"] for p in imported.get("/api/people").json}
    for path in ("/api/concerts", "/api/museums"):
        for item in imported.get(path).json:
            assert [ids[p["name"]] for p in item["people"]] == [p["id"] for p in item["people"]]


def test_people(imported: webtest.TestApp) -> None:
    people = imported.get("/api/people").json
    assert [p["name"] for p in people] == ["Alice Friend", "Bob Buddy", "Singer", "The Band"]
    alice, bob, _, _ = people
    assert alice["description"] == "Old friend"
    assert [c["name"] for c in alice["organizations"]] == ["Startup"]
    assert [c["name"] for c in bob["organizations"]] == ["Acme", "Startup"]
    # only the person and their organizations: their concerts and museums are not listed next to them
    assert set(alice) == {"id", "name", "organizations", "description"}


def test_organizations(imported: webtest.TestApp) -> None:
    organizations = imported.get("/api/organizations").json
    assert [c["name"] for c in organizations] == ["Acme", "Old School", "Startup"]
    acme, school, startup = organizations
    assert acme["functions"] == ["teaching", "consulting"]
    assert acme["status"] == "acquired"
    assert acme["what_happened"] == "Bought by Bigco"
    assert acme["website"] == "https://acme.example"
    assert [p["name"] for p in acme["people"]] == ["Bob Buddy"]
    assert [p["name"] for p in startup["people"]] == ["Alice Friend", "Bob Buddy"]
    # an organization only a person names has nothing but its name
    assert startup["functions"] == []
    assert startup["image"] is None
    assert school["image"] is None
    # the links point at the same rows both ways
    ids = {c["name"]: c["id"] for c in organizations}
    for person in imported.get("/api/people").json:
        assert all(ids[c["name"]] == c["id"] for c in person["organizations"])


def test_organization_types(imported: webtest.TestApp) -> None:
    types = {t["name"]: t for t in imported.get("/api/organization-types").json}
    assert list(types) == sorted(import_world.ORGANIZATION_TYPES)
    # Acme and Startup default to Company; the YAML names Old School's type
    assert types["Company"]["organizations"] == 2
    assert types["University"]["organizations"] == 1
    assert types["Military"]["organizations"] == 0
    by_name = {o["name"]: o for o in imported.get("/api/organizations").json}
    assert by_name["Old School"]["type"] == {"id": types["University"]["id"], "name": "University"}
    assert by_name["Acme"]["type"]["name"] == "Company"


def test_give_types_fills_only_what_is_missing(imported: webtest.TestApp, engine: Engine) -> None:
    with Session(engine) as session:
        session.execute(update(Organization).values(type_id=None))
        session.execute(delete(OrganizationType).where(OrganizationType.name == "Military"))
        session.commit()
        counts = import_world.give_types(session, owner(session))
        session.commit()
    assert counts == {"organization types added": 1, "organizations given a type": 3}
    by_name = {o["name"]: o["type"]["name"] for o in imported.get("/api/organizations").json}
    # Old School's type came from the YAML, which this does not read: it gets the default
    assert by_name == {"Acme": "Company", "Old School": "Company", "Startup": "Company"}
    with Session(engine) as session:
        assert import_world.give_types(session, owner(session)) == {"organization types added": 0, "organizations given a type": 0}


def test_edit_organization_types(imported: webtest.TestApp) -> None:
    imported.post_json("/api/organization-types", {"name": ""}, status=400)
    imported.post_json("/api/organization-types", {"name": "Company"}, status=409)
    lab = imported.post_json("/api/organization-types", {"name": "Lab", "description": "Research"}, status=201).json
    assert lab["organizations"] == 0
    acme = next(o for o in imported.get("/api/organizations").json if o["name"] == "Acme")
    edited = imported.put_json(f"/api/organizations/{acme['id']}", dict(acme, type_id=lab["id"])).json
    assert edited["type"]["name"] == "Lab"
    imported.put_json(f"/api/organizations/{acme['id']}", dict(acme, type_id=999), status=400)
    renamed = imported.put_json(f"/api/organization-types/{lab['id']}", {"name": "Laboratory"}).json
    assert renamed["organizations"] == 1
    assert next(o for o in imported.get("/api/organizations").json if o["name"] == "Acme")["type"]["name"] == "Laboratory"
    # a type in use cannot go; once nothing is of it, it can
    imported.delete(f"/api/organization-types/{lab['id']}", status=409)
    imported.put_json(f"/api/organizations/{acme['id']}", dict(acme, type_id=None))
    imported.delete(f"/api/organization-types/{lab['id']}", status=204)
    assert "Laboratory" not in [t["name"] for t in imported.get("/api/organization-types").json]


def test_organization_details_are_kept(imported: webtest.TestApp, engine: Engine) -> None:
    with Session(engine) as session:
        acme = session.scalars(select(Organization).where(Organization.name == "Acme")).one()
        assert acme.details["geo"]["lat"] == 32.08
        assert acme.details["sources"] == ["https://en.wikipedia.org/wiki/Acme"]
        assert acme.details["slug"] == "acme"
        school = session.scalars(select(Organization).where(Organization.name == "Old School")).one()
        assert school.details["from_date"] == "2008-03-21"


def test_logo(imported: webtest.TestApp) -> None:
    acme = imported.get("/api/organizations").json[0]
    response = imported.get(acme["image"])
    assert response.content_type == "image/svg+xml"
    assert response.body == LOGO
    # an SVG opened on its own cannot run scripts on this origin
    assert "sandbox" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_image(imported: webtest.TestApp) -> None:
    url = imported.get("/api/concerts").json[0]["image"]
    response = imported.get(url)
    assert response.content_type == "image/jpeg"
    assert response.body == b"\xff\xd8band"
    assert response.etag is not None
    assert "private" in response.headers["Cache-Control"]
    imported.get(url, headers={"If-None-Match": f'"{response.etag}"'}, status=304)


def test_other_users_see_nothing(imported: webtest.TestApp, engine: Engine) -> None:
    url = imported.get("/api/concerts").json[0]["image"]
    imported.post("/auth/logout")
    sign_in(imported, sub="someone-else")
    assert imported.get("/api/concerts").json == []
    assert imported.get("/api/museums").json == []
    assert imported.get("/api/people").json == []
    assert imported.get("/api/organizations").json == []
    assert imported.get("/api/organization-types").json == []
    imported.get(url, status=404)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Concert)) == 3


def test_reimport_replaces(imported: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        import_world.import_world(session, owner(session), tmp_path)
        session.commit()
        for model, count in ((Concert, 3), (Museum, 3), (Person, 4), (Organization, 3), (Image, 3)):
            assert session.scalar(select(func.count()).select_from(model)) == count
        assert session.scalar(select(func.count()).select_from(concert_people)) == 3
        assert session.scalar(select(func.count()).select_from(person_organizations)) == 3
    assert len(imported.get("/api/concerts").json) == 3


def test_unknown_field_stops_the_import(app: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    sign_in(app)
    source = write_source(tmp_path, CONCERTS + '    mood: "great"\n')
    with Session(engine) as session, pytest.raises(import_world.WorldImportError, match="mood"):
        import_world.import_world(session, owner(session), source)


def test_unknown_person_stops_the_import(app: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    sign_in(app)
    source = write_source(tmp_path, CONCERTS.replace('with: []', 'with: ["Stranger"]'))
    with Session(engine) as session, pytest.raises(import_world.WorldImportError, match="Stranger"):
        import_world.import_world(session, owner(session), source)


def test_unknown_organization_field_stops_the_import(app: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    sign_in(app)
    source = write_source(tmp_path)
    path = source / "data" / "yaml" / "organizations.yaml"
    path.write_text(ORGANIZATIONS + '    ceo: "Someone"\n', encoding="UTF8")
    with Session(engine) as session, pytest.raises(import_world.WorldImportError, match="ceo"):
        import_world.import_world(session, owner(session), source)


def test_find_owner(app: webtest.TestApp, engine: Engine) -> None:
    with Session(engine) as session, pytest.raises(import_world.WorldImportError, match="sign in once"):
        owner(session, "nobody@example.com")
    sign_in(app)
    sign_in(app, sub="second-google-account")
    with Session(engine) as session:
        with pytest.raises(import_world.WorldImportError, match="several accounts"):
            owner(session)
        assert import_world.find_owner(session, "alice@example.com", "1234567890").google_sub == "1234567890"


# ─── adding, editing, deleting ───────────────────────────────────────────────

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 32


def people_ids(app: webtest.TestApp) -> dict[str, int]:
    return {p["name"]: p["id"] for p in app.get("/api/people").json}


def test_add_concert_with_photo(imported: webtest.TestApp) -> None:
    upload = imported.post("/api/images", upload_files=[("file", "show.jpg", JPEG)]).json
    ids = people_ids(imported)
    concert = imported.post_json("/api/concerts", {
        "name": "New Show", "performers": [ids["Alice Friend"]], "date": "2024-05",
        "date_timezone": "Asia/Jerusalem", "people": [ids["Bob Buddy"]], "tickets": "2",
        "broadcast": True, "image_id": upload["id"],
    }, status=201).json
    assert [p["name"] for p in concert["performers"]] == ["Alice Friend"]
    assert concert["date"] == "2024-05"
    assert concert["date_precision"] == "month"
    assert concert["with"] == ["Bob Buddy"]
    assert concert["image"] == upload["url"]
    assert imported.get(upload["url"]).body == JPEG
    assert "New Show" in [c["name"] for c in imported.get("/api/concerts").json]


def test_add_validates(imported: webtest.TestApp) -> None:
    imported.post_json("/api/concerts", {"name": ""}, status=400)
    imported.post_json("/api/concerts", {"name": "x", "date": "2024-13"}, status=400)
    imported.post_json("/api/concerts", {"name": "x", "date": "last year"}, status=400)
    imported.post_json("/api/concerts", {"name": "x", "date_timezone": "Mars/Olympus"}, status=400)
    imported.post_json("/api/concerts", {"name": "x", "people": [999]}, status=400)
    imported.post_json("/api/museums", {"name": "x", "rating": 11}, status=400)
    imported.post_json("/api/people", {"name": "Alice Friend"}, status=409)
    imported.post("/api/images", upload_files=[("file", "x.jpg", b"not an image")], status=400)


def test_add_museum_and_person(imported: webtest.TestApp) -> None:
    person = imported.post_json("/api/people", {"name": "Carol", "description": "Zed"}, status=201).json
    museum = imported.post_json("/api/museums", {
        "name": "Prado", "city": "Madrid", "date": "2012", "rating": 9, "people": [person["id"]],
    }, status=201).json
    assert museum["date"] == "2012"
    assert museum["with"] == ["Carol"]
    assert museum["image"] is None


def test_edit_keeps_a_timestamp_sent_back_unchanged(imported: webtest.TestApp) -> None:
    late = next(c for c in imported.get("/api/concerts").json if c["name"] == "Late Show")
    body = dict(late, name="Late Late Show", people=[p["id"] for p in late["people"]][:1], performers=[p["id"] for p in late["performers"]])
    edited = imported.put_json(f"/api/concerts/{late['id']}", body).json
    assert edited["name"] == "Late Late Show"
    assert edited["date"] == "2020-01-01T22:30:00Z"
    assert edited["with"] == ["Alice Friend"]
    # the photo stays when no new one is uploaded
    assert edited["image"] == late["image"]
    edited = imported.put_json(f"/api/concerts/{late['id']}", dict(body, date="2020-01-02")).json
    assert edited["date"] == "2020-01-02"
    assert edited["date_precision"] == "day"


def test_edit_person(imported: webtest.TestApp) -> None:
    ids = people_ids(imported)
    imported.put_json(f"/api/people/{ids['Bob Buddy']}", {"name": "Alice Friend"}, status=409)
    bob = imported.put_json(f"/api/people/{ids['Bob Buddy']}", {"name": "Robert Buddy", "description": "x"}).json
    assert bob["name"] == "Robert Buddy"
    louvre = next(m for m in imported.get("/api/museums").json if m["with"])
    assert louvre["with"] == ["Robert Buddy"]
    # no organizations sent: the person is linked to none
    assert bob["organizations"] == []


def organization_ids(app: webtest.TestApp) -> dict[str, int]:
    return {c["name"]: c["id"] for c in app.get("/api/organizations").json}


def test_link_person_to_organizations(imported: webtest.TestApp) -> None:
    organizations = organization_ids(imported)
    bob = people_ids(imported)["Bob Buddy"]
    edited = imported.put_json(f"/api/people/{bob}", {
        "name": "Bob Buddy", "organizations": [organizations["Old School"], organizations["Acme"]],
    }).json
    assert [c["name"] for c in edited["organizations"]] == ["Acme", "Old School"]
    school = next(c for c in imported.get("/api/organizations").json if c["name"] == "Old School")
    assert [p["name"] for p in school["people"]] == ["Bob Buddy"]
    imported.put_json(f"/api/people/{bob}", {"name": "Bob Buddy", "organizations": [999]}, status=400)
    imported.put_json(f"/api/people/{bob}", {"name": "Bob Buddy", "organizations": "Acme"}, status=400)


def test_add_edit_delete_organization(imported: webtest.TestApp, engine: Engine) -> None:
    imported.post_json("/api/organizations", {"name": ""}, status=400)
    imported.post_json("/api/organizations", {"name": "Acme"}, status=409)
    upload = imported.post("/api/images", upload_files=[("file", "logo.jpg", JPEG)]).json
    organization = imported.post_json("/api/organizations", {
        "name": "Newco", "functions": ["consulting", " "], "website": "https://newco.example", "image_id": upload["id"],
    }, status=201).json
    assert organization["functions"] == ["consulting"]
    assert organization["image"] == upload["url"]
    acme = next(c for c in imported.get("/api/organizations").json if c["name"] == "Acme")
    edited = imported.put_json(f"/api/organizations/{acme['id']}", dict(acme, name="Acme Ltd", image_id=upload["id"])).json
    assert edited["name"] == "Acme Ltd"
    assert edited["what_happened"] == "Bought by Bigco"
    # people keep the link through a rename
    assert [p["name"] for p in edited["people"]] == ["Bob Buddy"]
    with Session(engine) as session:
        # the logo nothing shows any more is gone; the details the dialog never sends are kept
        assert "acme.svg" not in session.scalars(select(Image.filename)).all()
        kept = session.get(Organization, acme["id"])
        assert kept is not None
        assert kept.details["slug"] == "acme"
    imported.delete(f"/api/organizations/{acme['id']}", status=204)
    bob = next(p for p in imported.get("/api/people").json if p["name"] == "Bob Buddy")
    assert [c["name"] for c in bob["organizations"]] == ["Startup"]


def test_delete(imported: webtest.TestApp, engine: Engine) -> None:
    ids = people_ids(imported)
    imported.delete(f"/api/people/{ids['Alice Friend']}", status=204)
    assert all("Alice Friend" not in c["with"] for c in imported.get("/api/concerts").json)
    for concert in imported.get("/api/concerts").json:
        imported.delete(f"/api/concerts/{concert['id']}", status=204)
    assert imported.get("/api/concerts").json == []
    with Session(engine) as session:
        # the concert photo went with its last concert; the museum one stays
        assert sorted(session.scalars(select(Image.filename)).all()) == ["acme.svg", "museum-15.jpg"]
        assert session.scalar(select(func.count()).select_from(concert_people)) == 0
    imported.delete("/api/concerts/1", status=404)


def test_edit_replaces_photo_and_drops_the_old_one(imported: webtest.TestApp, engine: Engine) -> None:
    upload = imported.post("/api/images", upload_files=[("file", "new.jpg", JPEG)]).json
    for concert in imported.get("/api/concerts").json:
        if concert["image"]:
            imported.put_json(f"/api/concerts/{concert['id']}", dict(concert, image_id=upload["id"], people=[], performers=[]))
    with Session(engine) as session:
        assert "concert-the-band.jpg" not in session.scalars(select(Image.filename)).all()


def test_others_cannot_touch(imported: webtest.TestApp) -> None:
    concert = imported.get("/api/concerts").json[0]
    alice = people_ids(imported)["Alice Friend"]
    imported.post("/auth/logout")
    sign_in(imported, sub="someone-else")
    imported.put_json(f"/api/concerts/{concert['id']}", {"name": "mine now"}, status=404)
    imported.delete(f"/api/concerts/{concert['id']}", status=404)
    imported.delete(f"/api/people/{alice}", status=404)
    assert organization_ids(imported) == {}
    imported.post_json("/api/people", {"name": "x", "organizations": [1]}, status=400)
    imported.put_json("/api/organizations/1", {"name": "mine now"}, status=404)
    imported.delete("/api/organizations/1", status=404)
    imported.put_json("/api/organization-types/1", {"name": "mine now"}, status=404)
    imported.delete("/api/organization-types/1", status=404)
    imported.post_json("/api/organizations", {"name": "x", "type_id": 1}, status=400)
    imported.post_json("/api/concerts", {"name": "x", "people": [alice]}, status=400)
