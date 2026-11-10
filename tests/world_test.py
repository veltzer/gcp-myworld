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

from myworld import cities, names
from myworld.models import (
    AudioCourse,
    Concert,
    Image,
    Museum,
    Organization,
    OrganizationType,
    Person,
    PersonType,
    User,
    YouTubeVideo,
    concert_companions,
    library_entry_authors,
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


# books_read.yaml: read twice (once dated, rated and reviewed), read in
# translation with a Hebrew name, and owned but not read (no cover on the site)
BOOKS = """
items:
  - names:
      - language: "english"
        name: "The Hobbit"
        goodreads_id: "5907"
    authors:
      - - language: "english"
          name: "J.R.R. Tolkien"
    language: "english"
    ownings:
      - language: "english"
    readings:
      - language: "english"
        undated: true
      - language: "english"
        date: "2004-08-12T22:45:36Z"
        timezone: "Asia/Jerusalem"
        rating: 7
        review: "Good"
  - names:
      - language: "english"
        name: "Thirty Fifth in May"
      - language: "hebrew"
        name: "שלושים וחמישה במאי"
        simania_id: "7005"
    authors:
      - - language: "english"
          name: "Erich Kestner"
        - language: "hebrew"
          name: "אריך קסטנר"
    language: "german"
    readings:
      - language: "hebrew"
        undated: true
    remark: "was named: 35 May"
  - names:
      - language: "english"
        name: "Chess"
        simania_id: "11971"
    authors: []
    language: "hebrew"
    isbn: "1-58648-261-0"
    ownings:
      - language: "hebrew"
    readings: []
"""

TEXT_BOOKS = """
items:
  - name: "Thirty Fifth in May"
    authors: ["Erich Kestner"]
    review: "nice"
    rating: 8
"""


# by the logo convention (doc/logos.md), so the checks pass on imported data
LOGO = b'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1000" viewBox="-1 -1 12 12"><rect width="10" height="10"/></svg>'


def write_source(root: Path, concerts: str = CONCERTS) -> Path:
    (root / "data" / "yaml").mkdir(parents=True)
    (root / "static" / "images").mkdir(parents=True)
    (root / "data" / "logos").mkdir(parents=True)
    for name, text in (("people", PEOPLE), ("concerts", concerts), ("museums", MUSEUMS), ("organizations", ORGANIZATIONS), ("audio_courses", AUDIO_COURSES), ("video_youtube", YOUTUBE), ("books_read", BOOKS), ("text_books", TEXT_BOOKS)):
        (root / "data" / "yaml" / f"{name}.yaml").write_text(text, encoding="UTF8")
    (root / "data" / "logos" / "acme.svg").write_bytes(LOGO)
    (root / "static" / "data").mkdir(parents=True)
    with gzip.open(root / "static" / "data" / "youtube.json.gz", "wt", encoding="UTF8") as fp:
        json.dump(YOUTUBE_HISTORY, fp)
    (root / "static" / "images" / "concert-the-band.jpg").write_bytes(b"\xff\xd8band")
    (root / "static" / "images" / "museum-15.jpg").write_bytes(b"\xff\xd8louvre")
    (root / "static" / "images" / "audiocourse-gc-337.jpg").write_bytes(b"\xff\xd8greeks")
    (root / "static" / "images" / "audiocourse-internal-1.jpg").write_bytes(b"\xff\xd8music")
    (root / "static" / "images" / "book-goodreads-5907.jpg").write_bytes(b"\xff\xd8hobbit")
    (root / "static" / "images" / "book-simania-7005.jpg").write_bytes(b"\xff\xd8may")
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
        "people": 7, "organizations": 3, "organization types": 7, "relation types": 6, "person types": 3, "people with a profession": 4, "people related to the user": 2,
        "concerts": 3, "places": 1, "museums": 3, "audio courses": 2, "YouTube videos": 4, "devices": 3, "books": 3, "images": 7}
    return app


def test_requires_login(app: webtest.TestApp) -> None:
    for path in ("/api/concert-visits", "/api/museum-visits", "/api/people", "/api/organizations", "/api/organization-types", "/api/images/1"):
        app.get(path, status=401)


def test_concerts(imported: webtest.TestApp) -> None:
    concerts = imported.get("/api/concert-visits").json
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
    # where it was is a place; a show without a venue is at none
    assert {k: v for k, v in band["place"].items() if k != "id"} == {"name": "The Hall", "city": None}
    assert late["place"] is None


def test_person_relations(imported: webtest.TestApp) -> None:
    kinds = {k["name"]: k for k in imported.get("/api/person-relation-types").json}
    # the import starts the user with the family relations, each with how it reads the other way
    assert (kinds["Mother of"]["inverse"], kinds["Wife of"]["inverse"]) == ("Child of", "Spouse of")
    people = {p["name"]: p["id"] for p in imported.get("/api/people").json}
    alice, bob = people["Alice Friend"], people["Bob Buddy"]
    ann = imported.post_json("/api/people", {"first_name": "Ann", "relations": [{"type_id": kinds["Mother of"]["id"], "person_id": alice}]}, status=201).json
    assert [r["name"] for r in ann["relations"]] == ["Mother of Alice Friend"]
    # from the other side it reads the other way
    listed = {p["name"]: p for p in imported.get("/api/people").json}
    assert [(r["type"], r["person"]["id"]) for r in listed["Alice Friend"]["related"]] == [("Child of", ann["id"])]
    # one that reads the same both ways has no inverse
    friend = imported.post_json("/api/person-relation-types", {"name": "Pen pal of", "description": "Writes letters"}, status=201).json
    imported.put_json(f"/api/people/{bob}", {"first_name": "Bob", "surname": "Buddy", "relations": [{"type_id": friend["id"], "person_id": alice}]})
    assert "Pen pal of Bob Buddy" in [r["name"] for r in next(p for p in imported.get("/api/people").json if p["id"] == alice)["related"]]
    # an edit without relations keeps them; the user's own types and people only, never oneself
    imported.put_json(f"/api/people/{ann['id']}", {"first_name": "Ann", "description": "x"})
    assert len(next(p for p in imported.get("/api/people").json if p["id"] == ann["id"])["relations"]) == 1
    for bad in ([{"type_id": 9999, "person_id": alice}], [{"type_id": friend["id"], "person_id": 9999}], [{"type_id": friend["id"], "person_id": ann["id"]}], "Alice", [{"type_id": "1"}]):
        imported.put_json(f"/api/people/{ann['id']}", {"first_name": "Ann", "relations": bad}, status=400)
    # a relation type in use cannot go; its count says how many relations are of it
    assert next(k for k in imported.get("/api/person-relation-types").json if k["name"] == "Mother of")["count"] == 1
    imported.delete(f"/api/person-relation-types/{kinds['Mother of']['id']}", status=409)
    # deleting a person takes their relations, both ways, with them
    imported.delete(f"/api/people/{ann['id']}", status=204)
    assert next(p for p in imported.get("/api/people").json if p["id"] == alice)["related"] == [
        {"type_id": friend["id"], "type": "Pen pal of", "person": {"id": bob, "name": "Bob Buddy"}, "name": "Pen pal of Bob Buddy"},
    ]
    imported.delete(f"/api/person-relation-types/{kinds['Mother of']['id']}", status=204)


def test_groups(imported: webtest.TestApp) -> None:
    people = {p["name"]: p["id"] for p in imported.get("/api/people").json}
    floyd = imported.post_json("/api/groups", {"name": "Pink Floyd", "members": [people["Alice Friend"], people["Bob Buddy"]], "description": "rock band"}, status=201).json
    assert [m["name"] for m in floyd["members"]] == ["Alice Friend", "Bob Buddy"]
    assert floyd["concerts"] == []
    imported.post_json("/api/groups", {"name": "Pink Floyd"}, status=409)
    imported.post_json("/api/groups", {"name": "Other", "members": [9999]}, status=400)
    imported.post_json("/api/groups", {"description": "no name"}, status=400)
    # a concert points to the groups that performed, the user's own only
    band = next(c for c in imported.get("/api/concert-visits").json if c["name"] == "The Band")
    concert = imported.put_json(f"/api/concert-visits/{band['id']}", {"name": "The Band", "date": band["date"], "groups": [floyd["id"]]}).json
    assert concert["groups"] == [{"id": floyd["id"], "name": "Pink Floyd"}]
    imported.put_json(f"/api/concert-visits/{band['id']}", {"name": "The Band", "groups": [9999]}, status=400)
    [listed] = imported.get("/api/groups").json
    assert [c["name"] for c in listed["concerts"]] == ["The Band"]
    # a member leaving keeps the group; deleting the group keeps the concert and the people
    imported.put_json(f"/api/groups/{floyd['id']}", {"name": "Pink Floyd", "members": [people["Bob Buddy"]]})
    assert [m["name"] for m in imported.get("/api/groups").json[0]["members"]] == ["Bob Buddy"]
    assert imported.get("/api/stats").json["groups"] == 1
    imported.delete(f"/api/groups/{floyd['id']}", status=204)
    assert next(c for c in imported.get("/api/concert-visits").json if c["name"] == "The Band")["groups"] == []
    assert "Bob Buddy" in {p["name"] for p in imported.get("/api/people").json}


def test_places(imported: webtest.TestApp) -> None:
    [hall] = imported.get("/api/places").json
    # a place with a country but no city keeps the country in its remark
    assert (hall["name"], hall["city"], hall["remark"], [c["name"] for c in hall["concerts"]]) == (
        "The Hall", None, "In Israel; the city is not known.", ["The Band"],
    )
    # Israel and Tel Aviv came with the import (Acme is there)
    israel = next(c for c in imported.get("/api/countries").json if c["name"] == "Israel")
    tel_aviv = next(c for c in imported.get("/api/cities").json if c["name"] == "Tel Aviv")
    haifa = imported.post_json("/api/cities", {"name": "Haifa", "country_id": israel["id"]}, status=201).json
    barby = imported.post_json("/api/places", {"name": "Barby", "city_id": tel_aviv["id"], "latitude": 32.05, "longitude": 34.76}, status=201).json
    assert (barby["latitude"], barby["concerts"], barby["city"]["name"], barby["city"]["country"]["name"]) == (32.05, [], "Tel Aviv", "Israel")
    # one name once in a city; in another city it is another place
    imported.post_json("/api/places", {"name": "Barby", "city_id": tel_aviv["id"]}, status=409)
    imported.post_json("/api/places", {"name": "Barby", "city_id": haifa["id"]}, status=201)
    imported.post_json("/api/places", {"name": "Barby", "city_id": 9999}, status=400)
    imported.post_json("/api/places", {"city_id": haifa["id"]}, status=400)
    # a concert points to one of the user's own places
    late = next(c for c in imported.get("/api/concert-visits").json if c["name"] == "Late Show")
    moved = imported.put_json(f"/api/concert-visits/{late['id']}", {"name": "Late Show", "date": late["date"], "place_id": barby["id"]}).json
    assert moved["place"] == {"id": barby["id"], "name": "Barby", "city": {"id": tel_aviv["id"], "name": "Tel Aviv", "region": "", "country": {"id": israel["id"], "name": "Israel"}}}
    imported.put_json(f"/api/concert-visits/{late['id']}", {"name": "Late Show", "place_id": 9999}, status=400)
    assert [c["name"] for c in next(p for p in imported.get("/api/places").json if p["id"] == barby["id"])["concerts"]] == ["Late Show"]
    # deleting a place keeps its concerts, with no place
    imported.delete(f"/api/places/{barby['id']}", status=204)
    assert next(c for c in imported.get("/api/concert-visits").json if c["name"] == "Late Show")["place"] is None
    assert imported.get("/api/stats").json["places"] == 2


def test_parsing_locations() -> None:
    assert cities.parse_location("Santa Clara, California, USA (Nvidia)") == ("Santa Clara", "California", "United States of America")
    assert cities.parse_location("Tel Aviv, Israel (Nexxen International; also a New York office)") == ("Tel Aviv", "", "Israel")
    assert cities.parse_location("Palo Alto, California, USA (HP Inc); HPE is in Spring, Texas") == ("Palo Alto", "California", "United States of America")
    assert cities.parse_location("Kibbutz Glil Yam, Herzliya, Israel") == ("Herzliya", "", "Israel")
    assert cities.parse_location("Beersheba area (Kiryat HaTikshuv), Israel") == ("Beersheba", "", "Israel")
    assert cities.parse_location("Maidenhead, UK") == ("Maidenhead", "", "United Kingdom")
    assert cities.parse_location("Gibraltar") == ("Gibraltar", "", "Gibraltar")
    assert cities.parse_location("") is None
    # one city however written, under the better spelling
    assert cities.city_key("Tel-Aviv", "Israel") == cities.city_key("tel aviv", "Israel")
    assert cities.city_key("New York", "USA") == cities.city_key("New York", "United States of America")
    assert cities.better("Ramat Hasharon", "Ramat HaSharon") == "Ramat HaSharon"
    assert cities.better("Tel-Aviv", "Tel Aviv") == "Tel Aviv"


def test_cities_and_countries(imported: webtest.TestApp) -> None:
    cities = {c["name"]: c for c in imported.get("/api/cities").json}
    # the import made them from the text: the museums' Paris, Acme's "Tel Aviv, Israel"
    assert (cities["Paris"]["country"], [m["name"] for m in cities["Paris"]["museums"]]) == (None, ["The Louvre"])
    assert (cities["Tel Aviv"]["country"]["name"], [o["name"] for o in cities["Tel Aviv"]["organizations"]]) == ("Israel", ["Acme"])
    israel = next(c for c in imported.get("/api/countries").json if c["name"] == "Israel")
    assert [c["name"] for c in israel["cities"]] == ["Tel Aviv"]
    # a city is a name in a region of a country once; the user's own countries only
    imported.post_json("/api/cities", {"name": "Tel Aviv", "country_id": israel["id"]}, status=409)
    imported.post_json("/api/cities", {"name": "Portland", "region": "Oregon"}, status=201)
    imported.post_json("/api/cities", {"name": "Portland", "region": "Maine"}, status=201)
    imported.post_json("/api/cities", {"name": "Nowhere", "country_id": 9999}, status=400)
    imported.post_json("/api/countries", {"name": "Israel"}, status=409)
    france = imported.post_json("/api/countries", {"name": "France", "latitude": 46.6, "longitude": 1.9}, status=201).json
    paris = imported.put_json(f"/api/cities/{cities['Paris']['id']}", {"name": "Paris", "country_id": france["id"]}).json
    assert paris["country"] == {"id": france["id"], "name": "France"}
    # an organization keeps its location as written and points to its city
    acme = next(o for o in imported.get("/api/organizations").json if o["name"] == "Acme")
    assert (acme["location"], acme["city"]["name"]) == ("Tel Aviv, Israel", "Tel Aviv")
    # deleting a city keeps what was in it, with no city; deleting a country keeps its cities
    imported.delete(f"/api/countries/{france['id']}", status=204)
    assert next(c for c in imported.get("/api/cities").json if c["name"] == "Paris")["country"] is None
    imported.delete(f"/api/cities/{cities['Paris']['id']}", status=204)
    assert all(m["city"] is None for m in imported.get("/api/museum-visits").json if m["name"] == "The Louvre")
    stats = imported.get("/api/stats").json
    assert (stats["cities"], stats["countries"]) == (len(cities) + 2 - 1, 1)


def test_performers_are_people(imported: webtest.TestApp) -> None:
    concerts = {c["name"]: c for c in imported.get("/api/concert-visits").json}
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
    imported.post_json("/api/concert-visits", {"name": "x", "performers": [999]}, status=400)
    imported.post_json("/api/concert-visits", {"name": "x", "performers": ["Singer"]}, status=400)


def test_museums_share_the_first_visit_photo(imported: webtest.TestApp) -> None:
    museums = imported.get("/api/museum-visits").json
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
    videos = imported.get("/api/youtube-videos").json
    # newest first; the watch history has no dates, so comes after, by name
    assert [v["youtube_id"] for v in videos] == ["5jqXEzplxeo", "VNIRUigPxA8", "-0-EI_f9oXs", "-0dYmE1lyw4"]
    debate, _, chess, gone = videos
    # in both files: one row, with the review and YouTube's details
    assert (debate["review"], debate["channel"], debate["category"], debate["duration"], debate["uploaded"], debate["views"]) == (
        "interesting debate", "OxfordUnion", "News & Politics", 3725, "2015-11-10", 123456)
    assert (chess["name"], chess["date"], chess["review"], chess["unavailable"]) == ("Carlsen Crushes a GM", None, "", False)
    # one YouTube no longer has: only its id, no name, and it can be edited without one
    assert (gone["name"], gone["unavailable"], gone["channel"]) == ("", True, "")
    assert imported.put_json(f"/api/youtube-videos/{gone['id']}", dict(gone, device_id="", rating=5)).json["rating"] == 5
    assert (debate["date"], debate["rating"], debate["watched_at"], debate["device"]["name"]) == ("2015-11-30T16:24:31Z", 7, "Home", "Desktop")
    # the page builds YouTube's URLs from the id
    assert "url" not in debate and "image" not in debate
    # a link pasted in place of the id is taken apart
    added = imported.post_json("/api/youtube-videos", {"name": "Talk", "youtube_id": "https://youtu.be/JbNJoHFsQnc?t=10", "date": "2024-05-01"}, status=201).json
    assert added["youtube_id"] == "JbNJoHFsQnc"
    body = dict(added, device_id="")
    for link in ("https://www.youtube.com/watch?v=JbNJoHFsQnc&list=x", "https://www.youtube.com/shorts/JbNJoHFsQnc", "JbNJoHFsQnc"):
        assert imported.put_json(f"/api/youtube-videos/{added['id']}", dict(body, youtube_id=link)).json["youtube_id"] == "JbNJoHFsQnc"
    # a malformed id, and a video listed twice
    imported.put_json(f"/api/youtube-videos/{added['id']}", dict(body, youtube_id="JbNJoHFsQncS"), status=400)
    imported.post_json("/api/youtube-videos", {"name": "Again", "youtube_id": "5jqXEzplxeo"}, status=409)
    imported.delete(f"/api/youtube-videos/{added['id']}", status=204)
    assert len(imported.get("/api/youtube-videos").json) == 4


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
    small = imported.get("/api/youtube-videos", headers={"Accept-Encoding": "gzip"})
    assert "Accept-Encoding" not in small.headers.get("Vary", "")
    # long: gzipped (WebTest takes the gzip apart again, so what is left to see is the Vary)
    flask_app = imported.app
    assert isinstance(flask_app, flask.Flask)
    flask_app.config["GZIP_MIN_BYTES"] = 10
    zipped = imported.get("/api/youtube-videos", headers={"Accept-Encoding": "gzip"})
    assert "Accept-Encoding" in zipped.headers["Vary"]
    assert len(zipped.json) == 4
    # a client that does not take gzip gets it plain
    assert "Accept-Encoding" not in imported.get("/api/youtube-videos").headers.get("Vary", "")


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


def test_books(imported: webtest.TestApp) -> None:
    books = {b["title"]: b for b in imported.get("/api/library-entries?kind=book").json}
    hobbit, may, chess = books["The Hobbit"], books["Thirty Fifth in May"], books["Chess"]
    # the dated reading gives the rating, the review and the day (in Jerusalem, a day after UTC)
    assert (hobbit["creator"], hobbit["status"], hobbit["rating"], hobbit["finished_on"]) == ("J.R.R. Tolkien", "done", 7, "2004-08-13")
    assert hobbit["notes"] == "Good. Read in English (date unknown); English (2004-08-13). Owned in English"
    assert hobbit["goodreads_id"] == "5907"
    assert imported.get(hobbit["image"]).body == b"\xff\xd8hobbit"
    # text_books.yaml rates a book read with no rating of its own
    assert (may["rating"], may["finished_on"], may["simania_id"]) == (8, None, "7005")
    assert may["notes"] == (
        "nice. Read in Hebrew (date unknown). Written in German. Hebrew title: שלושים וחמישה במאי. "
        "Author in Hebrew: אריך קסטנר. was named: 35 May"
    )
    # owned but not read, with no cover
    assert (chess["status"], chess["creator"], chess["image"]) == ("wishlist", "", None)
    assert chess["notes"] == "Owned in Hebrew. Written in Hebrew"


def test_books_import_adds_once(imported: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    source = write_source(tmp_path / "again")
    [hobbit] = [b for b in imported.get("/api/library-entries?kind=book").json if b["title"] == "The Hobbit"]
    imported.delete(f"/api/library-entries/{hobbit['work_id']}", status=204)
    with Session(engine) as session:
        counts = import_world.import_books(session, owner(session), source)
        session.commit()
    # the deleted one comes back, on the work there already, and its cover is stored again
    assert counts == {
        "books": 1, "books there already": 2, "covers": 1, "covers given to books there already": 0, "books with no cover": 0,
        "authors added": 0, "people made book authors": 0, "authors given to books there already": 0,
    }
    assert len(imported.get("/api/library-entries?kind=book").json) == 3


def test_books_import_adds_a_new_cover(imported: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    source = write_source(tmp_path / "again")
    # the site has a cover for Chess now: running the import again gives it to the entry, and nothing else changes
    (source / "static" / "images" / "book-simania-11971.jpg").write_bytes(b"\xff\xd8chess")
    with Session(engine) as session:
        counts = import_world.import_books(session, owner(session), source)
        session.commit()
    assert counts == {
        "books": 0, "books there already": 3, "covers": 1, "covers given to books there already": 1, "books with no cover": 0,
        "authors added": 0, "people made book authors": 0, "authors given to books there already": 0,
    }
    books = {b["title"]: b for b in imported.get("/api/library-entries?kind=book").json}
    assert imported.get(books["Chess"]["image"]).body == b"\xff\xd8chess"
    assert imported.get(books["The Hobbit"]["image"]).body == b"\xff\xd8hobbit"


def test_book_authors_are_people(imported: webtest.TestApp) -> None:
    books = {b["title"]: b for b in imported.get("/api/library-entries?kind=book").json}
    people = {p["name"]: p for p in imported.get("/api/people").json}
    # each author is a person, a Book Author, linked from the book
    tolkien = people["J.R.R. Tolkien"]
    assert (tolkien["first_name"], tolkien["surname"]) == ("J.R.R.", "Tolkien")
    assert [t["name"] for t in tolkien["types"]] == ["Book Author"]
    assert books["The Hobbit"]["authors"] == [{"id": tolkien["id"], "name": "J.R.R. Tolkien"}]
    assert books["Chess"]["authors"] == []
    # the authors can be set through the API, to the user's own people only
    work_id = books["Chess"]["work_id"]
    entry = imported.put_json(f"/api/library-entries/{work_id}", {"status": "wishlist", "authors": [tolkien["id"]]}).json
    assert [a["name"] for a in entry["authors"]] == ["J.R.R. Tolkien"]
    imported.put_json(f"/api/library-entries/{work_id}", {"status": "wishlist", "authors": [9999]}, status=400)
    # an edit that does not send the authors keeps them
    entry = imported.put_json(f"/api/library-entries/{work_id}", {"status": "done"}).json
    assert [a["name"] for a in entry["authors"]] == ["J.R.R. Tolkien"]


CHESS_WITHOUT_AUTHOR = '        simania_id: "11971"\n    authors: []\n'
CHESS_WITH_AUTHOR = '        simania_id: "11971"\n    authors:\n      - - language: "english"\n          name: "Garry Kasparov"\n'


def test_books_import_adds_a_new_author(imported: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    source = write_source(tmp_path / "again")
    # the yaml names Chess's author now: its work is found by its Simania id, not made again
    assert CHESS_WITHOUT_AUTHOR in BOOKS
    (source / "data" / "yaml" / "books_read.yaml").write_text(BOOKS.replace(CHESS_WITHOUT_AUTHOR, CHESS_WITH_AUTHOR), encoding="UTF8")
    with Session(engine) as session:
        # and entries imported before their authors were people get them
        session.execute(delete(library_entry_authors))
        session.commit()
        counts = import_world.import_books(session, owner(session), source)
        session.commit()
    assert counts == {
        "books": 0, "books there already": 3, "covers": 0, "covers given to books there already": 0, "books with no cover": 0,
        "authors added": 1, "people made book authors": 1, "authors given to books there already": 3,
    }
    books = {b["title"]: b for b in imported.get("/api/library-entries?kind=book").json}
    assert len(books) == 3
    assert (books["Chess"]["creator"], [a["name"] for a in books["Chess"]["authors"]]) == ("Garry Kasparov", ["Garry Kasparov"])
    assert [a["name"] for a in books["The Hobbit"]["authors"]] == ["J.R.R. Tolkien"]
    kasparov = next(p for p in imported.get("/api/people").json if p["name"] == "Garry Kasparov")
    assert [t["name"] for t in kasparov["types"]] == ["Book Author"]


def test_books_unknown_field(engine: Engine, tmp_path: Path, app: webtest.TestApp) -> None:
    sign_in(app)
    source = write_source(tmp_path)
    path = source / "data" / "yaml" / "books_read.yaml"
    path.write_text(BOOKS.replace('        rating: 7', '        rating: 7\n        mood: "happy"'), encoding="UTF8")
    with Session(engine) as session, pytest.raises(import_world.WorldImportError, match=r"a reading of 'The Hobbit' has fields .*mood"):
        import_world.import_books(session, owner(session), source)


def test_people_links_point_at_people(imported: webtest.TestApp) -> None:
    ids = {p["name"]: p["id"] for p in imported.get("/api/people").json}
    for path in ("/api/concert-visits", "/api/museum-visits"):
        for item in imported.get(path).json:
            assert [ids[p["name"]] for p in item["people"]] == [p["id"] for p in item["people"]]


def test_people(imported: webtest.TestApp) -> None:
    people = imported.get("/api/people").json
    # Robert Greenberg is a lecturer of audio_courses.yaml, Erich Kestner and J.R.R. Tolkien authors of books_read.yaml;
    # Alice is the account owner's own person, the one the others are related to
    assert [p["name"] for p in people] == ["Alice", "Alice Friend", "Bob Buddy", "Erich Kestner", "J.R.R. Tolkien", "Robert Greenberg", "Singer", "The Band"]
    me, alice, bob, *_ = people
    assert (me["is_self"], alice["is_self"]) == (True, False)
    assert alice["description"] == "Old friend"
    assert [c["name"] for c in alice["organizations"]] == ["Startup"]
    assert [c["name"] for c in bob["organizations"]] == ["Acme", "Startup"]
    # only the person and their organizations: their concerts and museums are not listed next to them
    assert set(alice) == {"id", "name", "is_self", "honorific", "first_name", "middle_name", "surname", "relations", "related", "types", "organizations", "organization_links", "description"}


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


def test_professions_and_relations(imported: webtest.TestApp) -> None:
    professions = {t["name"]: t for t in imported.get("/api/person-types").json}
    assert sorted(professions) == sorted(import_world.PERSON_TYPES)
    people = {p["name"]: p for p in imported.get("/api/people").json}
    me = people["Alice"]
    # who performed is a Performer (Bob too, who is also a co-worker: one
    # need not choose); Alice and Bob, at organizations, are the user's
    # co-workers: a relation to the user's own person, not a person type
    assert [t["name"] for t in people["Singer"]["types"]] == ["Performer"]
    assert [t["name"] for t in people["Bob Buddy"]["types"]] == ["Performer"]
    assert professions["Performer"]["count"] == 3
    assert people["Alice Friend"]["types"] == []
    assert [r["name"] for r in people["Alice Friend"]["relations"]] == ["Co-worker of Alice"]
    assert sorted(r["name"] for r in me["related"]) == ["Co-worker of Alice Friend", "Co-worker of Bob Buddy"]
    # a person may have several professions, several relations to people and several organizations
    kinds = {k["name"]: k["id"] for k in imported.get("/api/person-relation-types").json}
    organizations = {o["name"]: o["id"] for o in imported.get("/api/organizations").json}
    programmer = imported.post_json("/api/person-types", {"name": "Programmer"}, status=201).json
    alice = people["Alice Friend"]
    edited = imported.put_json(f"/api/people/{alice['id']}", {
        "first_name": "Alice", "surname": "Friend",
        "type_ids": [programmer["id"], professions["Performer"]["id"]],
        "relations": [{"type_id": kinds["Co-worker of"], "person_id": me["id"]}, {"type_id": kinds["Friend of"], "person_id": people["Bob Buddy"]["id"]}],
        "organizations": [organizations["Acme"], organizations["Old School"], organizations["Startup"]],
    }).json
    assert [t["name"] for t in edited["types"]] == ["Performer", "Programmer"]
    assert [r["name"] for r in edited["relations"]] == ["Co-worker of Alice", "Friend of Bob Buddy"]
    assert [o["name"] for o in edited["organizations"]] == ["Acme", "Old School", "Startup"]
    counts = {t["name"]: t["count"] for t in imported.get("/api/person-types").json}
    assert (counts["Programmer"], counts["Performer"]) == (1, 4)
    imported.delete(f"/api/person-types/{programmer['id']}", status=409)
    imported.put_json(f"/api/people/{alice['id']}", {"first_name": "Alice", "type_ids": [9999]}, status=400)
    imported.put_json(f"/api/people/{alice['id']}", {"first_name": "Alice", "type_ids": programmer["id"]}, status=400)
    # taking a profession off frees it for deleting
    imported.put_json(f"/api/people/{alice['id']}", {"first_name": "Alice", "type_ids": []})
    imported.delete(f"/api/person-types/{programmer['id']}", status=204)


def test_person_types_that_are_relations_become_relations(imported: webtest.TestApp, engine: Engine) -> None:
    # a database from before: Friend and Family were person types
    with Session(engine) as session:
        user = owner(session)
        friend = PersonType(owner_id=user.id, name="Friend", description="A friend")
        family = PersonType(owner_id=user.id, name="Family", description="A relative")
        bob = session.scalars(select(Person).where(Person.first_name == "Bob")).one()
        singer = session.scalars(select(Person).where(Person.first_name == "Singer")).one()
        bob.types.append(friend)
        singer.types.append(family)
        session.commit()
        counts = import_world.give_types(session, user)
        session.commit()
    assert (counts["person types made relations"], counts["types added"]) == (2, 0)
    people = {p["name"]: p for p in imported.get("/api/people").json}
    # each is a relation to the user's own person now, and the types are gone; a profession stays
    assert sorted(r["name"] for r in people["Bob Buddy"]["relations"]) == ["Co-worker of Alice", "Friend of Alice"]
    assert ([t["name"] for t in people["Singer"]["types"]], [r["name"] for r in people["Singer"]["relations"]]) == (["Performer"], ["Relative of Alice"])
    assert sorted(t["name"] for t in imported.get("/api/person-types").json) == sorted(import_world.PERSON_TYPES)
    # running it again changes nothing
    with Session(engine) as session:
        again = import_world.give_types(session, owner(session))
    assert again == {"types added": 0, "organizations given a type": 0, "people given a profession": 0, "people given a relation": 0, "person types made relations": 0}


def test_split_name() -> None:
    assert import_world.split_name("Doron Veltzer") == ("", "Doron", "", "Veltzer")
    assert import_world.split_name("Yaron Ben-Ami") == ("", "Yaron", "", "Ben-Ami")
    assert import_world.split_name("Jeffrey L. Kasser") == ("", "Jeffrey", "L.", "Kasser")
    assert import_world.split_name("John Ronald Reuel Tolkien") == ("", "John", "Ronald Reuel", "Tolkien")
    assert import_world.split_name('Jeff "Tain" Watts') == ("", "Jeff", '"Tain"', "Watts")
    # a surname of two words is hyphenated
    assert import_world.split_name("Al Di Meola") == ("", "Al", "", "Di-Meola")
    assert import_world.split_name("Marcus du Sautoy") == ("", "Marcus", "", "du-Sautoy")
    # what is not plainly a person's name stays whole, for the people-names check
    assert import_world.split_name("Oded from MAFAT") == ("", "Oded from MAFAT", "", "")
    assert import_world.split_name("The Band") == ("", "The Band", "", "")
    assert import_world.split_name("Mads Vinding Trio") == ("", "Mads Vinding Trio", "", "")
    assert import_world.split_name("Barak (bass)") == ("", "Barak (bass)", "", "")
    # a title before the name is its honorific
    assert import_world.split_name("Sir Arthur Conan Doyle") == ("Sir", "Arthur", "Conan", "Doyle")
    assert import_world.split_name("Dr. Who") == ("Dr.", "Who", "", "")
    assert import_world.split_name("Marmir") == ("", "Marmir", "", "")


def test_tidy_names() -> None:
    # names already in a database, made to follow the rules where it is plain how
    assert names.tidy("", "Kiti", "", "Silveira Basso") == ("", "Kiti", "", "Silveira-Basso")
    assert names.tidy("", "Douglass", "", "R. Hofstaddter") == ("", "Douglass", "R.", "Hofstaddter")
    assert names.tidy("", "Richard P. Feynman", "", "") == ("", "Richard", "P.", "Feynman")
    assert names.tidy("", "Mary Ann", "Lou", "Smith") == ("", "Mary", "Ann Lou", "Smith")
    assert names.tidy("", "Open stage", "", "") == ("", "Open stage", "", "")
    assert names.tidy("", "Sir Arthur Conan Doyle", "", "") == ("Sir", "Arthur", "Conan", "Doyle")
    assert names.tidy("Dr.", "Dana", "", "Cohen") == ("Dr.", "Dana", "", "Cohen")
    assert names.tidy("", "Dana", "", "Cohen") == ("", "Dana", "", "Cohen")
    # people are matched however a name is spaced or hyphenated
    assert names.key("Al Di Meola") == names.key("Al  di-meola")


def test_names_are_one_word_each(imported: webtest.TestApp) -> None:
    person = imported.post_json("/api/people", {"first_name": "John", "middle_name": " Ronald  Reuel ", "surname": "Tolkien"}, status=201).json
    assert (person["middle_name"], person["name"]) == ("Ronald Reuel", "John Ronald Reuel Tolkien")
    imported.post_json("/api/people", {"first_name": "Mary Ann", "surname": "Smith"}, status=400)
    imported.post_json("/api/people", {"first_name": "Al", "surname": "Di Meola"}, status=400)
    assert imported.post_json("/api/people", {"first_name": "Al", "surname": "Di-Meola"}, status=201).json["name"] == "Al Di-Meola"
    # an honorific, one word, comes first in the name; empty unless given
    assert person["honorific"] == ""
    doctor = imported.post_json("/api/people", {"honorific": "Dr.", "first_name": "Dana", "surname": "Cohen"}, status=201).json
    assert (doctor["honorific"], doctor["name"]) == ("Dr.", "Dr. Dana Cohen")
    imported.post_json("/api/people", {"honorific": "Dr. Prof.", "first_name": "Dana"}, status=400)
    # a middle name alone is a name
    assert imported.post_json("/api/people", {"middle_name": "Lou"}, status=201).json["name"] == "Lou"


def test_people_may_share_a_name(imported: webtest.TestApp) -> None:
    first = imported.post_json("/api/people", {"first_name": "Dana", "surname": "Cohen", "description": "School"}, status=201).json
    second = imported.post_json("/api/people", {"first_name": "Dana", "surname": "Cohen", "description": "Work"}, status=201).json
    assert first["id"] != second["id"]
    danas = [p for p in imported.get("/api/people").json if p["name"] == "Dana Cohen"]
    assert [p["description"] for p in danas] == ["School", "Work"]


def test_guessing_professions_and_relations() -> None:
    def person(name: str, description: str = "") -> Person:
        honorific, first_name, middle_name, surname = import_world.split_name(name)
        return Person(honorific=honorific, first_name=first_name, middle_name=middle_name, surname=surname, description=description)
    assert import_world._relation_to_user(person("Doron Veltzer")) == "Relative of"
    assert import_world._relation_to_user(person("X", "My brother")) == "Relative of"
    assert import_world._relation_to_user(person("X", "My brothers ex-girlfriend")) is None
    assert import_world._relation_to_user(person("X", "Ex-girlfriend")) == "Girlfriend of"
    assert import_world._relation_to_user(person("X", "Yaron's girlfriend")) is None
    assert import_world._relation_to_user(person("X", "Physics guy from MAFAT")) == "Co-worker of"
    assert import_world._profession(person("X")) is None


def test_give_types_fills_only_what_is_missing(imported: webtest.TestApp, engine: Engine) -> None:
    with Session(engine) as session:
        session.execute(update(Organization).values(type_id=None))
        session.execute(delete(OrganizationType).where(OrganizationType.name == "Military"))
        session.commit()
        counts = import_world.give_types(session, owner(session))
        session.commit()
    assert counts == {"types added": 1, "organizations given a type": 3, "people given a profession": 0, "people given a relation": 0, "person types made relations": 0}
    by_name = {o["name"]: o["type"]["name"] for o in imported.get("/api/organizations").json}
    # Old School's type came from the YAML, which this does not read: it gets the default
    assert by_name == {"Acme": "Company", "Old School": "Company", "Startup": "Company"}
    with Session(engine) as session:
        assert import_world.give_types(session, owner(session)) == {
            "types added": 0, "organizations given a type": 0, "people given a profession": 0, "people given a relation": 0, "person types made relations": 0,
        }


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
    url = imported.get("/api/concert-visits").json[0]["image"]
    response = imported.get(url)
    assert response.content_type == "image/jpeg"
    assert response.body == b"\xff\xd8band"
    assert response.etag is not None
    assert "private" in response.headers["Cache-Control"]
    imported.get(url, headers={"If-None-Match": f'"{response.etag}"'}, status=304)


def test_other_users_see_nothing(imported: webtest.TestApp, engine: Engine) -> None:
    url = imported.get("/api/concert-visits").json[0]["image"]
    imported.post("/auth/logout")
    sign_in(imported, sub="someone-else")
    assert imported.get("/api/concert-visits").json == []
    assert imported.get("/api/museum-visits").json == []
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
        for model, count in ((Concert, 3), (Museum, 3), (AudioCourse, 2), (Person, 8), (Organization, 3), (Image, 7)):
            assert session.scalar(select(func.count()).select_from(model)) == count
        assert session.scalar(select(func.count()).select_from(concert_companions)) == 3
        assert session.scalar(select(func.count()).select_from(person_organizations)) == 3
    assert len(imported.get("/api/concert-visits").json) == 3


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
    concert = imported.post_json("/api/concert-visits", {
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
    assert "New Show" in [c["name"] for c in imported.get("/api/concert-visits").json]


def test_add_validates(imported: webtest.TestApp) -> None:
    imported.post_json("/api/concert-visits", {"name": ""}, status=400)
    imported.post_json("/api/concert-visits", {"name": "x", "date": "2024-13"}, status=400)
    imported.post_json("/api/concert-visits", {"name": "x", "date": "last year"}, status=400)
    imported.post_json("/api/concert-visits", {"name": "x", "date_timezone": "Mars/Olympus"}, status=400)
    imported.post_json("/api/concert-visits", {"name": "x", "people": [999]}, status=400)
    imported.post_json("/api/museum-visits", {"name": "x", "rating": 11}, status=400)
    imported.post_json("/api/museum-visits", {"name": "x", "latitude": 91, "longitude": 0}, status=400)
    imported.post_json("/api/museum-visits", {"name": "x", "latitude": "north", "longitude": 0}, status=400)
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
    concert = imported.post_json("/api/concert-visits", {"name": "x", "people": [guide["id"]]}, status=201).json
    assert concert["with"] == ["the guide at the Louvre"]
    imported.put_json(f"/api/people/{guide['id']}", {"description": " "}, status=400)


def test_add_museum_and_person(imported: webtest.TestApp) -> None:
    person = imported.post_json("/api/people", {"first_name": "Carol", "description": "Zed"}, status=201).json
    museum = imported.post_json("/api/museum-visits", {
        "name": "Prado", "date": "2012", "rating": 9, "people": [person["id"]],
    }, status=201).json
    assert museum["date"] == "2012"
    assert museum["with"] == ["Carol"]
    assert museum["image"] is None


def test_museum_alone(imported: webtest.TestApp) -> None:
    alone = imported.post_json("/api/museum-visits", {"name": "Prado", "alone": True}, status=201).json
    assert alone["alone"] is True
    assert alone["with"] == []
    assert imported.post_json("/api/museum-visits", {"name": "Tate"}, status=201).json["alone"] is False
    # alone with company is a contradiction
    person = imported.post_json("/api/people", {"first_name": "Carol"}, status=201).json
    imported.post_json("/api/museum-visits", {"name": "Uffizi", "alone": True, "people": [person["id"]]}, status=400)


def test_addresses_and_coordinates(imported: webtest.TestApp) -> None:
    museum = imported.post_json("/api/museum-visits", {
        "name": "Prado", "address": "Calle de Ruiz de Alarcón 23, Madrid, Spain", "latitude": "40.4138", "longitude": -3.6921,
    }, status=201).json
    assert (museum["address"], museum["latitude"], museum["longitude"]) == ("Calle de Ruiz de Alarcón 23, Madrid, Spain", 40.4138, -3.6921)
    # a dialog with the coordinates cleared leaves the place off the map
    cleared = imported.put_json(f"/api/museum-visits/{museum['id']}", dict(museum, people=[], latitude="", longitude="")).json
    assert (cleared["latitude"], cleared["longitude"]) == (None, None)
    organization = imported.post_json("/api/organizations", {"name": "Glil", "address": "Kibbutz Glil Yam, Israel", "latitude": 32.15556, "longitude": 34.82361}, status=201).json
    assert (organization["latitude"], organization["longitude"]) == (32.15556, 34.82361)


def test_edit_keeps_a_timestamp_sent_back_unchanged(imported: webtest.TestApp) -> None:
    late = next(c for c in imported.get("/api/concert-visits").json if c["name"] == "Late Show")
    body = dict(late, name="Late Late Show", people=[p["id"] for p in late["people"]][:1], performers=[p["id"] for p in late["performers"]])
    edited = imported.put_json(f"/api/concert-visits/{late['id']}", body).json
    assert edited["name"] == "Late Late Show"
    assert edited["date"] == "2020-01-01T22:30:00Z"
    assert edited["with"] == ["Alice Friend"]
    # the photo stays when no new one is uploaded
    assert edited["image"] == late["image"]
    edited = imported.put_json(f"/api/concert-visits/{late['id']}", dict(body, date="2020-01-02")).json
    assert edited["date"] == "2020-01-02"
    assert edited["date_precision"] == "day"


def test_edit_person(imported: webtest.TestApp) -> None:
    ids = people_ids(imported)
    bob = imported.put_json(f"/api/people/{ids['Bob Buddy']}", {"first_name": "Robert", "surname": "Buddy", "description": "x"}).json
    assert bob["name"] == "Robert Buddy"
    assert (bob["first_name"], bob["surname"]) == ("Robert", "Buddy")
    louvre = next(m for m in imported.get("/api/museum-visits").json if m["with"])
    assert louvre["with"] == ["Robert Buddy"]
    # no organizations sent: the links stay as they were, as relations do
    assert [o["name"] for o in bob["organizations"]] == ["Acme", "Startup"]


def organization_ids(app: webtest.TestApp) -> dict[str, int]:
    return {c["name"]: c["id"] for c in app.get("/api/organizations").json}


def test_kinds_of_links_to_organizations(imported: webtest.TestApp) -> None:
    kinds = {k["name"]: k for k in imported.get("/api/person-organization-types").json}
    # the import starts the user with the kinds; people.yaml's organizations are where people worked
    assert sorted(kinds) == sorted(import_world.PERSON_ORGANIZATION_TYPES)
    organizations = organization_ids(imported)
    bob = next(p for p in imported.get("/api/people").json if p["name"] == "Bob Buddy")
    assert [link["name"] for link in bob["organization_links"]] == ["Worked at Acme", "Worked at Startup"]
    # the same organization twice, by two kinds; and several organizations
    edited = imported.put_json(f"/api/people/{bob['id']}", {"first_name": "Bob", "surname": "Buddy", "organization_links": [
        {"type_id": kinds["Studied at"]["id"], "organization_id": organizations["Old School"]},
        {"type_id": kinds["Taught at"]["id"], "organization_id": organizations["Old School"]},
        {"type_id": kinds["Worked at"]["id"], "organization_id": organizations["Acme"]},
    ]}).json
    assert sorted(link["name"] for link in edited["organization_links"]) == ["Studied at Old School", "Taught at Old School", "Worked at Acme"]
    assert [o["name"] for o in edited["organizations"]] == ["Acme", "Old School"]
    school = next(o for o in imported.get("/api/organizations").json if o["name"] == "Old School")
    assert [p["name"] for p in school["people"]] == ["Bob Buddy"]
    assert [link["name"] for link in school["person_links"]] == ["Bob Buddy (Studied at)", "Bob Buddy (Taught at)"]
    # the user's own kinds and organizations only
    for bad in ([{"type_id": 9999, "organization_id": organizations["Acme"]}], [{"type_id": kinds["Founded"]["id"], "organization_id": 9999}], "Acme", [{"type_id": "1"}]):
        imported.put_json(f"/api/people/{bob['id']}", {"first_name": "Bob", "organization_links": bad}, status=400)
    # a kind in use cannot go; its count says how many links are of it
    assert next(k for k in imported.get("/api/person-organization-types").json if k["name"] == "Studied at")["count"] == 1
    imported.delete(f"/api/person-organization-types/{kinds['Studied at']['id']}", status=409)
    imported.delete(f"/api/person-organization-types/{kinds['Founded']['id']}", status=204)


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
    assert all("Alice Friend" not in c["with"] for c in imported.get("/api/concert-visits").json)
    for concert in imported.get("/api/concert-visits").json:
        imported.delete(f"/api/concert-visits/{concert['id']}", status=204)
    assert imported.get("/api/concert-visits").json == []
    with Session(engine) as session:
        # the concert photo went with its last concert; the museum one stays
        assert sorted(session.scalars(select(Image.filename)).all()) == ["acme.svg", "audiocourse-gc-337.jpg", "audiocourse-internal-1.jpg", "book-goodreads-5907.jpg", "book-simania-7005.jpg", "museum-15.jpg"]
        assert session.scalar(select(func.count()).select_from(concert_companions)) == 0
    imported.delete("/api/concert-visits/1", status=404)


def test_edit_replaces_photo_and_drops_the_old_one(imported: webtest.TestApp, engine: Engine) -> None:
    upload = imported.post("/api/images", upload_files=[("file", "new.jpg", JPEG)]).json
    for concert in imported.get("/api/concert-visits").json:
        if concert["image"]:
            imported.put_json(f"/api/concert-visits/{concert['id']}", dict(concert, image_id=upload["id"], people=[], performers=[]))
    with Session(engine) as session:
        assert "concert-the-band.jpg" not in session.scalars(select(Image.filename)).all()


def test_others_cannot_touch(imported: webtest.TestApp) -> None:
    concert = imported.get("/api/concert-visits").json[0]
    alice = people_ids(imported)["Alice Friend"]
    imported.post("/auth/logout")
    sign_in(imported, sub="someone-else")
    imported.put_json(f"/api/concert-visits/{concert['id']}", {"name": "mine now"}, status=404)
    imported.delete(f"/api/concert-visits/{concert['id']}", status=404)
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
    imported.post_json("/api/concert-visits", {"name": "x", "people": [alice]}, status=400)


# ─── stats ───────────────────────────────────────────────────────────────────

def test_stats(imported: webtest.TestApp) -> None:
    imported.post_json("/api/library-entries", {"kind": "book", "title": "Dune", "status": "done"}, status=201)
    stats = imported.get("/api/stats").json
    assert (stats["concerts"], stats["museum_visits"], stats["museums"], stats["audio_courses"]) == (3, 3, 2, 2)
    assert (stats["people"], stats["organizations"], stats["images"]) == (8, 3, 7)
    assert (stats["organization_types"], stats["person_types"]) == (7, 3)
    # Bob, Singer and The Band performed; Bob also went with the user, he counts once
    assert stats["performers"] == 3
    books = next(k for k in stats["library"] if k["kind"] == "book")
    # Dune and the three imported books
    assert books["total"] == 4
    assert books["by_status"] == {"Done": 3, "Want to": 1}
    assert {t["name"]: t["count"] for t in stats["people_by_type"]} == {"Performer": 3, "Book Author": 2, "Lecturer": 1, "No profession": 2}
    assert {t["name"]: t["count"] for t in stats["organizations_by_type"]} == {"Company": 2, "University": 1}
    assert stats["concerts_by_year"] == [{"year": 1989, "count": 1}, {"year": 2001, "count": 1}, {"year": 2020, "count": 1}]
    assert stats["museums_by_year"] == [{"year": 2010, "count": 2}, {"year": 2011, "count": 1}]


def test_stats_are_per_user(imported: webtest.TestApp) -> None:
    imported.post("/auth/logout")
    sign_in(imported, sub="someone-else")
    stats = imported.get("/api/stats").json
    assert (stats["concerts"], stats["people"], stats["images"], stats["performers"]) == (0, 0, 0, 0)
    assert stats["concerts_by_year"] == []
