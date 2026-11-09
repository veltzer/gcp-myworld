"""
The concerts, museums, people and organizations: the import script and the API.
"""

import gzip
import json
from pathlib import Path

import flask
import import_world
import pytest
import webtest
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from myworld.models import (
    AudioCourse,
    Concert,
    Image,
    Museum,
    Organization,
    OrganizationType,
    Person,
    User,
    YouTubeVideo,
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


AUDIO_COURSES = """
items:
  - name: "Famous Greeks"
    lecturers: ["Bob Buddy"]
    date_utcz: "2019-09-21T09:28:55Z"
    date_timezone: "Asia/Jerusalem"
    device: "Samsung S10"
    location: "Night Walks"
    rating: 8
    review: "Pretty good"
    great_courses_id: 337
    great_courses_slug: "famous-greeks"
  - name: "How to Listen to Music"
    lecturers: ["Robert Greenberg"]
    date_timezone: "Asia/Jerusalem"
    device: "Samsung S7"
    date_started_utcz: "2020-10-01T21:31:01Z"
    progress: "4/24"
    internal_id: 1
"""


YOUTUBE = """
items:
  - id: "VNIRUigPxA8"
    name: "Richard Dawkins in conversation"
    date_utcz: "2015-11-21T19:14:10Z"
    date_timezone: "Asia/Jerusalem"
    review: "Nice conversation."
    rating: 6
  - id: "5jqXEzplxeo"
    name: "BDS Movement Debate | Oxford Union"
    date_utcz: "2015-11-30T16:24:31Z"
    date_timezone: "Asia/Jerusalem"
    review: "interesting debate"
    rating: 7
    location: "Home"
    device: "Desktop"
"""


# the watch history, as yt-dlp left it: one also in YOUTUBE, one new, one YouTube no longer has
YOUTUBE_HISTORY = {"items": [
    {
        "categories": "News & Politics", "channel": "OxfordUnion", "duration": 3725, "title": "BDS Movement Debate",
        "upload_date": "2015-11-10", "view_count": 123456, "webpage_url": "https://www.youtube.com/watch?v=5jqXEzplxeo",
    },
    {
        "categories": "Entertainment", "channel": "agadmator's Chess Channel", "duration": 391, "title": "Carlsen Crushes a GM",
        "upload_date": "2017-09-28", "view_count": 1000, "webpage_url": "https://www.youtube.com/watch?v=-0-EI_f9oXs",
    },
    {"status": "missing", "title": "Metadata unavailable", "video_id": "-0dYmE1lyw4", "webpage_url": "https://www.youtube.com/watch?v=-0dYmE1lyw4"},
]}


# by the logo convention (doc/logos.md), so the checks pass on imported data
LOGO = b'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1000" viewBox="-1 -1 12 12"><rect width="10" height="10"/></svg>'


def write_source(root: Path, concerts: str = CONCERTS) -> Path:
    (root / "data" / "yaml").mkdir(parents=True)
    (root / "static" / "images").mkdir(parents=True)
    (root / "data" / "logos").mkdir(parents=True)
    for name, text in (("people", PEOPLE), ("concerts", concerts), ("museums", MUSEUMS), ("organizations", ORGANIZATIONS), ("audio_courses", AUDIO_COURSES), ("video_youtube", YOUTUBE)):
        (root / "data" / "yaml" / f"{name}.yaml").write_text(text, encoding="UTF8")
    (root / "data" / "logos" / "acme.svg").write_bytes(LOGO)
    (root / "static" / "data").mkdir(parents=True)
    with gzip.open(root / "static" / "data" / "youtube.json.gz", "wt", encoding="UTF8") as fp:
        json.dump(YOUTUBE_HISTORY, fp)
    (root / "static" / "images" / "concert-the-band.jpg").write_bytes(b"\xff\xd8band")
    (root / "static" / "images" / "museum-15.jpg").write_bytes(b"\xff\xd8louvre")
    (root / "static" / "images" / "audiocourse-gc-337.jpg").write_bytes(b"\xff\xd8greeks")
    (root / "static" / "images" / "audiocourse-internal-1.jpg").write_bytes(b"\xff\xd8music")
    return root


def owner(session: Session, email: str = "alice@example.com") -> User:
    return import_world.find_owner(session, email, None)


@pytest.fixture(name="imported")
def fixture_imported(app: webtest.TestApp, engine: Engine, tmp_path: Path) -> webtest.TestApp:
    sign_in(app)
    with Session(engine) as session:
        counts = import_world.import_world(session, owner(session), write_source(tmp_path))
        session.commit()
    assert counts == {
        "people": 5, "organizations": 3, "organization types": 7, "relation types": 6, "person types": 5, "people with a type": 5,
        "concerts": 3, "museums": 3, "audio courses": 2, "YouTube videos": 4, "devices": 3, "images": 5}
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


def test_audio_courses(imported: webtest.TestApp) -> None:
    courses = imported.get("/api/audio-courses").json
    # finished first, then the one still in progress
    assert [c["name"] for c in courses] == ["Famous Greeks", "How to Listen to Music"]
    greeks, music = courses
    assert (greeks["status"], greeks["date"], greeks["date_precision"]) == ("done", "2019-09-21T09:28:55Z", "time")
    assert [p["name"] for p in greeks["lecturers"]] == ["Bob Buddy"]
    assert (greeks["device"]["name"], greeks["listened_at"], greeks["rating"], greeks["review"]) == ("Samsung S10", "Night Walks", 8, "Pretty good")
    assert greeks["url"] == "https://www.thegreatcourses.com/courses/famous-greeks"
    assert greeks["image"] is not None
    assert (music["status"], music["date"], music["started"], music["progress"]) == ("in_progress", None, "2020-10-01T21:31:01Z", "4/24")
    assert music["url"] == ""
    # a lecturer people.yaml did not have is a new person, typed Lecturer
    people = {p["name"]: p for p in imported.get("/api/people").json}
    assert [t["name"] for t in people["Robert Greenberg"]["types"]] == ["Lecturer"]
    assert music["lecturers"] == [{"id": people["Robert Greenberg"]["id"], "name": "Robert Greenberg"}]


def test_edit_audio_course(imported: webtest.TestApp) -> None:
    music = next(c for c in imported.get("/api/audio-courses").json if c["name"] == "How to Listen to Music")
    body = dict(music, lecturers=[p["id"] for p in music["lecturers"]], progress="24/24", date="2021-05-02", rating=9)
    edited = imported.put_json(f"/api/audio-courses/{music['id']}", body).json
    assert (edited["status"], edited["date"], edited["progress"], edited["rating"]) == ("done", "2021-05-02", "24/24", 9)
    # the start sent back as it was shown keeps its time
    assert edited["started"] == "2020-10-01T21:31:01Z"
    added = imported.post_json("/api/audio-courses", {"name": "New Course", "started": "2024-01-02"}, status=201).json
    assert (added["status"], added["started"]) == ("in_progress", "2024-01-02T00:00:00Z")
    imported.post_json("/api/audio-courses", {"name": "x", "started": "soon"}, status=400)
    # a course no longer sold links to any page about it; a store page comes first
    linked = imported.post_json("/api/audio-courses", {"name": "Old Course", "link": "https://example.org/old"}, status=201).json
    assert (linked["link"], linked["url"]) == ("https://example.org/old", "https://example.org/old")
    both = imported.put_json(f"/api/audio-courses/{linked['id']}", dict(linked, lecturers=[], audible_asin="B000000000")).json
    assert both["url"] == "https://www.audible.com/pd/B000000000"
    imported.post_json("/api/audio-courses", {"name": "x", "link": "javascript:alert(1)"}, status=400)
    imported.delete(f"/api/audio-courses/{linked['id']}", status=204)
    imported.delete(f"/api/audio-courses/{added['id']}", status=204)
    assert len(imported.get("/api/audio-courses").json) == 2


def test_devices(imported: webtest.TestApp) -> None:
    devices = imported.get("/api/devices").json
    # a list kept like the types: each with how many audio courses point to it
    assert [(d["name"], d["count"]) for d in devices] == [("Desktop", 1), ("Samsung S10", 1), ("Samsung S7", 1)]
    desktop, s10, s7 = devices
    # a YouTube video's device counts too, and keeps it from being deleted
    imported.delete(f"/api/devices/{desktop['id']}", status=409)
    music = next(c for c in imported.get("/api/audio-courses").json if c["name"] == "How to Listen to Music")
    body = dict(music, lecturers=[p["id"] for p in music["lecturers"]], device_id=s10["id"])
    assert imported.put_json(f"/api/audio-courses/{music['id']}", body).json["device"] == {"id": s10["id"], "name": "Samsung S10"}
    # a device in use is not deleted; an unused one is
    imported.delete(f"/api/devices/{s10['id']}", status=409)
    imported.delete(f"/api/devices/{s7['id']}", status=204)
    sansa = imported.post_json("/api/devices", {"name": "Sansa Clip 2", "description": "MP3 player"}, status=201).json
    imported.post_json("/api/devices", {"name": "Sansa Clip 2"}, status=409)
    edited = imported.put_json(f"/api/audio-courses/{music['id']}", dict(body, device_id=sansa["id"])).json
    assert edited["device"]["name"] == "Sansa Clip 2"
    # no device, and a device of no one's
    assert imported.put_json(f"/api/audio-courses/{music['id']}", dict(body, device_id="")).json["device"] is None
    imported.put_json(f"/api/audio-courses/{music['id']}", dict(body, device_id=99999), status=400)


def test_audio_courses_import_adds_once(imported: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    del imported
    source = tmp_path / "again"
    write_source(source)
    with Session(engine) as session:
        # an account that has audio courses keeps them: the additive import stops
        with pytest.raises(import_world.WorldImportError, match="has audio courses already"):
            import_world.import_audio_courses(session, owner(session), source)
        for course in session.scalars(select(AudioCourse)):
            session.delete(course)
        session.flush()
        counts = import_world.import_audio_courses(session, owner(session), source)
        session.commit()
    # the lecturers are the people already there, and the covers the images already stored: nothing is added twice
    assert counts == {"audio courses": 2, "lecturers added": 0, "devices added": 0, "images": 0}


def test_youtube(imported: webtest.TestApp) -> None:
    videos = imported.get("/api/youtube").json
    # newest first; the watch history has no dates, so comes after, by name
    assert [v["youtube_id"] for v in videos] == ["5jqXEzplxeo", "VNIRUigPxA8", "-0-EI_f9oXs", "-0dYmE1lyw4"]
    debate, _, chess, gone = videos
    # in both files: one row, with the review and YouTube's details
    assert (debate["review"], debate["channel"], debate["category"], debate["duration"], debate["uploaded"], debate["views"]) == (
        "interesting debate", "OxfordUnion", "News & Politics", 3725, "2015-11-10", 123456)
    assert (chess["name"], chess["date"], chess["review"], chess["unavailable"]) == ("Carlsen Crushes a GM", None, "", False)
    # one YouTube no longer has: only its id, no name, and it can be edited without one
    assert (gone["name"], gone["unavailable"], gone["channel"]) == ("", True, "")
    assert imported.put_json(f"/api/youtube/{gone['id']}", dict(gone, device_id="", rating=5)).json["rating"] == 5
    assert (debate["date"], debate["rating"], debate["watched_at"], debate["device"]["name"]) == ("2015-11-30T16:24:31Z", 7, "Home", "Desktop")
    # the page builds YouTube's URLs from the id
    assert "url" not in debate and "image" not in debate
    # a link pasted in place of the id is taken apart
    added = imported.post_json("/api/youtube", {"name": "Talk", "youtube_id": "https://youtu.be/JbNJoHFsQnc?t=10", "date": "2024-05-01"}, status=201).json
    assert added["youtube_id"] == "JbNJoHFsQnc"
    body = dict(added, device_id="")
    for link in ("https://www.youtube.com/watch?v=JbNJoHFsQnc&list=x", "https://www.youtube.com/shorts/JbNJoHFsQnc", "JbNJoHFsQnc"):
        assert imported.put_json(f"/api/youtube/{added['id']}", dict(body, youtube_id=link)).json["youtube_id"] == "JbNJoHFsQnc"
    # a malformed id, and a video listed twice
    imported.put_json(f"/api/youtube/{added['id']}", dict(body, youtube_id="JbNJoHFsQncS"), status=400)
    imported.post_json("/api/youtube", {"name": "Again", "youtube_id": "5jqXEzplxeo"}, status=409)
    imported.delete(f"/api/youtube/{added['id']}", status=204)
    assert len(imported.get("/api/youtube").json) == 4


def test_youtube_history_runs_again(imported: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    del imported
    source = tmp_path / "again"
    write_source(source)
    with Session(engine) as session:
        counts = import_world.import_youtube_history(session, owner(session), source)
        session.commit()
    # nothing new: every video is there, and gets its details again
    assert counts == {"YouTube videos added": 0, "YouTube videos given details": 3}


def test_long_json_is_gzipped(imported: webtest.TestApp) -> None:
    # small: sent as it is
    small = imported.get("/api/youtube", headers={"Accept-Encoding": "gzip"})
    assert "Accept-Encoding" not in small.headers.get("Vary", "")
    # long: gzipped (WebTest takes the gzip apart again, so what is left to see is the Vary)
    flask_app = imported.app
    assert isinstance(flask_app, flask.Flask)
    flask_app.config["GZIP_MIN_BYTES"] = 10
    zipped = imported.get("/api/youtube", headers={"Accept-Encoding": "gzip"})
    assert "Accept-Encoding" in zipped.headers["Vary"]
    assert len(zipped.json) == 4
    # a client that does not take gzip gets it plain
    assert "Accept-Encoding" not in imported.get("/api/youtube").headers.get("Vary", "")


def test_youtube_import_adds_once(imported: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    del imported
    source = tmp_path / "again"
    write_source(source)
    with Session(engine) as session:
        with pytest.raises(import_world.WorldImportError, match="has YouTube videos already"):
            import_world.import_youtube(session, owner(session), source)
        session.execute(delete(YouTubeVideo))
        counts = import_world.import_youtube(session, owner(session), source)
        session.commit()
    # the devices are those already there
    assert counts == {"YouTube videos": 2, "devices added": 0}


def test_people_links_point_at_people(imported: webtest.TestApp) -> None:
    ids = {p["name"]: p["id"] for p in imported.get("/api/people").json}
    for path in ("/api/concerts", "/api/museums"):
        for item in imported.get(path).json:
            assert [ids[p["name"]] for p in item["people"]] == [p["id"] for p in item["people"]]


def test_people(imported: webtest.TestApp) -> None:
    people = imported.get("/api/people").json
    # Robert Greenberg is a lecturer of audio_courses.yaml
    assert [p["name"] for p in people] == ["Alice Friend", "Bob Buddy", "Robert Greenberg", "Singer", "The Band"]
    alice, bob, _, _, _ = people
    assert alice["description"] == "Old friend"
    assert [c["name"] for c in alice["organizations"]] == ["Startup"]
    assert [c["name"] for c in bob["organizations"]] == ["Acme", "Startup"]
    # only the person and their organizations: their concerts and museums are not listed next to them
    assert set(alice) == {"id", "name", "first_name", "surname", "types", "organizations", "description"}


def test_organizations(imported: webtest.TestApp) -> None:
    organizations = imported.get("/api/organizations").json
    assert [c["name"] for c in organizations] == ["Acme", "Old School", "Startup"]
    acme, school, startup = organizations
    # the functions of organizations.yaml become relation types
    assert [r["name"] for r in acme["relations"]] == ["Consulting", "Teaching"]
    assert [r["name"] for r in school["relations"]] == ["Education"]
    assert acme["status"] == "acquired"
    assert acme["what_happened"] == "Bought by Bigco"
    assert acme["website"] == "https://acme.example"
    assert [p["name"] for p in acme["people"]] == ["Bob Buddy"]
    assert [p["name"] for p in startup["people"]] == ["Alice Friend", "Bob Buddy"]
    # an organization only a person names has nothing but its name
    assert startup["relations"] == []
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
    assert types["Company"]["count"] == 2
    assert types["University"]["count"] == 1
    assert types["Military"]["count"] == 0
    by_name = {o["name"]: o for o in imported.get("/api/organizations").json}
    assert by_name["Old School"]["type"] == {"id": types["University"]["id"], "name": "University"}
    assert by_name["Acme"]["type"]["name"] == "Company"


def test_person_types(imported: webtest.TestApp) -> None:
    types = {t["name"]: t for t in imported.get("/api/person-types").json}
    assert sorted(types) == sorted(import_world.PERSON_TYPES)
    people = {p["name"]: [t["name"] for t in p["types"]] for p in imported.get("/api/people").json}
    # Alice and Bob are at organizations; the two performers people.yaml does not have are Performers
    assert people["Alice Friend"] == ["Co-Worker"]
    assert people["Bob Buddy"] == ["Co-Worker"]
    assert people["Singer"] == ["Performer"]
    assert people["The Band"] == ["Performer"]
    assert types["Performer"]["count"] == 2
    friend = imported.post_json("/api/person-types", {"name": "Friend"}, status=201).json
    alice = next(p for p in imported.get("/api/people").json if p["name"] == "Alice Friend")
    neighbor = imported.post_json("/api/person-types", {"name": "Neighbor"}, status=201).json
    # a person may be of several types at once
    edited = imported.put_json(f"/api/people/{alice['id']}", {
        "first_name": "Alice", "surname": "Friend", "type_ids": [neighbor["id"], friend["id"]],
    }).json
    assert edited["types"] == [{"id": friend["id"], "name": "Friend"}, {"id": neighbor["id"], "name": "Neighbor"}]
    counts = {t["name"]: t["count"] for t in imported.get("/api/person-types").json}
    assert (counts["Friend"], counts["Neighbor"], counts["Co-Worker"]) == (1, 1, 1)
    imported.delete(f"/api/person-types/{friend['id']}", status=409)
    imported.put_json(f"/api/people/{alice['id']}", {"first_name": "Alice", "type_ids": [9999]}, status=400)
    imported.put_json(f"/api/people/{alice['id']}", {"first_name": "Alice", "type_ids": friend["id"]}, status=400)
    # taking a type off frees it for deleting
    imported.put_json(f"/api/people/{alice['id']}", {"first_name": "Alice", "type_ids": [neighbor["id"]]})
    imported.delete(f"/api/person-types/{friend['id']}", status=204)


def test_split_name() -> None:
    assert import_world.split_name("Doron Veltzer") == ("Doron", "Veltzer")
    assert import_world.split_name("Yaron Ben-Ami") == ("Yaron", "Ben-Ami")
    assert import_world.split_name("Oded from MAFAT") == ("Oded from MAFAT", "")
    assert import_world.split_name("The Band") == ("The Band", "")
    assert import_world.split_name("Marmir") == ("Marmir", "")


def test_people_may_share_a_name(imported: webtest.TestApp) -> None:
    first = imported.post_json("/api/people", {"first_name": "Dana", "surname": "Cohen", "description": "School"}, status=201).json
    second = imported.post_json("/api/people", {"first_name": "Dana", "surname": "Cohen", "description": "Work"}, status=201).json
    assert first["id"] != second["id"]
    danas = [p for p in imported.get("/api/people").json if p["name"] == "Dana Cohen"]
    assert [p["description"] for p in danas] == ["School", "Work"]


def test_guessing_a_person_type() -> None:
    def person(name: str, description: str = "") -> Person:
        first_name, surname = import_world.split_name(name)
        return Person(first_name=first_name, surname=surname, description=description)
    assert import_world._person_type(person("Doron Veltzer")) == "Family"
    assert import_world._person_type(person("X", "My brother")) == "Family"
    assert import_world._person_type(person("X", "My brothers ex-girlfriend")) is None
    assert import_world._person_type(person("X", "Ex-girlfriend")) == "Girlfriend"
    assert import_world._person_type(person("X", "Yaron's girlfriend")) is None
    assert import_world._person_type(person("X", "Physics guy from MAFAT")) == "Co-Worker"


def test_give_types_fills_only_what_is_missing(imported: webtest.TestApp, engine: Engine) -> None:
    with Session(engine) as session:
        session.execute(update(Organization).values(type_id=None))
        session.execute(delete(OrganizationType).where(OrganizationType.name == "Military"))
        session.commit()
        counts = import_world.give_types(session, owner(session))
        session.commit()
    assert counts == {"types added": 1, "organizations given a type": 3, "people given a type": 0}
    by_name = {o["name"]: o["type"]["name"] for o in imported.get("/api/organizations").json}
    # Old School's type came from the YAML, which this does not read: it gets the default
    assert by_name == {"Acme": "Company", "Old School": "Company", "Startup": "Company"}
    with Session(engine) as session:
        assert import_world.give_types(session, owner(session)) == {"types added": 0, "organizations given a type": 0, "people given a type": 0}


def test_edit_organization_types(imported: webtest.TestApp) -> None:
    imported.post_json("/api/organization-types", {"name": ""}, status=400)
    imported.post_json("/api/organization-types", {"name": "Company"}, status=409)
    lab = imported.post_json("/api/organization-types", {"name": "Lab", "description": "Research"}, status=201).json
    assert lab["count"] == 0
    acme = next(o for o in imported.get("/api/organizations").json if o["name"] == "Acme")
    edited = imported.put_json(f"/api/organizations/{acme['id']}", dict(acme, type_id=lab["id"])).json
    assert edited["type"]["name"] == "Lab"
    imported.put_json(f"/api/organizations/{acme['id']}", dict(acme, type_id=999), status=400)
    renamed = imported.put_json(f"/api/organization-types/{lab['id']}", {"name": "Laboratory"}).json
    assert renamed["count"] == 1
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
    assert imported.get("/api/person-types").json == []
    imported.get(url, status=404)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Concert)) == 3


def test_reimport_replaces(imported: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        import_world.import_world(session, owner(session), tmp_path)
        session.commit()
        for model, count in ((Concert, 3), (Museum, 3), (AudioCourse, 2), (Person, 5), (Organization, 3), (Image, 5)):
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
    imported.post_json("/api/museums", {"name": "x", "latitude": 91, "longitude": 0}, status=400)
    imported.post_json("/api/museums", {"name": "x", "latitude": "north", "longitude": 0}, status=400)
    # one coordinate without the other is no place
    imported.post_json("/api/organizations", {"name": "x", "latitude": 32.1}, status=400)
    imported.post_json("/api/people", {"first_name": ""}, status=400)
    imported.post_json("/api/people", {"first_name": " ", "surname": " "}, status=400)
    imported.post("/api/images", upload_files=[("file", "x.jpg", b"not an image")], status=400)


def test_person_with_one_name(imported: webtest.TestApp) -> None:
    surname_only = imported.post_json("/api/people", {"surname": "Cohen"}, status=201).json
    assert (surname_only["first_name"], surname_only["surname"], surname_only["name"]) == ("", "Cohen", "Cohen")
    first_only = imported.post_json("/api/people", {"first_name": "Dana", "surname": ""}, status=201).json
    assert first_only["name"] == "Dana"
    imported.put_json(f"/api/people/{first_only['id']}", {"first_name": "", "surname": ""}, status=400)


def test_person_with_no_name(imported: webtest.TestApp) -> None:
    # the description is what such a person is called, in pickers and elsewhere
    guide = imported.post_json("/api/people", {"description": "the guide at the Louvre"}, status=201).json
    assert (guide["first_name"], guide["surname"], guide["name"]) == ("", "", "the guide at the Louvre")
    concert = imported.post_json("/api/concerts", {"name": "x", "people": [guide["id"]]}, status=201).json
    assert concert["with"] == ["the guide at the Louvre"]
    imported.put_json(f"/api/people/{guide['id']}", {"description": " "}, status=400)


def test_add_museum_and_person(imported: webtest.TestApp) -> None:
    person = imported.post_json("/api/people", {"first_name": "Carol", "description": "Zed"}, status=201).json
    museum = imported.post_json("/api/museums", {
        "name": "Prado", "city": "Madrid", "date": "2012", "rating": 9, "people": [person["id"]],
    }, status=201).json
    assert museum["date"] == "2012"
    assert museum["with"] == ["Carol"]
    assert museum["image"] is None


def test_museum_alone(imported: webtest.TestApp) -> None:
    alone = imported.post_json("/api/museums", {"name": "Prado", "alone": True}, status=201).json
    assert alone["alone"] is True
    assert alone["with"] == []
    assert imported.post_json("/api/museums", {"name": "Tate"}, status=201).json["alone"] is False
    # alone with company is a contradiction
    person = imported.post_json("/api/people", {"first_name": "Carol"}, status=201).json
    imported.post_json("/api/museums", {"name": "Uffizi", "alone": True, "people": [person["id"]]}, status=400)


def test_addresses_and_coordinates(imported: webtest.TestApp) -> None:
    museum = imported.post_json("/api/museums", {
        "name": "Prado", "address": "Calle de Ruiz de Alarcón 23, Madrid, Spain", "latitude": "40.4138", "longitude": -3.6921,
    }, status=201).json
    assert (museum["address"], museum["latitude"], museum["longitude"]) == ("Calle de Ruiz de Alarcón 23, Madrid, Spain", 40.4138, -3.6921)
    # a dialog with the coordinates cleared leaves the place off the map
    cleared = imported.put_json(f"/api/museums/{museum['id']}", dict(museum, people=[], latitude="", longitude="")).json
    assert (cleared["latitude"], cleared["longitude"]) == (None, None)
    organization = imported.post_json("/api/organizations", {"name": "Glil", "address": "Kibbutz Glil Yam, Israel", "latitude": 32.15556, "longitude": 34.82361}, status=201).json
    assert (organization["latitude"], organization["longitude"]) == (32.15556, 34.82361)


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
    bob = imported.put_json(f"/api/people/{ids['Bob Buddy']}", {"first_name": "Robert", "surname": "Buddy", "description": "x"}).json
    assert bob["name"] == "Robert Buddy"
    assert (bob["first_name"], bob["surname"]) == ("Robert", "Buddy")
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
        "first_name": "Bob", "surname": "Buddy", "organizations": [organizations["Old School"], organizations["Acme"]],
    }).json
    assert [c["name"] for c in edited["organizations"]] == ["Acme", "Old School"]
    school = next(c for c in imported.get("/api/organizations").json if c["name"] == "Old School")
    assert [p["name"] for p in school["people"]] == ["Bob Buddy"]
    imported.put_json(f"/api/people/{bob}", {"first_name": "Bob", "organizations": [999]}, status=400)
    imported.put_json(f"/api/people/{bob}", {"first_name": "Bob", "organizations": "Acme"}, status=400)


def test_relation_types(imported: webtest.TestApp) -> None:
    # every import starts with the six; counts are of the user's organizations
    counts = {t["name"]: t["count"] for t in imported.get("/api/relation-types").json}
    assert counts == {
        "Certification": 0, "Consulting": 1, "Education": 1, "Publisher": 0, "Teaching": 1, "Training provider": 0,
    }
    board = imported.post_json("/api/relation-types", {"name": "Board member", "description": "I sat on the board"}, status=201).json
    imported.post_json("/api/relation-types", {"name": "Board member"}, status=409)
    startup = next(c for c in imported.get("/api/organizations").json if c["name"] == "Startup")
    imported.put_json(f"/api/organizations/{startup['id']}", {"name": "Startup", "relation_ids": [board["id"]]})
    # a type in use cannot go: no organization silently loses a relation
    imported.delete(f"/api/relation-types/{board['id']}", status=409)
    imported.put_json(f"/api/organizations/{startup['id']}", {"name": "Startup", "relation_ids": []})
    imported.delete(f"/api/relation-types/{board['id']}", status=204)
    stats = imported.get("/api/stats").json
    assert stats["relation_types"] == 6
    assert {"name": "No relation", "count": 1} in stats["organizations_by_relation"]


def test_add_edit_delete_organization(imported: webtest.TestApp, engine: Engine) -> None:
    imported.post_json("/api/organizations", {"name": ""}, status=400)
    imported.post_json("/api/organizations", {"name": "Acme"}, status=409)
    upload = imported.post("/api/images", upload_files=[("file", "logo.jpg", JPEG)]).json
    relations = {t["name"]: t["id"] for t in imported.get("/api/relation-types").json}
    imported.post_json("/api/organizations", {"name": "Badco", "relation_ids": [999]}, status=400)
    organization = imported.post_json("/api/organizations", {
        "name": "Newco", "relation_ids": [relations["Consulting"]], "website": "https://newco.example", "image_id": upload["id"],
    }, status=201).json
    assert [r["name"] for r in organization["relations"]] == ["Consulting"]
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
        assert sorted(session.scalars(select(Image.filename)).all()) == ["acme.svg", "audiocourse-gc-337.jpg", "audiocourse-internal-1.jpg", "museum-15.jpg"]
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
    imported.post_json("/api/people", {"first_name": "x", "organizations": [1]}, status=400)
    imported.put_json("/api/organizations/1", {"name": "mine now"}, status=404)
    imported.delete("/api/organizations/1", status=404)
    imported.put_json("/api/organization-types/1", {"name": "mine now"}, status=404)
    imported.delete("/api/organization-types/1", status=404)
    imported.post_json("/api/organizations", {"name": "x", "type_id": 1}, status=400)
    imported.put_json("/api/person-types/1", {"name": "mine now"}, status=404)
    imported.post_json("/api/people", {"first_name": "x", "type_ids": [1]}, status=400)
    imported.post_json("/api/concerts", {"name": "x", "people": [alice]}, status=400)


# ─── stats ───────────────────────────────────────────────────────────────────

def test_stats(imported: webtest.TestApp) -> None:
    imported.post_json("/api/library", {"kind": "book", "title": "Dune", "status": "done"}, status=201)
    stats = imported.get("/api/stats").json
    assert (stats["concerts"], stats["museum_visits"], stats["museums"], stats["audio_courses"]) == (3, 3, 2, 2)
    assert (stats["people"], stats["organizations"], stats["images"]) == (5, 3, 5)
    assert (stats["organization_types"], stats["person_types"]) == (7, 5)
    # Bob, Singer and The Band performed; Bob also went with the user, he counts once
    assert stats["performers"] == 3
    books = next(k for k in stats["library"] if k["kind"] == "book")
    assert books["total"] == 1
    assert books["by_status"] == {"Done": 1}
    assert {t["name"]: t["count"] for t in stats["people_by_type"]} == {"Co-Worker": 2, "Performer": 2, "Lecturer": 1}
    assert {t["name"]: t["count"] for t in stats["organizations_by_type"]} == {"Company": 2, "University": 1}
    assert stats["concerts_by_year"] == [{"year": 1989, "count": 1}, {"year": 2001, "count": 1}, {"year": 2020, "count": 1}]
    assert stats["museums_by_year"] == [{"year": 2010, "count": 2}, {"year": 2011, "count": 1}]


def test_stats_are_per_user(imported: webtest.TestApp) -> None:
    imported.post("/auth/logout")
    sign_in(imported, sub="someone-else")
    stats = imported.get("/api/stats").json
    assert (stats["concerts"], stats["people"], stats["images"], stats["performers"]) == (0, 0, 0, 0)
    assert stats["concerts_by_year"] == []
