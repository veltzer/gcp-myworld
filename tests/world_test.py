"""
The concerts, museums and people: the import script and the read-only API.
"""

from pathlib import Path

import import_world
import pytest
import webtest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from myworld.models import Concert, Image, Museum, Person, User, concert_people
from tests.conftest import sign_in

PEOPLE = """
items:
  - name: "Alice Friend"
    description: "Old friend"
  - name: "Bob Buddy"
    company: "Acme"
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
    performers: ["Singer"]
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


def write_source(root: Path, concerts: str = CONCERTS) -> Path:
    (root / "data" / "yaml").mkdir(parents=True)
    (root / "static" / "images").mkdir(parents=True)
    for name, text in (("people", PEOPLE), ("concerts", concerts), ("museums", MUSEUMS)):
        (root / "data" / "yaml" / f"{name}.yaml").write_text(text, encoding="UTF8")
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
    assert counts == {"people": 2, "concerts": 3, "museums": 3, "images": 2}
    return app


def test_requires_login(app: webtest.TestApp) -> None:
    for path in ("/api/concerts", "/api/museums", "/api/people", "/api/images/1"):
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
    assert [p["name"] for p in people] == ["Alice Friend", "Bob Buddy"]
    alice, bob = people
    assert alice["description"] == "Old friend"
    assert sorted(c["name"] for c in alice["concerts"]) == ["Late Show", "The Band"]
    assert bob["company"] == "Acme"
    assert [m["name"] for m in bob["museums"]] == ["The Louvre"]


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
    imported.get(url, status=404)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Concert)) == 3


def test_reimport_replaces(imported: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        import_world.import_world(session, owner(session), tmp_path)
        session.commit()
        for model, count in ((Concert, 3), (Museum, 3), (Person, 2), (Image, 2)):
            assert session.scalar(select(func.count()).select_from(model)) == count
        assert session.scalar(select(func.count()).select_from(concert_people)) == 3
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


def test_find_owner(app: webtest.TestApp, engine: Engine) -> None:
    with Session(engine) as session, pytest.raises(import_world.WorldImportError, match="sign in once"):
        owner(session, "nobody@example.com")
    sign_in(app)
    sign_in(app, sub="second-google-account")
    with Session(engine) as session:
        with pytest.raises(import_world.WorldImportError, match="several accounts"):
            owner(session)
        assert import_world.find_owner(session, "alice@example.com", "1234567890").google_sub == "1234567890"
