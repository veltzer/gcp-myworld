"""
The concerts, museums, people and organizations: the import script and the API.
"""

import datetime
import gzip
import json
from pathlib import Path
from typing import Any

import fetch_book_details
import fix_languages
import flask
import import_world
import link_authors
import owned_from_notes
import pytest
import tidy_book_notes
import webtest
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from myworld import addresses, checks, cities, languages, names, notes
from myworld.models import (
    SEED_LOCALES,
    AudioBook,
    AudioCourse,
    Concert,
    Cover,
    Image,
    Locale,
    Organization,
    OrganizationType,
    Person,
    PersonName,
    PersonType,
    Place,
    Podcast,
    PodcastEpisode,
    Read,
    User,
    UserWork,
    Visit,
    Work,
    WorkTitle,
    YouTubeVideo,
    concert_companions,
    library_entry_authors,
    person_organizations,
)
from tests.conftest import sign_in, sign_in_admin

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


AUDIBLE = """
items:
  - asin: "0063005409"
    title: "Making Sense"
    subtitle: "Conversations on Consciousness"
    authors: "Sam Harris"
    narrators: "Sam Harris, David Chalmers"
    series_title: ""
    series_sequence: ""
    genres: ["Psychology", "Science", "Psychology"]
    runtime_length_min: "1346"
    is_finished: true
    percent_complete: "0.0"
    rating: "4.7"
    num_ratings: "592"
    date_added: "2021-08-10T08:55:06.867Z"
    release_date: "2020-08-11"
    cover_url: "https://m.media-amazon.com/images/I/x.jpg"
    purchase_date: "2021-08-11T00:00:00Z"
  - asin: "B07D23CFGR"
    title: "Political Order and Political Decay"
    subtitle: ""
    authors: "Francis Fukuyama"
    narrators: "Jonathan Davis"
    series_title: "Political Order"
    series_sequence: "2"
    genres: ["History"]
    runtime_length_min: ""
    is_finished: false
    percent_complete: "12.5"
    rating: ""
    num_ratings: ""
    date_added: "2022-01-02T10:00:00Z"
    release_date: ""
    cover_url: ""
    purchase_date: "2022-01-02T10:00:00Z"
"""


AUDIO_BOOKS = """
items:
  - name: "Letter to a Christian Nation"
    authors:
      - "Sam Harris"
    date_utcz: "2016-05-01T21:33:15Z"
    date_timezone: "Asia/Jerusalem"
    location: "Night Walks"
    device: "Samsung S7"
  - name: "Heretic"
    authors:
      - "Ayaan Hirsi Ali"
      - "A. N. Other"
    date_started_utcz: "2022-08-20T12:28:35Z"
    date_timezone: "Asia/Jerusalem"
    location: "Home"
    device: "Desktop"
    progress: "did part03"
"""


PODCASTS = """
items:
  - name: "The rest is history"
    url: "https://therestishistory.com/club"
    rss_feed: "https://feeds.megaphone.fm/GLT4787413333"
    chapters:
      - title: "Trailer"
        description: "Hosted by historians Tom Holland and Dominic Sandbrook"
        pubDate: "Wed, 28 Oct 2020 13:00:00 -0000"
        episode: 1
        duration: 286
        episodeType: "trailer"
        explicit: "no"
        enclosure_url: "https://pdst.fm/e/trailer.mp3"
        author: "Goalhanger"
        guid: "a428c3fa"
        date_utcz: "2026-03-22T13:24:50Z"
        date_timezone: "Asia/Jerusalem"
        location: "Night Walks"
        device: "Samsung S25"
      - title: "1. Greatness"
        description: "How did certain people come to be called the Great?"
        pubDate: "Mon, 02 Nov 2020 04:00:00 +0200"
        episode: 1
        duration: 1975
        episodeType: "full"
        explicit: "yes"
        enclosure_url: "https://pdst.fm/e/greatness.mp3"
        image: "https://megaphone.imgix.net/greatness.jpg"
        author: "Goalhanger"
        guid: "d64331b9"
        date_utcz: "2026-03-27T10:00:00Z"
        date_timezone: "Asia/Jerusalem"
        location: "Night Walks"
        device: "Samsung S25"
    rating: 7
    review: "So-so podcast"
    internal_id: 1
  - name: "Mindscape"
    url: "https://podcasts.apple.com/us/podcast/mindscape/id1406534739"
    rss_feed: "https://rss.libsyn.com/shows/604590/destinations/5264190.xml"
    chapters:
      - title: "Welcome to the Mindscape Podcast!"
        description: "Welcome"
        pubDate: "Mon, 02 Jul 2018 05:00:00 +0000"
        duration: 120
        episodeType: "full"
        explicit: "false"
        enclosure_url: "https://traffic.libsyn.com/welcome.mp3"
        image: "https://ssl-static.libsyn.com/welcome.jpg"
        guid: "e7b5a1d2"
        date_utcz: "2026-03-27T09:00:00Z"
        date_timezone: "Asia/Jerusalem"
        device: "Samsung S25"
    rating: 8
    review: "A very good podcast"
    internal_id: 2
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
    for name, text in (("people", PEOPLE), ("concerts", concerts), ("museums", MUSEUMS), ("organizations", ORGANIZATIONS), ("audio_courses", AUDIO_COURSES), ("audible", AUDIBLE), ("audio_books", AUDIO_BOOKS), ("podcasts", PODCASTS), ("video_youtube", YOUTUBE), ("books_read", BOOKS), ("text_books", TEXT_BOOKS)):
        (root / "data" / "yaml" / f"{name}.yaml").write_text(text, encoding="UTF8")
    (root / "data" / "logos" / "acme.svg").write_bytes(LOGO)
    (root / "static" / "data").mkdir(parents=True)
    with gzip.open(root / "static" / "data" / "youtube.json.gz", "wt", encoding="UTF8") as fp:
        json.dump(YOUTUBE_HISTORY, fp)
    (root / "static" / "images" / "concert-the-band.jpg").write_bytes(b"\xff\xd8band")
    (root / "static" / "images" / "museum-15.jpg").write_bytes(b"\xff\xd8louvre")
    (root / "static" / "images" / "audiocourse-gc-337.jpg").write_bytes(b"\xff\xd8greeks")
    (root / "static" / "images" / "audiocourse-internal-1.jpg").write_bytes(b"\xff\xd8music")
    # the second book has no cover: it is added without one
    (root / "static" / "images" / "audible-0063005409.jpg").write_bytes(b"\xff\xd8sense")
    # the second podcast has no cover: it is added without one
    (root / "static" / "images" / "podcast-1.jpg").write_bytes(b"\xff\xd8history")
    (root / "static" / "images" / "book-goodreads-5907.jpg").write_bytes(b"\xff\xd8hobbit")
    (root / "static" / "images" / "book-simania-7005.jpg").write_bytes(b"\xff\xd8may")
    return root


def owner(session: Session, email: str = "alice@example.com") -> User:
    return import_world.find_owner(session, email, None)


@pytest.fixture(name="imported")
def fixture_imported(app: webtest.TestApp, engine: Engine, tmp_path: Path) -> webtest.TestApp:
    # an admin: what the import adds to what everyone shares (cities, places), the tests change too
    sign_in_admin(app, engine)
    with Session(engine) as session:
        counts = import_world.import_world(session, owner(session), write_source(tmp_path))
        session.commit()
    assert counts == {
        "people": 7, "organizations": 3, "organization types": 7, "relation types": 6, "person types": 3, "people with a profession": 4, "people related to the user": 2,
        "concerts": 3, "places": 1, "museums": 2, "museum visits": 3, "audio courses": 2, "audio books": 4, "podcasts": 2, "podcast episodes": 3,
        "YouTube videos": 4, "devices": 4, "books": 3, "images": 9}
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
    # the concert's place, a concert venue, and the museums, places of the kind Museum
    places = {p["name"]: p for p in imported.get("/api/places").json}
    assert sorted(places) == ["No Photo Museum", "The Hall", "The Louvre"]
    hall = places["The Hall"]
    assert (hall["city"], [k["name"] for k in hall["kinds"]], [c["name"] for c in hall["concerts"]]) == (None, ["Concert venue"], ["The Band"])
    assert [k["name"] for k in places["The Louvre"]["kinds"]] == ["Museum"]
    # a place with a country but no city: the concert says the country (a shared place has no remark)
    band = next(c for c in imported.get("/api/concert-visits").json if c["name"] == "The Band")
    assert band["remark"].endswith("About the place: in Israel; the city is not known.")
    # Israel and Tel Aviv came with the import (Acme is there)
    israel = next(c for c in imported.get("/api/countries").json if c["name"] == "Israel")
    tel_aviv = next(c for c in imported.get("/api/cities").json if c["name"] == "Tel Aviv")
    haifa = imported.post_json("/api/cities", {"name": "Haifa", "country_id": israel["id"]}, status=201).json
    barby = imported.post_json("/api/places", {"name": "Barby", "city_id": tel_aviv["id"], "latitude": 32.05, "longitude": 34.76}, status=201).json
    assert (barby["latitude"], barby["concerts"], barby["city"]["name"], barby["city"]["country"]["name"]) == (32.05, [], "Tel Aviv", "Israel")
    # a place has a photo, with its credit
    upload = imported.post("/api/images", upload_files=[("file", "barby.jpg", JPEG)]).json
    assert barby["image"] is None
    pictured = imported.put_json(f"/api/places/{barby['id']}", {"name": "Barby", "city_id": tel_aviv["id"], "image_id": upload["id"], "image_license": "CC0"}).json
    assert (pictured["image"], pictured["image_license"]) == (f"/api/images/{upload['id']}", "CC0")
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
    # the hall, the two museums and Haifa's Barby
    assert imported.get("/api/stats").json["places"] == 4


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


def test_splitting_addresses() -> None:
    # the city carries the region and the country: they are left out, the postcode found anywhere
    assert addresses.split_text("23 Kaplan St., HaKirya, Tel Aviv 6473424, Israel", "Tel Aviv", "", "Israel") == ("23 Kaplan St.", "HaKirya", "6473424", True)
    assert addresses.split_text("131 West 3rd Street, New York, NY 10012, USA", "New York", "New York", "United States of America") == ("131 West 3rd Street", "", "10012", True)
    # a building and its floor before the street stay in the street line; a postcode written its own way is found
    assert addresses.split_text("Atrium Tower, 18th Floor, 2 Jabotinsky St., Ramat Gan 5250501, Israel", "Ramat Gan", "", "Israel") == (
        "Atrium Tower, 18th Floor, 2 Jabotinsky St.", "", "5250501", True,
    )
    assert addresses.parse_address("Bangårdsgatan 8, 753 20 Uppsala, Sweden")["city"] == "Uppsala"
    assert addresses.parse_address("Bangårdsgatan 8, 753 20 Uppsala, Sweden")["postcode"] == "753 20"
    # the city is the one the user has, even with a county after it (kept as written: "whole" is False)
    redhill = addresses.parse_address("3rd Floor, Forum House, 41-51 Brighton Road, Redhill, Surrey RH1 6YS, United Kingdom", {cities.city_key("Redhill", "")[0]})
    assert (redhill["street"], redhill["city"], redhill["postcode"], redhill["whole"]) == ("3rd Floor, Forum House, 41-51 Brighton Road", "Redhill", "RH1 6YS", False)
    assert addresses.split_text("Rue de Rivoli, 75001 Paris, France", "Paris", "", "France") == ("Rue de Rivoli", "", "75001", True)
    assert addresses.split_text("1-2-3 Ginza, Chuo-ku, Tokyo, Japan", "Tokyo", "", "Japan") == ("1-2-3 Ginza", "Chuo-ku", "", True)
    # more than the parts hold is said, so the caller keeps the text
    assert addresses.split_text("Infinity Park (7 HaPnina St.), Ra'anana, Israel", "Ra'anana", "", "Israel")[3] is False
    # a city that is its country: every part is the address
    assert addresses.split_text("Floor 3, Tower 2, Harbour View, 18 Harbour Road, Hong Kong", "Hong Kong", "", "Hong Kong") == (
        "Floor 3, Tower 2, Harbour View, 18 Harbour Road", "", "", True,
    )
    # the street in the country's order, from OpenStreetMap's parts
    assert addresses.from_osm({"road": "Ibn Gabirol", "house_number": "30", "suburb": "Sarona", "postcode": "6473424"}, "Israel") == ("Ibn Gabirol 30", "Sarona", "6473424")
    assert addresses.from_osm({"road": "7th Avenue South", "house_number": "88", "neighbourhood": "West Village"}, "United States of America") == ("88 7th Avenue South", "West Village", "")
    assert addresses.compose("Ibn Gabirol 30", "Sarona", "Tel Aviv", "6473424", "Israel") == "Ibn Gabirol 30, Sarona, Tel Aviv 6473424, Israel"
    assert addresses.compose("", "", "Mishmarot", "", "Israel") == "Mishmarot, Israel"


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
    # an organization keeps its location as written and points to its headquarters' city (and, with no address, its city)
    acme = next(o for o in imported.get("/api/organizations").json if o["name"] == "Acme")
    assert (acme["location"], acme["city"]["name"], acme["headquarters"]["name"]) == ("Tel Aviv, Israel", "Tel Aviv", "Tel Aviv")
    assert [o["name"] for o in next(c for c in imported.get("/api/cities").json if c["name"] == "Tel Aviv")["headquarters_of"]] == ["Acme"]
    # the office's city and the headquarters' are set apart
    moved = imported.put_json(f"/api/organizations/{acme['id']}", dict(acme, city_id=paris["id"], headquarters_id=cities["Tel Aviv"]["id"], relation_ids=[])).json
    assert (moved["city"]["name"], moved["headquarters"]["name"]) == ("Paris", "Tel Aviv")
    imported.put_json(f"/api/organizations/{acme['id']}", dict(acme, headquarters_id=9999, relation_ids=[]), status=400)
    imported.put_json(f"/api/organizations/{acme['id']}", dict(acme, city_id=cities["Tel Aviv"]["id"], headquarters_id=cities["Tel Aviv"]["id"], relation_ids=[]))
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


def test_a_museum_has_its_visits(imported: webtest.TestApp) -> None:
    # a museum visited twice is one museum, with the photo of its first visit and both visits, the latest first
    museums = imported.get("/api/museum-visits").json
    assert [(m["name"], len(m["visits"])) for m in museums] == [("No Photo Museum", 1), ("The Louvre", 2)]
    assert museums[0]["image"] is None
    louvre = museums[1]
    assert louvre["image"] is not None
    first = louvre["visits"][1]
    assert (first["rating"], first["with"]) == (9, ["Bob Buddy"])
    # the museum goes by its latest visit, and by everyone it was ever visited with
    assert (louvre["date"], louvre["date_sort"]) == (louvre["visits"][0]["date"], louvre["visits"][0]["date_sort"])
    assert [p["name"] for p in louvre["people"]] == ["Bob Buddy"]
    # a visit is added, one is changed and one taken away: sent, visits are all of them
    kept = dict(first, people=[p["id"] for p in first["people"]], rating=10)
    changed = imported.put_json(f"/api/museum-visits/{louvre['id']}", {"visits": [kept, {"date": "2024-03", "alone": True, "review": "crowded"}]}).json
    assert [(v["date"], v["rating"], v["alone"], v["review"] == "crowded") for v in changed["visits"]] == [("2024-03", None, True, True), (first["date"], 10, False, False)]
    assert changed["visits"][1]["id"] == first["id"] and changed["rating"] == 10
    # visits are what is sent; a visit of another museum, or one sent twice, is no visit of this one
    imported.put_json(f"/api/museum-visits/{louvre['id']}", {}, status=400)
    imported.put_json(f"/api/museum-visits/{louvre['id']}", {"visits": [{"id": museums[0]["visits"][0]["id"]}]}, status=400)
    imported.put_json(f"/api/museum-visits/{louvre['id']}", {"visits": [{"id": first["id"]}, {"id": first["id"]}]}, status=400)
    # a museum is in the user's Museum visits once: adding visits to it again is refused (they are added to it)
    imported.post_json("/api/museum-visits", {"place_id": louvre["id"], "visits": [{}]}, status=409)
    # the museum itself is shared: what is sent of it is not the user's to change
    again = [dict(v, people=[p["id"] for p in v["people"]]) for v in changed["visits"]]
    renamed = imported.put_json(f"/api/museum-visits/{louvre['id']}", {"name": "Le Louvre", "visits": again}).json
    assert renamed["name"] == "The Louvre"
    # its visits taken away, it leaves the user's Museum visits, and stays a place, everyone's
    imported.put_json(f"/api/museum-visits/{louvre['id']}", {"visits": []})
    assert [m["name"] for m in imported.get("/api/museum-visits").json] == ["No Photo Museum"]
    assert "The Louvre" in [p["name"] for p in imported.get("/api/places").json]
    stats = imported.get("/api/stats").json
    assert (stats["museums"], stats["museum_visits"]) == (1, 1)
    # and deleting a museum from Museums deletes the user's visits only
    imported.delete(f"/api/museum-visits/{museums[0]['id']}", status=204)
    assert imported.get("/api/museum-visits").json == []
    assert "No Photo Museum" in [p["name"] for p in imported.get("/api/places").json]


def test_a_museum_visit_is_to_a_museum(imported: webtest.TestApp, engine: Engine) -> None:
    hall = next(p for p in imported.get("/api/places").json if p["name"] == "The Hall")
    # a place that is no museum is not visited as one: an admin says it is one first
    error = imported.post_json("/api/museum-visits", {"place_id": hall["id"], "visits": [{}]}, status=400).json["error"]
    assert error == "The Hall is not a museum (a place of the kind Museum): an admin can say it is, on the Places page"
    imported.post_json("/api/museum-visits", {"visits": [{}]}, status=400)
    imported.post_json("/api/museum-visits", {"place_id": 9999, "visits": [{}]}, status=400)
    imported.put_json(f"/api/museum-visits/{hall['id']}", {"visits": []}, status=400)
    imported.put_json("/api/museum-visits/9999", {"visits": []}, status=404)
    kinds = {k["name"]: k["id"] for k in imported.get("/api/place-kinds").json}
    imported.put_json(f"/api/places/{hall['id']}", {"name": "The Hall", "kinds": [kinds["Concert venue"], kinds["Museum"]]})
    added = imported.post_json("/api/museum-visits", {"place_id": hall["id"], "visits": [{"date": "2020", "rating": 7}]}, status=201).json
    assert (added["id"], added["rating"]) == (hall["id"], 7)
    # another account's visits are theirs
    sign_in(imported, sub="someone-else")
    assert imported.get("/api/museum-visits").json == []
    imported.put_json(f"/api/museum-visits/{hall['id']}", {"visits": [{"id": added["visits"][0]["id"]}]}, status=400)


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
    assert [(d["name"], d["count"]) for d in devices] == [("Desktop", 2), ("Samsung S10", 1), ("Samsung S25", 3), ("Samsung S7", 2)]
    desktop, s10, s25, s7 = devices
    # the podcast episodes heard on one count too
    imported.delete(f"/api/devices/{s25['id']}", status=409)
    # a YouTube video's device counts too, and keeps it from being deleted
    imported.delete(f"/api/devices/{desktop['id']}", status=409)
    music = next(c for c in imported.get("/api/audio-courses").json if c["name"] == "How to Listen to Music")
    body = dict(music, lecturers=[p["id"] for p in music["lecturers"]], device_id=s10["id"])
    assert imported.put_json(f"/api/audio-courses/{music['id']}", body).json["device"] == {"id": s10["id"], "name": "Samsung S10"}
    # a device in use is not deleted; an unused one is
    imported.delete(f"/api/devices/{s10['id']}", status=409)
    # an audio book was heard on it too
    imported.delete(f"/api/devices/{s7['id']}", status=409)
    spare = imported.post_json("/api/devices", {"name": "Spare"}, status=201).json
    imported.delete(f"/api/devices/{spare['id']}", status=204)
    sansa = imported.post_json("/api/devices", {"name": "Sansa Clip 2", "description": "MP3 player"}, status=201).json
    imported.post_json("/api/devices", {"name": "Sansa Clip 2"}, status=409)
    # a device has a photo, with its credit; an edit that uploads none keeps it
    assert sansa["image"] is None
    upload = imported.post("/api/images", upload_files=[("file", "clip.jpg", JPEG)]).json
    photo = {"image_id": upload["id"], "image_source": "https://commons.wikimedia.org/wiki/File:Clip.jpg", "image_license": "CC BY-SA 3.0", "image_author": "Hinrik"}
    pictured = imported.put_json(f"/api/devices/{sansa['id']}", dict(sansa, **photo)).json
    assert pictured["image"] and pictured["image_license"] == "CC BY-SA 3.0" and pictured["image_author"] == "Hinrik"
    kept = imported.put_json(f"/api/devices/{sansa['id']}", dict(pictured, image_id=None, description="An MP3 player")).json
    assert kept["image"] == pictured["image"] and kept["description"] == "An MP3 player"
    assert imported.get(pictured["image"]).content_type == "image/jpeg"
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


def test_audio_books(imported: webtest.TestApp) -> None:
    books = imported.get("/api/audio-books").json
    # the latest into the library first
    # the latest finished or into the library first; one never finished nor added (only started) last
    assert [b["name"] for b in books] == ["Political Order and Political Decay", "Making Sense", "Letter to a Christian Nation", "Heretic"]
    order, sense, letter, heretic = books
    assert (sense["source"], sense["source_name"], sense["source_id"], sense["url"]) == ("audible", "Audible", "0063005409", "https://www.audible.com/pd/0063005409")
    assert (sense["subtitle"], sense["authors"], sense["narrators"], sense["minutes"]) == ("Conversations on Consciousness", "Sam Harris", "Sam Harris, David Chalmers", 1346)
    # everything as Audible gives it: the genres repeats too, the cover's address, when bought
    assert sense["genres"] == ["Psychology", "Science", "Psychology"]
    assert (sense["cover_url"], sense["purchased"]) == ("https://m.media-amazon.com/images/I/x.jpg", "2021-08-11T00:00:00Z")
    assert (sense["finished"], sense["status"], sense["source_rating"], sense["source_ratings"]) == (True, "done", 4.7, 592)
    assert (sense["added"], sense["released"], sense["rating"], sense["review"]) == ("2021-08-10T08:55:06.867000Z", "2020-08-11", None, "")
    assert imported.get(sense["image"]).body == b"\xff\xd8sense"
    # what Audible leaves empty is empty; a book without a cover file has none
    assert (order["series"], order["series_sequence"], order["minutes"], order["released"], order["source_rating"]) == ("Political Order", "2", None, "", None)
    assert (order["finished"], order["status"], order["percent_heard"], order["image"]) == (False, "in_progress", 12.5, None)
    # heard elsewhere: no source; said as an audio course is
    assert (letter["source"], letter["source_id"], letter["authors"], letter["url"]) == ("", "", "Sam Harris", "")
    assert (letter["finished"], letter["status"], letter["date"], letter["date_timezone"]) == (True, "done", "2016-05-01T21:33:15Z", "Asia/Jerusalem")
    assert (letter["listened_at"], letter["device"]["name"], letter["started"]) == ("Night Walks", "Samsung S7", "")
    assert (heretic["authors"], heretic["status"], heretic["started"], heretic["progress"]) == ("Ayaan Hirsi Ali, A. N. Other", "in_progress", "2022-08-20T12:28:35Z", "did part03")
    assert (heretic["date"], heretic["listened_at"], heretic["device"]["name"]) == (None, "Home", "Desktop")


def test_edit_audio_book(imported: webtest.TestApp) -> None:
    sense = next(b for b in imported.get("/api/audio-books").json if b["name"] == "Making Sense")
    edited = imported.put_json(f"/api/audio-books/{sense['id']}", dict(sense, rating=9, review="Deep", genres="Psychology, Philosophy, Psychology")).json
    assert (edited["rating"], edited["review"], edited["genres"]) == (9, "Deep", ["Psychology", "Philosophy", "Psychology"])
    # what only the source says is kept by an edit
    assert (edited["cover_url"], edited["purchased"]) == (sense["cover_url"], sense["purchased"])
    # the cover is kept when the edit sends none
    assert edited["image"] == sense["image"]
    added = imported.post_json("/api/audio-books", {"name": "A Book Heard Elsewhere", "authors": "Someone"}, status=201).json
    assert (added["source"], added["source_id"], added["url"], added["status"]) == ("", "", "", "")
    # a book is in a source's library once; an id needs its source; a source is one there is
    imported.post_json("/api/audio-books", {"name": "x", "source": "audible", "source_id": "0063005409"}, status=409)
    imported.post_json("/api/audio-books", {"name": "x", "source_id": "123"}, status=400)
    imported.post_json("/api/audio-books", {"name": "x", "source": "nowhere"}, status=400)
    imported.post_json("/api/audio-books", {"name": "x", "percent_heard": 101}, status=400)
    # finished on a day, and the device it was heard on; then started only, on none
    dated = imported.put_json(f"/api/audio-books/{added['id']}", dict(added, date="2024-03", listened_at="Car")).json
    assert (dated["status"], dated["date"], dated["date_precision"], dated["listened_at"]) == ("done", "2024-03", "month", "Car")
    started = imported.put_json(f"/api/audio-books/{added['id']}", dict(dated, date="", started="2024-01-02", progress="disc 2")).json
    assert (started["status"], started["started"], started["progress"]) == ("in_progress", "2024-01-02T00:00:00Z", "disc 2")
    imported.put_json(f"/api/audio-books/{added['id']}", dict(started, device_id=99999), status=400)
    imported.delete(f"/api/audio-books/{added['id']}", status=204)
    assert len(imported.get("/api/audio-books").json) == 4


def test_audio_books_import_runs_again(imported: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    sense = next(b for b in imported.get("/api/audio-books").json if b["name"] == "Making Sense")
    imported.put_json(f"/api/audio-books/{sense['id']}", dict(sense, name="Making Sense (edited)", rating=9))
    source = write_source(tmp_path / "again")
    yaml_file = source / "data" / "yaml" / "audible.yaml"
    # Audible since: the second book further along, and a third one bought
    text = yaml_file.read_text(encoding="UTF8").replace('percent_complete: "12.5"', 'percent_complete: "40.0"')
    text += """  - asin: "B0NEWBOOK1"
    title: "A New One"
    subtitle: ""
    authors: "Someone New"
    narrators: ""
    series_title: ""
    series_sequence: ""
    genres: []
    runtime_length_min: "60"
    is_finished: false
    percent_complete: "0.0"
    rating: ""
    num_ratings: ""
    date_added: "2023-03-03T00:00:00Z"
    release_date: "2023-01-01"
    cover_url: ""
    purchase_date: "2023-03-03T00:00:00Z"
"""
    yaml_file.write_text(text, encoding="UTF8")
    with Session(engine) as session:
        counts = import_world.import_audio_books(session, owner(session), source)
        session.commit()
    assert counts == {"audio books added": 1, "audio books refreshed": 1, "images": 0, "devices added": 0}
    books = {b["source_id"]: b for b in imported.get("/api/audio-books").json}
    assert books["B07D23CFGR"]["percent_heard"] == 40.0
    # what was edited in the app stays
    assert (books["0063005409"]["name"], books["0063005409"]["rating"]) == ("Making Sense (edited)", 9)
    assert books["B0NEWBOOK1"]["name"] == "A New One"
    with Session(engine) as session:
        again = import_world.import_audio_books(session, owner(session), source)
    assert again == {"audio books added": 0, "audio books refreshed": 0, "images": 0, "devices added": 0}


def test_audio_books_import_gives_back_the_genres_kept_once(imported: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    del imported
    with Session(engine) as session:
        # as an earlier import kept them: each once, and without the cover's address or when bought
        sense = session.scalars(select(AudioBook).where(AudioBook.source_id == "0063005409")).one()
        sense.genres, sense.cover_url, sense.purchased_utcz = ["Psychology", "Science"], "", None
        order = session.scalars(select(AudioBook).where(AudioBook.source_id == "B07D23CFGR")).one()
        # edited in the app: left as it is
        order.genres = ["Politics"]
        session.commit()
        import_world.import_audio_books(session, owner(session), write_source(tmp_path / "again"))
        session.commit()
        assert sense.genres == ["Psychology", "Science", "Psychology"]
        assert (sense.cover_url, sense.purchased_utcz) == ("https://m.media-amazon.com/images/I/x.jpg", datetime.datetime(2021, 8, 11))
        assert order.genres == ["Politics"]


def test_a_source_without_the_audible_library(app: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    sign_in_admin(app, engine)
    source = write_source(tmp_path)
    (source / "data" / "yaml" / "audible.yaml").unlink()
    (source / "data" / "yaml" / "audio_books.yaml").unlink()
    with Session(engine) as session:
        # the site no longer keeps them: the full import imports no audio books, --audio-books says why it cannot
        assert import_world.import_world(session, owner(session), source)["audio books"] == 0
        with pytest.raises(import_world.WorldImportError, match="no longer keeps them"):
            import_world.import_audio_books(session, owner(session), source)


def test_a_source_without_youtube(app: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    sign_in_admin(app, engine)
    source = write_source(tmp_path)
    (source / "data" / "yaml" / "video_youtube.yaml").unlink()
    (source / "static" / "data" / "youtube.json.gz").unlink()
    with Session(engine) as session:
        # the site no longer keeps them: the full import imports no YouTube videos, --youtube and --youtube-history say why they cannot
        assert import_world.import_world(session, owner(session), source)["YouTube videos"] == 0
        with pytest.raises(import_world.WorldImportError, match="no longer keeps it"):
            import_world.import_youtube(session, owner(session), source)
        with pytest.raises(import_world.WorldImportError, match="no longer keeps it"):
            import_world.import_youtube_history(session, owner(session), source)


def test_audio_books_import_refuses_what_it_does_not_know(imported: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    del imported
    source = write_source(tmp_path / "again")
    yaml_file = source / "data" / "yaml" / "audible.yaml"
    yaml_file.write_text(yaml_file.read_text(encoding="UTF8").replace('    cover_url: ""', '    cover_url: ""\n    wishlist: true'), encoding="UTF8")
    with Session(engine) as session, pytest.raises(import_world.WorldImportError, match="does not know"):
        import_world.import_audio_books(session, owner(session), source)


def test_podcasts(imported: webtest.TestApp) -> None:
    # the podcasts are shared: by name
    podcasts = imported.get("/api/podcasts").json
    assert [p["name"] for p in podcasts] == ["Mindscape", "The rest is history"]
    mindscape, history = podcasts
    assert (history["url"], history["rss_feed"], history["episodes"]) == (
        "https://therestishistory.com/club", "https://feeds.megaphone.fm/GLT4787413333", 2)
    # the same for everyone: what the user heard of it is in Your podcasts
    assert "heard" not in history and "listened" not in history
    assert "rating" not in history and history["published"] == "2020-11-02T02:00:00Z"
    assert imported.get(history["image"]).body == b"\xff\xd8history"
    assert (mindscape["episodes"], mindscape["image"]) == (1, None)
    # and so are their episodes, the latest published first, each saying when the user heard it
    episodes = imported.get("/api/podcast-episodes").json
    assert [e["name"] for e in episodes] == ["1. Greatness", "Trailer", "Welcome to the Mindscape Podcast!"]
    greatness, trailer, welcome = episodes
    # everything as the feed says it: pubDate in UTC
    assert (greatness["podcast"]["name"], greatness["published"], greatness["number"], greatness["duration"]) == ("The rest is history", "2020-11-02T02:00:00Z", 1, 1975)
    assert (greatness["episode_type"], greatness["explicit"], greatness["author"], greatness["guid"]) == ("full", "yes", "Goalhanger", "d64331b9")
    assert (greatness["enclosure_url"], greatness["url"], greatness["image_url"]) == ("https://pdst.fm/e/greatness.mp3", "https://pdst.fm/e/greatness.mp3", "https://megaphone.imgix.net/greatness.jpg")
    assert (greatness["description"], greatness["image"], greatness["heard"]["date"]) == ("How did certain people come to be called the Great?", history["image"], "2026-03-27T10:00:00Z")
    # what a feed leaves out is empty; "false" is kept as the feed says it
    assert (welcome["number"], welcome["author"], welcome["explicit"], welcome["image"]) == (None, "", "false", None)
    assert (trailer["episode_type"], trailer["image_url"], trailer["published"]) == ("trailer", "", "2020-10-28T13:00:00Z")
    # the user's own: the podcasts they listen to, the one heard last first, with their rating and review and the episodes heard
    heard = imported.get("/api/podcasts-heard").json
    assert [(p["name"], p["rating"], p["review"]) for p in heard] == [("The rest is history", 7, "So-so podcast"), ("Mindscape", 8, "A very good podcast")]
    assert ([e["name"] for e in heard[0]["episodes"]], heard[0]["duration"], heard[0]["date_sort"]) == (["1. Greatness", "Trailer"], 286 + 1975, "2026-03-27")
    # and the episodes heard: the latest heard first; of a day, the latest published first
    listened = imported.get("/api/episodes-heard").json
    assert [e["name"] for e in listened] == ["1. Greatness", "Welcome to the Mindscape Podcast!", "Trailer"]
    first = listened[0]
    assert (first["episode"]["id"], first["date"], first["date_timezone"], first["listened_at"], first["device"]["name"]) == (
        greatness["id"], "2026-03-27T10:00:00Z", "Asia/Jerusalem", "Night Walks", "Samsung S25")
    assert (first["published"], first["duration"], first["image"]) == (greatness["published"], 1975, history["image"])
    assert greatness["heard"]["id"] == first["id"]


def test_edit_podcasts(imported: webtest.TestApp) -> None:
    history = imported.get("/api/podcasts").json[1]
    edited = imported.put_json(f"/api/podcasts/{history['id']}", dict(history, url="https://therestishistory.com")).json
    assert (edited["url"], edited["image"], edited["episodes"]) == ("https://therestishistory.com", history["image"], 2)
    imported.post_json("/api/podcasts", {"name": "The rest is history"}, status=409)
    imported.post_json("/api/podcasts", {"name": "x", "rss_feed": "feed"}, status=400)
    # a podcast someone listens to stays, and so does an episode someone heard
    imported.delete(f"/api/podcasts/{history['id']}", status=409)
    greatness = imported.get("/api/podcast-episodes").json[0]
    imported.delete(f"/api/podcast-episodes/{greatness['id']}", status=409)
    new = imported.post_json("/api/podcasts", {"name": "Hardcore History", "url": "https://www.dancarlin.com"}, status=201).json
    # the published moment sent back as shown is kept to the second
    body = {**greatness, "podcast_id": greatness["podcast"]["id"], "author": "Goalhanger Films"}
    edited = imported.put_json(f"/api/podcast-episodes/{greatness['id']}", body).json
    assert (edited["author"], edited["published"], edited["guid"]) == ("Goalhanger Films", greatness["published"], "d64331b9")
    # an episode is of a podcast, and in it once by its guid
    imported.post_json("/api/podcast-episodes", {"name": "x"}, status=400)
    imported.post_json("/api/podcast-episodes", {"name": "x", "podcast_id": greatness["podcast"]["id"], "guid": "d64331b9"}, status=409)
    khans = imported.post_json("/api/podcast-episodes", {"name": "Wrath of the Khans", "podcast_id": new["id"], "published": "2006-04-01"}, status=201).json
    assert (khans["podcast"]["name"], khans["published"], khans["guid"], khans["heard"]) == ("Hardcore History", "2006-04-01T00:00:00Z", "", None)
    # hearing it puts its podcast in the user's Podcasts heard
    heard = imported.post_json("/api/episodes-heard", {"episode_id": khans["id"], "date": "2026-04-01", "rating": 9}, status=201).json
    assert (heard["name"], heard["podcast"]["name"], heard["date"], heard["rating"]) == ("Wrath of the Khans", "Hardcore History", "2026-04-01", 9)
    imported.post_json("/api/episodes-heard", {"episode_id": khans["id"]}, status=409)
    hardcore = next(p for p in imported.get("/api/podcasts-heard").json if p["name"] == "Hardcore History")
    assert ([e["id"] for e in hardcore["episodes"]], hardcore["rating"]) == ([heard["id"]], None)
    imported.put_json(f"/api/podcasts-heard/{hardcore['id']}", {"podcast_id": new["id"], "rating": 10, "review": "Long"})
    imported.post_json("/api/podcasts-heard", {"podcast_id": new["id"]}, status=409)
    # a podcast heard with episodes heard stays; without, it goes, and then the podcast may
    imported.delete(f"/api/podcasts-heard/{hardcore['id']}", status=409)
    imported.delete(f"/api/episodes-heard/{heard['id']}")
    imported.delete(f"/api/podcasts-heard/{hardcore['id']}")
    imported.delete(f"/api/podcast-episodes/{khans['id']}")
    imported.delete(f"/api/podcasts/{new['id']}")


def test_podcasts_import_runs_again(imported: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    heard = imported.get("/api/episodes-heard").json[0]
    imported.put_json(f"/api/episodes-heard/{heard['id']}", {"episode_id": heard["episode"]["id"], "date": heard["date"], "review": "edited"})
    source = write_source(tmp_path / "again")
    yaml_file = source / "data" / "yaml" / "podcasts.yaml"
    # a new episode heard of a podcast there is: only it is added
    yaml_file.write_text(yaml_file.read_text(encoding="UTF8").replace("    rating: 8\n", """      - title: "1 | Carol Tavris"
        pubDate: "Mon, 02 Jul 2018 06:00:00 +0000"
        guid: "c4f1"
        date_ymd: "2026-04-02"
    rating: 8
"""), encoding="UTF8")
    with Session(engine) as session:
        counts = import_world.import_podcasts(session, owner(session), source)
        session.commit()
    assert counts == {"podcasts added": 0, "podcast episodes added": 1, "covers added": 0, "podcasts heard added": 0, "episodes heard added": 1, "devices added": 0}
    listened = imported.get("/api/episodes-heard").json
    assert listened[0]["name"] == "1 | Carol Tavris"
    assert next(e for e in listened if e["id"] == heard["id"])["review"] == "edited"
    # another account that heard the same: the shared podcasts and episodes are found, only its own hearing is added
    with Session(engine) as session:
        bob = User(email="bob@example.com")
        session.add(bob)
        session.flush()
        counts = import_world.import_podcasts(session, bob, source)
        session.commit()
    assert counts == {"podcasts added": 0, "podcast episodes added": 0, "covers added": 0, "podcasts heard added": 2, "episodes heard added": 4, "devices added": 1}


def test_podcasts_import_refuses_what_it_does_not_know(imported: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    del imported
    source = write_source(tmp_path / "again")
    yaml_file = source / "data" / "yaml" / "podcasts.yaml"
    yaml_file.write_text(yaml_file.read_text(encoding="UTF8").replace('        guid: "e7b5a1d2"\n', '        guid: "e7b5a1d2"\n        season: 1\n'), encoding="UTF8")
    with Session(engine) as session, pytest.raises(import_world.WorldImportError, match="does not know"):
        import_world.import_podcasts(session, owner(session), source)
    (source / "data" / "yaml" / "podcasts.yaml").unlink()
    with Session(engine) as session, pytest.raises(import_world.WorldImportError, match="no longer keeps it"):
        import_world.import_podcasts(session, owner(session), source)


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
    books = {b["main_title"]: b for b in imported.get("/api/library-entries?kind=book").json}
    hobbit, may, chess = books["The Hobbit"], books["Thirty Fifth in May"], books["Chess"]
    # the dated reading gives the rating, the review and the day (in Jerusalem, a day after UTC)
    assert (hobbit["creator"], hobbit["status"], hobbit["rating"], hobbit["finished_on"]) == ("J.R.R. Tolkien", "done", 7, "2004-08-13")
    # what was thought of it is its review, and what it has no field for its notes
    assert (hobbit["review"], hobbit["notes"]) == ("Good", "Read in English (date unknown); English (2004-08-13)")
    # the languages it is owned in are a list of its own
    assert hobbit["owned"] == ["en"]
    assert hobbit["goodreads_id"] == "5907"
    assert imported.get(hobbit["image"]).body == b"\xff\xd8hobbit"
    # text_books.yaml rates a book read with no rating of its own
    assert (may["rating"], may["finished_on"], may["simania_id"]) == (8, None, "7005")
    assert (may["review"], may["notes"]) == ("nice", "Read in Hebrew (date unknown). Written in German. was named: 35 May")
    # read in Hebrew, but shown in the language the account prefers, English to begin with: its English title, its author's English name
    assert (may["locale"], may["title"], may["main_title"], may["title_locale"]) == ("he", "Thirty Fifth in May", "Thirty Fifth in May", "en")
    assert may["titles"] == [{"locale": "he", "title": "שלושים וחמישה במאי"}]
    assert [a["name"] for a in may["authors"]] == ["Erich Kestner"]
    # preferring Hebrew (Settings): a book with a Hebrew title is shown by it, its author by his Hebrew name; one without is as it was
    assert imported.get("/api/config").json["user"]["locale"] == "en"
    assert imported.put_json("/api/account/locale", {"locale": "he"}).json["locale"] == "he"
    in_hebrew = {b["main_title"]: b for b in imported.get("/api/library-entries?kind=book").json}
    assert (in_hebrew["Thirty Fifth in May"]["title"], [a["name"] for a in in_hebrew["Thirty Fifth in May"]["authors"]]) == ("שלושים וחמישה במאי", ["אריך קסטנר"])
    assert in_hebrew["The Hobbit"]["title"] == "The Hobbit"
    # and so are people, everywhere: one with a Hebrew name by it, with the English one kept beside it
    people = {p["english_name"]: p for p in imported.get("/api/people").json}
    assert (people["Erich Kestner"]["name"], people["Erich Kestner"]["names"]) == ("אריך קסטנר", [named("he", "אריך", "קסטנר")])
    assert all(p["name"] == p["english_name"] for p in people.values() if not p["names"])
    imported.put_json("/api/account/locale", {"locale": "xx"}, status=400)
    imported.put_json("/api/account/locale", {"locale": "en"})
    assert (hobbit["locale"], hobbit["title"], hobbit["titles"]) == ("en", "The Hobbit", [])
    # every other view names the author in English, with the other names alongside
    [kestner] = [p for p in imported.get("/api/people").json if p["name"] == "Erich Kestner"]
    assert kestner["names"] == [named("he", "אריך", "קסטנר")]
    # owned but not read, with no cover
    assert (chess["status"], chess["creator"], chess["image"], chess["locale"]) == ("wishlist", "", None, "")
    assert (chess["notes"], chess["owned"]) == ("Written in Hebrew", ["he"])


def test_books_import_adds_once(imported: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    source = write_source(tmp_path / "again")
    [hobbit] = [b for b in imported.get("/api/library-entries?kind=book").json if b["main_title"] == "The Hobbit"]
    imported.delete(f"/api/library-entries/{hobbit['work_id']}", status=204)
    with Session(engine) as session:
        counts = import_world.import_books(session, owner(session), source)
        session.commit()
    # the deleted one comes back, on the work there already, and its cover is stored again
    assert counts == {
        "books": 1, "books there already": 2, "covers": 1, "covers given to books there already": 0, "books with no cover": 0,
        "authors added": 0, "people made book authors": 0, "authors given to books there already": 0,
        "titles in other languages": 0, "author names in other languages": 0, "languages given to books there already": 0, "notes tidied": 0,
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
        "titles in other languages": 0, "author names in other languages": 0, "languages given to books there already": 0, "notes tidied": 0,
    }
    books = {b["main_title"]: b for b in imported.get("/api/library-entries?kind=book").json}
    assert imported.get(books["Chess"]["image"]).body == b"\xff\xd8chess"
    assert imported.get(books["The Hobbit"]["image"]).body == b"\xff\xd8hobbit"


def test_book_authors_are_people(imported: webtest.TestApp) -> None:
    books = {b["main_title"]: b for b in imported.get("/api/library-entries?kind=book").json}
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
    # a book may have several authors, and each one linked becomes a Book Author
    kasparov = imported.post_json("/api/people", {"first_name": "Garry", "surname": "Kasparov"}, status=201).json
    entry = imported.put_json(f"/api/library-entries/{work_id}", {"status": "done", "authors": [tolkien["id"], kasparov["id"]]}).json
    assert [a["name"] for a in entry["authors"]] == ["J.R.R. Tolkien", "Garry Kasparov"]
    [garry] = [p for p in imported.get("/api/people").json if p["id"] == kasparov["id"]]
    assert [t["name"] for t in garry["types"]] == ["Book Author"]



def test_link_authors_names() -> None:
    # the names in a book's creator text, each once
    assert link_authors.author_names("Garry Kasparov") == ["Garry Kasparov"]
    assert link_authors.author_names("Kernighan, Ritchie") == ["Kernighan", "Ritchie"]
    assert link_authors.author_names("Brian Kernighan and Dennis Ritchie & Ken Thompson; Brian Kernighan") == ["Brian Kernighan", "Dennis Ritchie", "Ken Thompson"]
    assert link_authors.author_names("  ") == []


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
        "titles in other languages": 0, "author names in other languages": 0, "languages given to books there already": 0, "notes tidied": 0,
    }
    books = {b["main_title"]: b for b in imported.get("/api/library-entries?kind=book").json}
    assert len(books) == 3
    assert (books["Chess"]["creator"], [a["name"] for a in books["Chess"]["authors"]]) == ("Garry Kasparov", ["Garry Kasparov"])
    assert [a["name"] for a in books["The Hobbit"]["authors"]] == ["J.R.R. Tolkien"]
    kasparov = next(p for p in imported.get("/api/people").json if p["name"] == "Garry Kasparov")
    assert [t["name"] for t in kasparov["types"]] == ["Book Author"]


def test_books_import_fills_languages(imported: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    source = write_source(tmp_path / "again")
    # books imported before names had languages: no language read in, no
    # other titles or names, and those said in the notes instead
    old_notes = "Read in Hebrew (date unknown). Written in German. Hebrew title: שלושים וחמישה במאי. Author in Hebrew: אריך קסטנר. was named: 35 May"
    with Session(engine) as session:
        session.execute(delete(WorkTitle))
        session.execute(delete(PersonName))
        session.execute(delete(Read))
        may = session.scalars(select(UserWork).join(Work).where(Work.title == "Thirty Fifth in May")).one()
        may.notes = old_notes + ". and an edit of mine"
        session.commit()
        counts = import_world.import_books(session, owner(session), source)
        session.commit()
    assert {k: v for k, v in counts.items() if v} == {
        "books there already": 3, "titles in other languages": 1, "author names in other languages": 1,
        "languages given to books there already": 2, "notes tidied": 1,
    }
    books = {b["main_title"]: b for b in imported.get("/api/library-entries?kind=book").json}
    may = books["Thirty Fifth in May"]
    assert (may["locale"], may["titles"]) == ("he", [{"locale": "he", "title": "שלושים וחמישה במאי"}])
    # only what the import once wrote goes: the user's own words stay
    assert may["notes"] == "Read in Hebrew (date unknown). Written in German. was named: 35 May. and an edit of mine"
    assert books["The Hobbit"]["locale"] == "en"
    # and again: nothing more to do
    with Session(engine) as session:
        again = import_world.import_books(session, owner(session), source)
    assert {k: v for k, v in again.items() if v} == {"books there already": 3}


def test_names_in_languages(imported: webtest.TestApp) -> None:
    # a person's names in other languages, one per language, replaced when sent
    bob = imported.post_json("/api/people", {"first_name": "Haim", "surname": "Shapira", "names": [{"locale": "he", "name": " חיים  שפירא "}]}, status=201).json
    assert (bob["name"], bob["names"]) == ("Haim Shapira", [named("he", "חיים", "שפירא")])
    body = {"first_name": "Haim", "surname": "Shapira"}
    renamed = imported.put_json(f"/api/people/{bob['id']}", dict(body, names=[{"locale": "he", "name": "חיים שפירה"}, {"locale": "ru", "name": "Хаим Шапира"}])).json
    assert renamed["names"] == [named("he", "חיים", "שפירה"), named("ru", "Хаим", "Шапира")]
    # a name in its parts, as the English one is: the honorific, the first name, the middle name, the surname
    parts = {"locale": "he", "honorific": 'ד"ר', "first_name": "חיים", "middle_name": " בן  דוד ", "surname": "שפירא"}
    in_parts = imported.put_json(f"/api/people/{bob['id']}", dict(body, names=[parts])).json["names"]
    assert in_parts == [named("he", "חיים", "שפירא", middle="בן דוד", honorific='ד"ר')]
    for wrong in ({**parts, "first_name": "חיים דוד"}, {**parts, "surname": "Shapira"}, {"locale": "he", "first_name": "", "surname": ""}):
        imported.put_json(f"/api/people/{bob['id']}", dict(body, names=[wrong]), status=400)
    imported.put_json(f"/api/people/{bob['id']}", dict(body, names=renamed["names"]))
    assert imported.put_json(f"/api/people/{bob['id']}", body).json["names"] == renamed["names"]
    for wrong in ([{"locale": "he", "name": "א"}, {"locale": "he", "name": "ב"}], [{"locale": "xx", "name": "x"}], [{"locale": "en", "name": "x"}], [{"locale": "he", "name": " "}], "he"):
        imported.put_json(f"/api/people/{bob['id']}", dict(body, names=wrong), status=400)
    # a book in a language: its title and its authors' names in it
    book = imported.post_json("/api/library-entries", {"kind": "book", "title": "Thinking About Thinking", "title_locale": "en", "locale": "he",
                                                       "titles": [{"locale": "he", "title": "לחשוב על חשיבה"}],
                                                       "authors": [bob["id"]]}).json
    assert (book["title"], book["main_title"], [a["name"] for a in book["authors"]]) == ("Thinking About Thinking", "Thinking About Thinking", ["Haim Shapira"])
    assert [t["title"] for t in book["titles"]] == ["לחשוב על חשיבה"]
    # one title per language: two in one are refused, sent together or one after the other, and so is one in the main title's
    for titles in ([{"locale": "fr", "title": "Penser"}, {"locale": "fr", "title": "Pensées"}], [{"locale": "he", "title": "חשיבה"}], [{"locale": "en", "title": "Thinking"}]):
        response = imported.put_json(f"/api/library-entries/{book['work_id']}", {"titles": titles}, status=400)
        assert "per language" in response.json["error"]
    # with no author text sent, the book's is its authors' English names
    assert book["creator"] == "Haim Shapira"
    plain = imported.post_json("/api/library-entries", {"kind": "book", "title": "Untitled thoughts"}).json
    assert plain["creator"] == ""
    filled = imported.put_json(f"/api/library-entries/{plain['work_id']}", {"authors": [bob["id"]]}).json
    assert filled["creator"] == "Haim Shapira"
    # titles are only added, never twice: the ones it has may be sent again
    sent = [{"locale": "en", "title": "Thinking About Thinking"}, {"locale": "he", "title": "לחשוב על חשיבה"}, {"locale": "fr", "title": "Penser"}]
    again = imported.put_json(f"/api/library-entries/{book['work_id']}", {"locale": "en", "titles": sent}).json
    assert (again["title"], [a["name"] for a in again["authors"]]) == ("Thinking About Thinking", ["Haim Shapira"])
    assert [(t["locale"], t["title"]) for t in again["titles"]] == [("he", "לחשוב על חשיבה"), ("fr", "Penser")]
    # read in no language said: none kept
    assert imported.put_json(f"/api/library-entries/{book['work_id']}", {"locale": ""}).json["locale"] == ""
    imported.put_json(f"/api/library-entries/{book['work_id']}", {"locale": "xx"}, status=400)
    imported.post_json("/api/library-entries", {"kind": "book", "title": "X", "title_locale": "xx"}, status=400)
    assert imported.get("/api/config").json["locales"]["he"] == "Hebrew"


def test_book_year_and_ids(imported: webtest.TestApp) -> None:
    # the year it came out is filled in or put right on the work; the ISBN and the Open Library work are only filled in
    book = imported.post_json("/api/library-entries", {"kind": "book", "title": "The Republic", "isbn": "9780140455113", "openlibrary_id": "OL123W"}).json
    assert (book["year"], book["isbn"], book["openlibrary_id"]) == (None, "9780140455113", "OL123W")
    dated = imported.put_json(f"/api/library-entries/{book['work_id']}", {"year": -375}).json
    assert dated["year"] == -375
    # a wrong year is put right, and one not sent leaves it as it is
    assert imported.put_json(f"/api/library-entries/{book['work_id']}", {"year": 1999}).json["year"] == 1999
    assert imported.put_json(f"/api/library-entries/{book['work_id']}", {"rating": 9}).json["year"] == 1999
    assert imported.put_json(f"/api/library-entries/{book['work_id']}", {"year": -375}).json["year"] == -375
    # but not to the year of another book of the same title and author
    other = imported.post_json("/api/library-entries", {"kind": "book", "title": "The Republic", "year": 1955}).json
    assert other["work_id"] != book["work_id"]
    imported.put_json(f"/api/library-entries/{other['work_id']}", {"year": -375}, status=409)
    again = imported.post_json("/api/library-entries", {"kind": "book", "title": "The Republic", "year": -375, "isbn": "0", "openlibrary_id": "OL9W"}).json
    assert (again["work_id"], again["isbn"], again["openlibrary_id"]) == (book["work_id"], "9780140455113", "OL123W")


def test_book_original_language(imported: webtest.TestApp) -> None:
    # the language a book was first written in is on the work: not known at first, set when sent, never emptied
    book = imported.post_json("/api/library-entries", {"kind": "book", "title": "The Joke"}).json
    assert book["original_locale"] == ""
    url = f"/api/library-entries/{book['work_id']}"
    assert imported.put_json(url, {"original_locale": "cs"}).json["original_locale"] == "cs"
    assert imported.put_json(url, {"original_locale": ""}).json["original_locale"] == "cs"
    assert imported.put_json(url, {"notes": "x"}).json["original_locale"] == "cs"
    imported.put_json(url, {"original_locale": "xx"}, status=400)
    # a new book may say it at once, and the language counts what is said in it
    assert imported.post_json("/api/library-entries", {"kind": "book", "title": "Dune 2", "original_locale": "en"}).json["original_locale"] == "en"


def test_fetch_book_details_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {
        "https://www.goodreads.com/book/show/1": '<p>First published February 17, 1884</p>"isbn":"1568461933","isbn13":"9781568461939"',
        "https://www.goodreads.com/book/show/2": '<p>First published 380 BC</p>',
        "https://www.goodreads.com/book/show/3": '"publicationTime":1094022000000,"isbn":"0140455116"',
        "https://simania.co.il/bookdetails.php?item_id=4": '{\\"isbn\\": \\"0\\", \\"datePublished\\": \\"1985\\"}',
        "https://simania.co.il/bookdetails.php?item_id=5": '"isbn": "965-13-0001-2", "datePublished": "2001"',
    }
    monkeypatch.setattr(fetch_book_details, "get", pages.get)
    assert fetch_book_details.goodreads("1") == {"year": 1884, "isbn": "9781568461939"}
    assert fetch_book_details.goodreads("2") == {"year": -380}
    assert fetch_book_details.goodreads("3") == {"year": 2004, "isbn": "0140455116"}
    assert fetch_book_details.goodreads("9") == {}
    # Simania says "0" for no ISBN
    assert fetch_book_details.simania("4") == {"year": 1985}
    assert fetch_book_details.simania("5") == {"year": 2001, "isbn": "965130001" + "2"}
    assert fetch_book_details.plain("The Hobbit: or There and Back Again") == fetch_book_details.plain("the  hobbit")


def test_books_unknown_field(engine: Engine, tmp_path: Path, app: webtest.TestApp) -> None:
    sign_in(app)
    source = write_source(tmp_path)
    path = source / "data" / "yaml" / "books_read.yaml"
    path.write_text(BOOKS.replace('        rating: 7', '        rating: 7\n        mood: "happy"'), encoding="UTF8")
    with Session(engine) as session, pytest.raises(import_world.WorldImportError, match=r"a reading of 'The Hobbit' has fields .*mood"):
        import_world.import_books(session, owner(session), source)


def test_people_links_point_at_people(imported: webtest.TestApp) -> None:
    ids = {p["name"]: p["id"] for p in imported.get("/api/people").json}
    visits = [visit for museum in imported.get("/api/museum-visits").json for visit in museum["visits"]]
    for item in [*imported.get("/api/concert-visits").json, *visits]:
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
    assert set(alice) == {"id", "name", "is_self", "honorific", "first_name", "middle_name", "surname", "relations", "related", "types", "organizations", "organization_links", "description", "names", "english_name", "image", "photos"}


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
    # a profession has a photo, with its credit; an edit that uploads none keeps it
    assert programmer["image"] is None
    upload = imported.post("/api/images", upload_files=[("file", "coder.jpg", JPEG)]).json
    photo = {"image_id": upload["id"], "image_source": "https://commons.wikimedia.org/wiki/File:Coder.jpg", "image_license": "CC BY 2.0", "image_author": "Someone"}
    pictured = imported.put_json(f"/api/person-types/{programmer['id']}", dict(programmer, **photo)).json
    assert pictured["image"] and pictured["image_license"] == "CC BY 2.0"
    kept = imported.put_json(f"/api/person-types/{programmer['id']}", dict(pictured, image_id=None, description="Writes code")).json
    assert kept["image"] == pictured["image"] and kept["description"] == "Writes code"
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


def test_reimport_refuses_an_account_with_data(imported: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    """ The full import replaces everything, so on an account with data it stops unless told to replace. """
    with Session(engine) as session:
        concert = session.scalars(select(Concert)).first()
        assert concert is not None
        concert.remark = "edited in the app"
        session.commit()
    with Session(engine) as session, pytest.raises(import_world.WorldImportError, match="--replace-everything alice@example.com"):
        import_world.import_world(session, owner(session), tmp_path)
    remarks = [concert["remark"] for concert in imported.get("/api/concert-visits").json]
    assert "edited in the app" in remarks


def test_reimport_replaces(imported: webtest.TestApp, engine: Engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        import_world.import_world(session, owner(session), tmp_path, replace=True)
        session.commit()
        # the shared rows (places, the museums among them) are found again, not added twice
        for model, count in ((Concert, 3), (Place, 3), (Visit, 3), (AudioCourse, 2), (Person, 8), (Organization, 3), (AudioBook, 4), (Podcast, 2), (PodcastEpisode, 3), (Image, 9)):
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
    with Session(engine) as session:
        # one account per email; a login's subject (or the bare Google sub it once was) insists it has that login
        google = owner(session)
        assert import_world.find_owner(session, "alice@example.com", "1234567890").id == google.id
        assert import_world.find_owner(session, "alice@example.com", "google:1234567890").id == google.id
        with pytest.raises(import_world.WorldImportError, match="no account"):
            import_world.find_owner(session, "alice@example.com", "email:alice@example.com")


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
    imported.post_json("/api/museum-visits", {"name": "x", "visits": [{"rating": 11}]}, status=400)
    imported.post_json("/api/museum-visits", {"name": "x", "visits": "often"}, status=400)
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


def a_museum(app: webtest.TestApp, name: str, **columns: Any) -> int:
    """ A museum, as an admin adds it to the Places page: a place of the kind Museum; its id. """
    kinds = {k["name"]: k["id"] for k in app.get("/api/place-kinds").json}
    return app.post_json("/api/places", {"name": name, "kinds": [kinds["Museum"]], **columns}, status=201).json["id"]


def test_add_museum_and_person(imported: webtest.TestApp) -> None:
    person = imported.post_json("/api/people", {"first_name": "Carol", "description": "Zed"}, status=201).json
    museum = imported.post_json("/api/museum-visits", {
        "place_id": a_museum(imported, "Prado"), "visits": [{"date": "2012", "rating": 9, "people": [person["id"]]}],
    }, status=201).json
    assert (museum["date"], museum["rating"]) == ("2012", 9)
    assert museum["visits"][0]["with"] == ["Carol"]
    assert museum["image"] is None


def test_museum_alone(imported: webtest.TestApp) -> None:
    [alone] = imported.post_json("/api/museum-visits", {"place_id": a_museum(imported, "Prado"), "visits": [{"alone": True}]}, status=201).json["visits"]
    assert alone["alone"] is True
    assert alone["with"] == []
    assert imported.post_json("/api/museum-visits", {"place_id": a_museum(imported, "Tate"), "visits": [{}]}, status=201).json["visits"][0]["alone"] is False
    # alone with company is a contradiction
    person = imported.post_json("/api/people", {"first_name": "Carol"}, status=201).json
    imported.post_json("/api/museum-visits", {"place_id": a_museum(imported, "Uffizi"), "visits": [{"alone": True, "people": [person["id"]]}]}, status=400)


def test_addresses_and_coordinates(imported: webtest.TestApp) -> None:
    spain = imported.post_json("/api/countries", {"name": "Spain"}, status=201).json
    madrid = imported.post_json("/api/cities", {"name": "Madrid", "country_id": spain["id"]}, status=201).json
    prado = a_museum(
        imported, "Prado", street="Calle de Ruiz de Alarcón 23", neighbourhood="Retiro", postcode="28014", city_id=madrid["id"], latitude="40.4138", longitude=-3.6921,
    )
    museum = imported.post_json("/api/museum-visits", {"place_id": prado, "visits": [{}]}, status=201).json
    # the parts, and the address in one line with the city and its country
    assert (museum["street"], museum["neighbourhood"], museum["postcode"]) == ("Calle de Ruiz de Alarcón 23", "Retiro", "28014")
    assert (museum["address"], museum["latitude"], museum["longitude"]) == ("Calle de Ruiz de Alarcón 23, Retiro, Madrid 28014, Spain", 40.4138, -3.6921)
    # a dialog with the coordinates cleared leaves the place off the map
    place = next(p for p in imported.get("/api/places").json if p["id"] == prado)
    cleared = imported.put_json(f"/api/places/{prado}", dict(place, city_id=madrid["id"], kinds=[k["id"] for k in place["kinds"]], latitude="", longitude="")).json
    assert (cleared["latitude"], cleared["longitude"]) == (None, None)
    organization = imported.post_json("/api/organizations", {"name": "Glil", "street": "Kibbutz Glil Yam", "latitude": 32.15556, "longitude": 34.82361}, status=201).json
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
    louvre = next(m for m in imported.get("/api/museum-visits").json if m["people"])
    assert [p["name"] for p in louvre["people"]] == ["Robert Buddy"]
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
        assert sorted(session.scalars(select(Image.filename)).all()) == ["acme.svg", "audible-0063005409.jpg", "audiocourse-gc-337.jpg", "audiocourse-internal-1.jpg", "book-goodreads-5907.jpg", "book-simania-7005.jpg", "museum-15.jpg", "podcast-1.jpg"]
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
    assert (stats["people"], stats["organizations"], stats["images"]) == (8, 3, 9)
    assert (stats["podcasts"], stats["podcast_episodes"], stats["podcasts_heard"], stats["episodes_heard"]) == (2, 3, 2, 3)
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


def test_a_title_is_in_the_language_of_its_letters(imported: webtest.TestApp, engine: Engine) -> None:
    assert languages.script_of("שיחות על תורת המשחקים: אסטרטגיות") == "Hebrew"
    assert languages.script_of("C++ בעברית למתחילים") == "Hebrew"
    assert languages.script_of("1984") == ""
    with Session(engine) as session:
        locales = languages.known(session)
    # the table starts with the languages of the code, in their order
    assert [(code, locale.name, locale.script) for code, locale in locales.items()] == SEED_LOCALES
    assert [languages.locale_of(locales, text) for text in ("בעלת הארמון", "Война и мир", "Emma", "源氏物語")] == ["he", "ru", "en", ""]
    assert languages.fits(locales["yi"], "בעלת הארמון") and languages.fits(locales["fr"], "Émile") and languages.fits(locales["he"], "1984")
    assert not languages.fits(locales["en"], "בעלת הארמון") and not languages.fits(locales["he"], "Emma")
    config = imported.get("/api/config").json
    assert list(config["locales"].items())[:2] == [("en", "English"), ("he", "Hebrew")]
    assert imported.get("/api/config").json["locale_scripts"]["he"] == "Hebrew"
    # a Hebrew title that says English is refused, and with no language said it is Hebrew
    response = imported.post_json("/api/library-entries", {"kind": "book", "title": "בעלת הארמון", "title_locale": "en"}, status=400)
    assert "not written in English" in response.json["error"]
    book = imported.post_json("/api/library-entries", {"kind": "book", "title": "בעלת הארמון"}).json
    assert book["title_locale"] == "he"
    assert imported.post_json("/api/library-entries", {"kind": "book", "title": "Emma"}).json["title_locale"] == "en"
    # its other titles are held to the same
    response = imported.post_json("/api/library-entries", {"kind": "book", "title": "Persuasion", "titles": [{"locale": "en", "title": "הטיה"}]}, status=400)
    assert "not written in English" in response.json["error"]


def test_fix_languages(imported: webtest.TestApp, engine: Engine) -> None:
    """ What was kept before the forms checked: the check lists it, the script sets the language its letters say. """
    def problems(name: str) -> list[str]:
        with Session(engine) as session:
            return [p.message for p in checks.CHECKS[name].run(session).problems]

    book = imported.post_json("/api/library-entries", {"kind": "book", "title": "Games"}).json
    other = imported.post_json("/api/library-entries", {"kind": "book", "title": "Decisions", "titles": [{"locale": "he", "title": "משחקים"}]}).json
    person = imported.get("/api/people").json[0]
    with Session(engine) as session:
        work, second = session.get(Work, book["work_id"]), session.get(Work, other["work_id"])
        assert work is not None and second is not None
        work.title, second.titles[0].locale = "שיחות על תורת המשחקים", "fr"
        session.add(PersonName(person_id=person["id"], locale="ru", name="חיים שפירא"))
        session.commit()
    assert sorted(problems("book-title-languages")) == [
        "the title 'משחקים' says French but is written in Hebrew letters",
        "the title 'שיחות על תורת המשחקים' says English but is written in Hebrew letters",
    ]
    assert problems("people-name-languages") == ["the name 'חיים שפירא' says Russian but is written in Hebrew letters"]
    with Session(engine) as session:
        assert fix_languages.fix(session) == (3, 0)
        session.commit()
        assert fix_languages.fix(session) == (0, 0)
    assert problems("book-title-languages") == problems("people-name-languages") == []
    fixed = {e["work_id"]: e for e in imported.get("/api/library-entries?kind=book").json}
    assert (fixed[book["work_id"]]["title_locale"], fixed[other["work_id"]]["titles"]) == ("he", [{"locale": "he", "title": "משחקים"}])


def test_book_title_checks(imported: webtest.TestApp, engine: Engine) -> None:
    """ A book has a title, and one with a Hebrew title has an English one too. """
    def problems(name: str) -> list[tuple[str, str]]:
        with Session(engine) as session:
            result = checks.CHECKS[name].run(session)
            return [(p.subject.split(" (")[0], p.message) for p in result.problems]

    before = len(problems("book-english-titles"))
    imported.post_json("/api/library-entries", {"kind": "book", "title": "Emma"})
    imported.post_json("/api/library-entries", {"kind": "book", "title": "Games", "titles": [{"locale": "he", "title": "משחקים"}]})
    hebrew = imported.post_json("/api/library-entries", {"kind": "book", "title": "בעלת הארמון"}).json
    assert problems("book-titles") == []
    # a Hebrew title alone is listed, whether or not it is the main one; a book with no Hebrew title is not looked at
    assert problems("book-english-titles")[before:] == [("בעלת הארמון", "has a Hebrew title but no English one")]
    imported.put_json(f"/api/library-entries/{hebrew['work_id']}", {"titles": [{"locale": "en", "title": "Lady of the Castle"}]})
    assert len(problems("book-english-titles")) == before
    with Session(engine) as session:
        work = session.get(Work, hebrew["work_id"])
        assert work is not None
        work.title = " "
        session.commit()
    assert problems("book-titles") == [(" ", "has no title")]


def named(locale: str, first: str, surname: str, middle: str = "", honorific: str = "") -> dict[str, str]:
    """ A person's name in a language as the API gives it: the parts, and the whole. """
    name = " ".join(part for part in (honorific, first, middle, surname) if part)
    return {"locale": locale, "name": name, "honorific": honorific, "first_name": first, "middle_name": middle, "surname": surname}


def reading(**said: object) -> dict[str, object]:
    """ A reading as the API gives it: what is said, and the rest as it is when not. """
    return {"date": None, "locale": "", "status": "done", "rating": None, "review": "", "started_on": None, **said}


def test_reads(imported: webtest.TestApp) -> None:
    """ A book has a list of readings, each with its day and its language. """
    book = imported.post_json("/api/library-entries", {"kind": "book", "title": "Read Twice", "reads": [
        {"date": "2001-05-01", "locale": "he"}, {"date": "", "locale": "en"}, {"date": "1999-01-01", "locale": ""},
    ]}).json
    assert book["reads"] == [reading(date="2001-05-01", locale="he"), reading(locale="en"), reading(date="1999-01-01")]
    # the entry goes by its latest dated reading
    assert (book["locale"], book["finished_on"]) == ("he", "2001-05-01")
    url = f"/api/library-entries/{book['work_id']}"
    # readings not sent stay; finished_on and locale alone change the reading it goes by
    kept = imported.put_json(url, {"notes": "kept"}).json
    assert kept["reads"] == book["reads"]
    changed = imported.put_json(url, {"locale": "en", "finished_on": "2002-02-02"}).json
    assert changed["reads"][0] == reading(date="2002-02-02", locale="en") and len(changed["reads"]) == 3
    # readings sent replace them all, and none is a book with no reading: wanted
    assert imported.put_json(url, {"reads": [{"locale": "he"}]}).json["reads"] == [reading(locale="he")]
    none = imported.put_json(url, {"reads": []}).json
    assert (none["reads"], none["locale"], none["finished_on"], none["status"], none["rating"], none["review"]) == ([], "", None, "wishlist", None, "")
    # a reading of the old fields is made when there is none
    assert imported.put_json(url, {"notes": "still none"}).json["reads"] == []
    assert imported.put_json(url, {"locale": "he"}).json["reads"] == [reading(locale="he")]
    for wrong in ({"reads": "he"}, {"reads": [{"locale": "xx"}]}, {"reads": [{"date": "yesterday"}]}, {"locale": "xx"}):
        imported.put_json(url, wrong, status=400)
    # the readings go with the entry
    imported.delete(url)
    assert all(e["work_id"] != book["work_id"] for e in imported.get("/api/library-entries?kind=book").json)


def test_a_book_has_covers(imported: webtest.TestApp, engine: Engine) -> None:
    """ A book may have several covers; the first is the one its card shows, and the check asks for at least one. """
    first, second, third = (imported.post("/api/images", upload_files=[("file", f"cover{n}.jpg", JPEG + bytes([n]))]).json["id"] for n in range(3))
    book = imported.post_json("/api/library-entries", {"kind": "book", "title": "Two Editions", "covers": [first, second]}).json
    assert (book["image"], [c["id"] for c in book["covers"]]) == (f"/api/images/{first}", [first, second])
    assert [c["image"] for c in book["covers"]] == [f"/api/images/{first}", f"/api/images/{second}"]
    url = f"/api/library-entries/{book['work_id']}"
    # covers not sent stay; image_id alone is a new first cover
    assert [c["id"] for c in imported.put_json(url, {"rating": 7}).json["covers"]] == [first, second]
    assert [c["id"] for c in imported.put_json(url, {"image_id": third}).json["covers"]] == [third, second]
    # covers sent are all of them, in their order: the first taken away, the next is the one shown
    kept = imported.put_json(url, {"covers": [second, first]}).json
    assert (kept["image"], [c["id"] for c in kept["covers"]]) == (f"/api/images/{second}", [second, first])
    only = imported.put_json(url, {"covers": [first]}).json
    assert (only["image"], [c["id"] for c in only["covers"]]) == (f"/api/images/{first}", [first])
    for wrong in ({"covers": first}, {"covers": [first, first]}, {"covers": [999999]}, {"covers": ["x"]}):
        imported.put_json(url, wrong, status=400)

    def uncovered() -> list[str]:
        with Session(engine) as session:
            return [p.subject.split(" (")[0] for p in checks.CHECKS["book-covers"].run(session).problems]

    # at least one cover: a book with one or with several passes, one with none does not
    assert "Two Editions" not in uncovered()
    imported.put_json(url, {"covers": [first, second]})
    assert "Two Editions" not in uncovered()
    none = imported.put_json(url, {"covers": []}).json
    assert (none["image"], none["covers"]) == (None, [])
    assert "Two Editions" in uncovered()
    # the covers go with the entry, and so do images nothing shows any more
    imported.put_json(url, {"covers": [first, second]})
    imported.delete(url)
    with Session(engine) as session:
        assert session.scalars(select(Cover)).all() == []
        assert session.get(Image, second) is None


def test_a_city_has_photos(imported: webtest.TestApp) -> None:
    """ A city may have several photos, each with its credit; the first is the one its card shows. """
    one, two = (imported.post("/api/images", upload_files=[("file", f"city{n}.jpg", JPEG + bytes([n]))]).json["id"] for n in range(2))
    credit = {"image_source": "https://commons.wikimedia.org/wiki/File:Haifa.jpg", "image_license": "CC BY 4.0", "image_author": "Dana"}
    haifa = imported.post_json("/api/cities", {"name": "Haifa", "photos": [{"image_id": one, **credit}, {"image_id": two, "image_author": "Noa"}]}, status=201).json
    assert (haifa["image"], haifa["image_author"]) == (f"/api/images/{one}", "Dana")
    assert haifa["photos"] == [
        {"id": one, "image": f"/api/images/{one}", **credit},
        {"id": two, "image": f"/api/images/{two}", "image_source": "", "image_license": "", "image_author": "Noa"},
    ]
    url = f"/api/cities/{haifa['id']}"
    # photos not sent stay (the one photo and its credit are then the first, as before)
    assert len(imported.put_json(url, {"name": "Haifa", **credit}).json["photos"]) == 2
    # the first taken away: the next is the one shown, with its own credit
    left = imported.put_json(url, {"name": "Haifa", "photos": [{"image_id": two, "image_author": "Noa"}]}).json
    assert (left["image"], left["image_author"], len(left["photos"])) == (f"/api/images/{two}", "Noa", 1)
    none = imported.put_json(url, {"name": "Haifa", "photos": []}).json
    assert (none["image"], none["image_author"], none["photos"]) == (None, "", [])
    for wrong in ("x", [one], [{"image_id": 999999}], [{"image_id": one}, {"image_id": one}]):
        imported.put_json(url, {"name": "Haifa", "photos": wrong}, status=400)


def test_a_picture_can_be_taken_away(imported: webtest.TestApp) -> None:
    upload = imported.post("/api/images", upload_files=[("file", "flag.jpg", JPEG)]).json
    land = imported.post_json("/api/countries", {"name": "Ruritania", "image_id": upload["id"]}, status=201).json
    assert land["image"] == f"/api/images/{upload['id']}"
    url = f"/api/countries/{land['id']}"
    # not sent, it stays; image_remove takes it away
    assert imported.put_json(url, {"name": "Ruritania"}).json["image"] is not None
    assert imported.put_json(url, {"name": "Ruritania", "image_remove": True}).json["image"] is None


def test_titles_of_a_book_are_edited(imported: webtest.TestApp) -> None:
    """ The dialog sends all the titles of a book: one not sent is taken away, one sent replaces the one in its language. """
    book = imported.post_json("/api/library-entries", {"kind": "book", "title": "Thinking", "titles": [{"locale": "he", "title": "חשיבה"}, {"locale": "fr", "title": "Penser"}]}).json
    url = f"/api/library-entries/{book['work_id']}"
    # the French one taken away, the Hebrew one reworded
    edited = imported.put_json(url, {"title": "Thinking", "title_locale": "en", "titles": [{"locale": "he", "title": "לחשוב"}]}).json
    assert (edited["main_title"], edited["titles"]) == ("Thinking", [{"locale": "he", "title": "לחשוב"}])
    # the English one taken away: the Hebrew one is what the work is known by
    hebrew = imported.put_json(url, {"title": "לחשוב", "title_locale": "he", "titles": []}).json
    assert (hebrew["main_title"], hebrew["title_locale"], hebrew["titles"]) == ("לחשוב", "he", [])
    # a book keeps a title, in the language of its letters, one per language, and is not another book
    imported.post_json("/api/library-entries", {"kind": "book", "title": "Other"})
    for wrong, status in (({"title": ""}, 400), ({"title": "לחשוב", "title_locale": "en"}, 400), ({"title": "Other", "title_locale": "en"}, 409),
                          ({"title": "Thinking", "title_locale": "en", "titles": [{"locale": "en", "title": "Thought"}]}, 400)):
        imported.put_json(url, wrong, status=status)


def test_each_reading_has_its_own_status_rating_and_review(imported: webtest.TestApp) -> None:
    """ Where the user is with a book, their rating and their review belong to each reading of it. """
    # a new book has a reading, as that is where its status is
    book = imported.post_json("/api/library-entries", {"kind": "book", "title": "Read Twice", "status": "wishlist"}).json
    assert book["reads"] == [{"date": None, "locale": "", "status": "wishlist", "rating": None, "review": "", "started_on": None}]
    assert (book["status"], book["rating"], book["review"]) == ("wishlist", None, "")
    url = f"/api/library-entries/{book['work_id']}"
    # two readings, each with what was thought then
    first = {"date": "2001-05-01", "locale": "he", "status": "done", "rating": 6, "review": "slow", "started_on": "2001-04-01"}
    second = {"date": "2020-02-02", "locale": "en", "status": "done", "rating": 9, "review": "better the second time", "started_on": None}
    book = imported.put_json(url, {"reads": [first, second]}).json
    assert book["reads"] == [first, second]
    # the book goes by its latest reading
    assert (book["status"], book["rating"], book["review"], book["finished_on"]) == ("done", 9, "better the second time", "2020-02-02")
    # one being read now is the one it goes by; its rating is still that of the latest reading rated
    again = {"date": None, "locale": "en", "status": "in_progress", "rating": None, "review": "", "started_on": "2026-01-01"}
    book = imported.put_json(url, {"reads": [first, second, again]}).json
    assert (book["status"], book["rating"], book["review"], book["started_on"]) == ("in_progress", 9, "better the second time", "2026-01-01")
    # sent without the readings, they are those of the reading it goes by, each only when sent
    book = imported.put_json(url, {"rating": 5}).json
    assert [(r["status"], r["rating"], r["review"]) for r in book["reads"]] == [("done", 6, "slow"), ("done", 9, "better the second time"), ("in_progress", 5, "")]
    assert imported.put_json(url, {"notes": "on the top shelf"}).json["reads"] == book["reads"]
    # a status not known, a rating out of range
    imported.put_json(url, {"reads": [{"status": "lost"}]}, status=400)
    imported.put_json(url, {"reads": [{"rating": 11}]}, status=400)
    assert imported.put_json(url, {"reads": [{}]}).json["reads"] == [{"date": None, "locale": "", "status": "done", "rating": None, "review": "", "started_on": None}]


def test_a_book_is_owned_in_languages(imported: webtest.TestApp, engine: Engine) -> None:
    """ A book has the languages it is owned in, a list; the notes that said so give it and lose the sentence. """
    book = imported.post_json("/api/library-entries", {"kind": "book", "title": "On The Shelf", "owned": ["he", "en", "he"]}).json
    assert book["owned"] == ["he", "en"]
    url = f"/api/library-entries/{book['work_id']}"
    # not sent, they stay; sent, they are all of them
    assert imported.put_json(url, {"notes": "kept"}).json["owned"] == ["he", "en"]
    assert imported.put_json(url, {"owned": ["en"]}).json["owned"] == ["en"]
    assert imported.put_json(url, {"owned": []}).json["owned"] == []
    for wrong in ({"owned": "he"}, {"owned": ["xx"]}, {"owned": [1]}):
        imported.put_json(url, wrong, status=400)
    # what the notes say of ownership, as the import once wrote it
    codes = {"english": "en", "hebrew": "he"}
    assert owned_from_notes.split_notes("Read in Hebrew (2001-05-01). Owned in Hebrew. Written in Hebrew", codes) == (["he"], "Read in Hebrew (2001-05-01). Written in Hebrew")
    assert owned_from_notes.split_notes("Owned in English and Hebrew", codes) == (["en", "he"], "")
    assert owned_from_notes.split_notes("Publisher: x. Owned in English", codes) == (["en"], "Publisher: x")
    # anything else is left as it is: a language not known, the user's own words
    assert owned_from_notes.split_notes("Owned in Klingon", codes) == ([], "Owned in Klingon")
    assert owned_from_notes.split_notes("I owned it in my youth", codes) == ([], "I owned it in my youth")
    imported.put_json(url, {"notes": "Owned in Hebrew. on the top shelf", "owned": ["en"]})
    with Session(engine) as session:
        assert owned_from_notes.derive(session) == 1
        session.commit()
        assert owned_from_notes.derive(session) == 0
    [after] = [b for b in imported.get("/api/library-entries?kind=book").json if b["work_id"] == book["work_id"]]
    assert (after["owned"], after["notes"]) == (["en", "he"], "on the top shelf")


def test_notes_lose_what_the_book_says_elsewhere(imported: webtest.TestApp, engine: Engine) -> None:
    """ The readings the notes list become readings, a name that is a title goes, and the rest of the notes stay. """
    book = imported.post_json("/api/library-entries", {
        "kind": "book", "title": "Said Twice", "reads": [{"date": "2021-04-23", "locale": "en", "rating": 9, "review": "great"}],
        "notes": "Read in English (2021-04-23); Hebrew (2006-08-19, rated 8, very good). Written in French. was named: said twice. Publisher: x",
    }).json
    other = imported.post_json("/api/library-entries", {
        "kind": "book", "title": "Kept", "locale": "he", "notes": "Read in Hebrew (date unknown). was named: Kept Once. on the top shelf",
    }).json
    with Session(engine) as session:
        changed, gained, left = tidy_book_notes.tidy(session)
        session.commit()
        assert (gained, left) == (1, 0) and changed >= 2
        assert tidy_book_notes.tidy(session) == (0, 0, 0)
    books = {b["work_id"]: b for b in imported.get("/api/library-entries?kind=book").json}
    after = books[book["work_id"]]
    assert after["notes"] == "Written in French. Publisher: x"
    assert after["reads"] == [reading(date="2021-04-23", locale="en", rating=9, review="great"), reading(date="2006-08-19", locale="he", rating=8, review="very good")]
    # it still goes by the reading it went by
    assert (after["rating"], after["review"], after["locale"]) == (9, "great", "en")
    assert (books[other["work_id"]]["notes"], books[other["work_id"]]["reads"]) == ("was named: Kept Once. on the top shelf", [reading(locale="he")])


def test_alone_and_owned_in_none(imported: webtest.TestApp) -> None:
    # a concert gone to alone says so, never with people in With
    person = imported.post_json("/api/people", {"first_name": "Carol"}, status=201).json
    assert imported.post_json("/api/concert-visits", {"name": "Solo", "alone": True}, status=201).json["alone"] is True
    assert imported.post_json("/api/concert-visits", {"name": "Duo", "people": [person["id"]]}, status=201).json["alone"] is False
    imported.post_json("/api/concert-visits", {"name": "Odd", "alone": True, "people": [person["id"]]}, status=400)
    # a book owned in no language is one the user owns no copy of: nothing more says so
    book = imported.post_json("/api/library-entries", {"kind": "book", "title": "Borrowed"}).json
    assert book["owned"] == [] and "not_owned" not in book
    url = f"/api/library-entries/{book['work_id']}"
    assert imported.put_json(url, {"owned": ["en"]}).json["owned"] == ["en"]
    assert imported.put_json(url, {"notes": "x"}).json["owned"] == ["en"]
    assert imported.put_json(url, {"owned": []}).json["owned"] == []


def test_a_name_that_is_the_title() -> None:
    same = notes.same_title
    # a part of the title, the title but for its spelling, its punctuation, a leading article or an & for an and
    assert same("The Blind Watchmaker", ["The Blind Watchmaker: Why the Evidence of Evolution Reveals a Universe Without Design"])
    assert same("The Strange Case of Dr. Jekyll and Mr. Hyde", ["Strange Case Of Dr. Jekyll & Mr. Hyde"])
    assert same("Ulysees", ["Ulysses"]) and same("Godel, Escher & Bach", ["Gödel, Escher, Bach: An Eternal Golden Braid"])
    assert same("Guide to Movies and Videos 1996", ["Blockbuster Video Guide to Movies and Videos 1996"])
    # another name is not the title
    assert not same("Kufsa Shora", ["Black Box"]) and not same("Pipes", ["Pipelines"]) and not same("", ["Dune"])


def test_languages_are_a_page(imported: webtest.TestApp, engine: Engine) -> None:
    """ The locales table is listed, and kept by an admin: a language is added, renamed, and deleted only when nothing is said in it. """
    listed = imported.get("/api/locales").json
    assert [(row["code"], row["name"], row["script"]) for row in listed][:2] == [("en", "English", "Latin"), ("he", "Hebrew", "Hebrew")]
    assert all(row["count"] >= 0 for row in listed) and len({row["id"] for row in listed}) == len(listed)
    assert imported.get("/api/stats").json["locales"] == len(listed)
    # each has a picture: what it is called in itself, in its own script, drawn
    hebrew = listed[1]
    assert hebrew["native"] == "עברית" and hebrew["image"].startswith(f"/api/locales/{hebrew['id']}/picture.svg?v=")
    picture = imported.get(hebrew["image"])
    assert picture.content_type == "image/svg+xml" and "עברית" in picture.text and "<script" not in picture.text
    # every language is drawn on the same ground, whatever its script
    grounds = {imported.get(row["image"]).text.split('<rect width="400" height="300" fill="')[1][:7] for row in listed}
    assert len(grounds) == 1 and len({row["script"] for row in listed}) > 1
    with Session(engine) as session:
        me = owner(session)
        role, me.role = me.role, "user"
        session.commit()
    # everyone sees them, only an admin changes them
    imported.post_json("/api/locales", {"code": "nl", "name": "Dutch", "script": "Latin"}, status=403)
    with Session(engine) as session:
        owner(session).role = "admin"
        session.commit()
    dutch = imported.post_json("/api/locales", {"code": "NL", "name": "Dutch", "script": "latin"}, status=201).json
    assert (dutch["code"], dutch["name"], dutch["script"], dutch["count"]) == ("nl", "Dutch", "Latin", 0)
    assert imported.get("/api/config").json["locales"]["nl"] == "Dutch"
    url = f"/api/locales/{dutch['id']}"
    for wrong, status in (
        ({"code": "nl", "name": "Other", "script": "Latin"}, 409), ({"code": "x", "name": "X", "script": "Latin"}, 400),
        ({"code": "xx", "name": "English", "script": "Latin"}, 409), ({"code": "xx", "name": "X", "script": "Runes of Mine"}, 400),
        ({"code": "xx", "name": "", "script": "Latin"}, 400),
    ):
        imported.post_json("/api/locales", wrong, status=status)
    # its own name is in its own script, and its picture shows it (escaped), at a new address
    imported.put_json(url, {"code": "nl", "name": "Dutch", "script": "Latin", "native": "עברית"}, status=400)
    named = imported.put_json(url, {"code": "nl", "name": "Dutch", "script": "Latin", "native": "Neder<lands"}).json
    assert named["native"] == "Neder<lands" and named["image"] != dutch["image"]
    assert "Neder&lt;lands" in imported.get(named["image"]).text
    with Session(engine) as session:
        assert checks.CHECKS["locale-native-names"].run(session).problems == []
        session.scalars(select(Locale).where(Locale.code == "nl")).one().native = ""
        session.commit()
        assert [p.message for p in checks.CHECKS["locale-native-names"].run(session).problems] == ["does not say what it is called in itself"]
    # renamed; its code stays
    assert imported.put_json(url, {"code": "nl", "name": "Nederlands", "script": "Latin"}).json["name"] == "Nederlands"
    imported.put_json(url, {"code": "du", "name": "Dutch", "script": "Latin"}, status=400)
    # used, it stays; unused, it goes; English always stays
    book = imported.post_json("/api/library-entries", {"kind": "book", "title": "Kept", "owned": ["nl"]}).json
    assert next(row for row in imported.get("/api/locales").json if row["code"] == "nl")["count"] == 1
    imported.delete(url, status=409)
    imported.put_json(f"/api/library-entries/{book['work_id']}", {"owned": []})
    imported.delete(url, status=204)
    imported.delete(f"/api/locales/{listed[0]['id']}", status=409)
    imported.delete("/api/locales/999", status=404)
    with Session(engine) as session:
        owner(session).role = role
        session.commit()
        assert checks.CHECKS["locale-scripts"].run(session).problems == []


def test_a_person_has_photos(imported: webtest.TestApp, engine: Engine) -> None:
    """ A person may have several photos, each with its credit; the first is the default, the one their card shows. """
    first, second = (imported.post("/api/images", upload_files=[("file", f"face{n}.jpg", JPEG + bytes([40 + n]))]).json["id"] for n in range(2))
    ann = imported.post_json("/api/people", {"first_name": "Ann", "photos": [
        {"image_id": first, "image_source": "https://example.com/ann", "image_license": "CC BY 4.0", "image_author": "Bo"}, {"image_id": second},
    ]}, status=201).json
    assert (ann["image"], [p["id"] for p in ann["photos"]]) == (f"/api/images/{first}", [first, second])
    assert (ann["photos"][0]["image_source"], ann["photos"][0]["image_license"], ann["photos"][0]["image_author"]) == ("https://example.com/ann", "CC BY 4.0", "Bo")
    url = f"/api/people/{ann['id']}"
    # photos not sent stay; sent in another order, the first is the default, and each keeps its credit
    assert [p["id"] for p in imported.put_json(url, {"first_name": "Ann"}).json["photos"]] == [first, second]
    third = imported.post("/api/images", upload_files=[("file", "face2.jpg", JPEG + bytes([42]))]).json["id"]
    swapped = imported.put_json(url, {"first_name": "Ann", "photos": [{"image_id": second}, {**ann["photos"][0], "image_id": first}, {"image_id": third}]}).json
    assert (swapped["image"], [p["id"] for p in swapped["photos"]]) == (f"/api/images/{second}", [second, first, third])
    assert swapped["photos"][1]["image_author"] == "Bo"
    for wrong in ({"photos": [{"image_id": first}, {"image_id": first}]}, {"photos": [{"image_id": 10**9}]}, {"photos": "x"}):
        imported.put_json(url, {"first_name": "Ann", **wrong}, status=400)
    # one taken away goes, with its image
    assert [p["id"] for p in imported.put_json(url, {"first_name": "Ann", "photos": [{"image_id": third}]}).json["photos"]] == [third]
    with Session(engine) as session:
        assert session.get(Image, first) is None and session.get(Image, third) is not None
    assert imported.put_json(url, {"first_name": "Ann", "photos": []}).json["image"] is None


def test_authors_of_hebrew_books_have_hebrew_names(imported: webtest.TestApp, engine: Engine) -> None:
    def problems() -> list[tuple[str, str]]:
        with Session(engine) as session:
            return [(p.subject.split(" (")[0], p.message) for p in checks.CHECKS["people-hebrew-names"].run(session).problems]

    before = problems()
    amos = imported.post_json("/api/people", {"first_name": "Amos", "surname": "Oz"}, status=201).json
    ann = imported.post_json("/api/people", {"first_name": "Ann", "surname": "Lee"}, status=201).json
    # a book with a Hebrew title, and one without: only the first asks its author for a Hebrew name
    imported.post_json("/api/library-entries", {"kind": "book", "title": "My Michael", "titles": [{"locale": "he", "title": "מיכאל שלי"}], "authors": [amos["id"]]})
    imported.post_json("/api/library-entries", {"kind": "book", "title": "Plain", "authors": [ann["id"]]})
    assert problems() == [*before, ("Amos Oz", "wrote My Michael, which has a Hebrew title, but has no Hebrew name")]
    imported.put_json(f"/api/people/{amos['id']}", {"first_name": "Amos", "surname": "Oz", "names": [{"locale": "he", "name": "עמוס עוז"}]})
    assert problems() == before


def test_every_person_has_an_english_name(imported: webtest.TestApp, engine: Engine) -> None:
    def problems() -> list[tuple[str, str]]:
        with Session(engine) as session:
            return [(p.subject.split(" (")[0], p.message) for p in checks.CHECKS["people-english-names"].run(session).problems]

    assert problems() == []
    # someone whose name is not known has a description instead
    nameless = imported.post_json("/api/people", {"first_name": "", "description": "A red-headed guitarist"}, status=201).json
    imported.post_json("/api/people", {"first_name": "חיים", "surname": "שפירא"}, status=201)
    assert problems() == [("חיים שפירא", "the name is written in Hebrew letters, not in English")]
    with Session(engine) as session:
        person = session.get(Person, nameless["id"])
        assert person is not None
        person.description = " "
        session.commit()
    assert sorted(message for _, message in problems()) == ["has neither a name nor a description", "the name is written in Hebrew letters, not in English"]
