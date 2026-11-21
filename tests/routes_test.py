"""
The routes every page of the world has (myworld/world.py): one table of
views drives adding, editing and deleting, so each page is put through the
same steps here. Also the dates, which several pages share.
"""

from typing import Any

import pytest
import webtest
from sqlalchemy.engine import Engine

from myworld.models import is_shared
from myworld.world import VIEWS
from tests.conftest import sign_in, sign_in_admin

# what a row is called after its edit, where the edit does not say a name
NAMED = {"people": "Dana Levi", "chess-games": "me vs Deeper Blue"}

# the least a row of each page can be added with, and what an edit changes it to
MINIMAL: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "concert-visits": ({"name": "Jarrett"}, {"name": "Jarrett Trio"}),
    "audio-courses": ({"name": "Logic"}, {"name": "Logic 101"}),
    "audio-books": ({"name": "Dune"}, {"name": "Dune Messiah"}),
    "podcasts": ({"name": "Mindscape"}, {"name": "Mindscape 2"}),
    # and the podcast it is of, which minimal() adds first
    "podcast-episodes": ({"name": "Trailer"}, {"name": "The trailer"}),
    "youtube-videos": ({"youtube_id": "dQw4w9WgXcQ", "name": "A song"}, {"youtube_id": "dQw4w9WgXcQ", "name": "That song"}),
    # a game is added by its text and named by its players: an edit that sends another text renames it
    "chess-games": (
        {"pgn": '[White "me"]\n[Black "Deep Blue"]\n[Result "1-0"]\n\n1. e4 e5 1-0', "color": "white"},
        {"pgn": '[White "me"]\n[Black "Deeper Blue"]\n[Result "1-0"]\n\n1. e4 e5 1-0', "color": "white"},
    ),
    "people": ({"first_name": "Dana"}, {"first_name": "Dana", "surname": "Levi"}),
    "organizations": ({"name": "ACME"}, {"name": "ACME Ltd"}),
    "places": ({"name": "Barby"}, {"name": "The Barby"}),
    "groups": ({"name": "Trio"}, {"name": "The Trio"}),
    "cities": ({"name": "Haifa"}, {"name": "Hefa"}),
    "countries": ({"name": "Israel"}, {"name": "State of Israel"}),
    "currencies": ({"code": "ILS", "name": "Shekel"}, {"code": "ILS", "name": "New Shekel"}),
    "place-kinds": ({"name": "Lecture hall"}, {"name": "Auditorium"}),
    "visit-types": ({"name": "Lecture"}, {"name": "Talk"}),
}


def minimal(app: webtest.TestApp, path: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """ MINIMAL[path], with what the row needs there to be first (an episode, its podcast) added to the signed-in account. """
    first, changed = MINIMAL[path]
    if path == "podcast-episodes":
        podcast = {"podcast_id": app.post_json("/api/podcasts", {"name": "Mindscape"}, status=201).json["id"]}
        return {**first, **podcast}, {**changed, **podcast}
    return first, changed


def test_every_view_is_tried() -> None:
    assert set(MINIMAL) == set(VIEWS)


@pytest.mark.parametrize("path", sorted(VIEWS))
def test_add_edit_delete(app: webtest.TestApp, engine: Engine, path: str) -> None:
    # what everyone shares is changed by an admin
    sign_in_admin(app, engine)
    first, changed = minimal(app, path)
    # (place kinds and visit types start with those there always are)
    there = [row["id"] for row in app.get(f"/api/{path}").json]
    added = app.post_json(f"/api/{path}", first, status=201).json
    assert added["name"] == first.get("name", added["name"])
    assert sorted(row["id"] for row in app.get(f"/api/{path}").json) == sorted([*there, added["id"]])
    edited = app.put_json(f"/api/{path}/{added['id']}", changed).json
    assert edited["id"] == added["id"]
    wanted = changed.get("name", NAMED.get(path))
    assert edited["name"] == wanted
    assert wanted in [row["name"] for row in app.get(f"/api/{path}").json]
    app.delete(f"/api/{path}/{added['id']}", status=204)
    assert [row["id"] for row in app.get(f"/api/{path}").json] == there
    # gone is gone: neither edited nor deleted again
    app.put_json(f"/api/{path}/{added['id']}", changed, status=404)
    app.delete(f"/api/{path}/{added['id']}", status=404)


@pytest.mark.parametrize("path", sorted(path for path, view in VIEWS.items() if not is_shared(view.model)))
def test_a_row_is_its_owners(app: webtest.TestApp, path: str) -> None:
    sign_in(app)
    first, changed = minimal(app, path)
    row_id = app.post_json(f"/api/{path}", first, status=201).json["id"]
    sign_in(app, sub="someone-else")
    assert app.get(f"/api/{path}").json == []
    assert app.put_json(f"/api/{path}/{row_id}", changed, status=404).json == {"error": "no such entry"}
    app.delete(f"/api/{path}/{row_id}", status=404)
    # and the other account may have one of the same name (of its own podcast)
    app.post_json(f"/api/{path}", minimal(app, path)[0], status=201)
    sign_in(app)
    assert [row["id"] for row in app.get(f"/api/{path}").json] == [row_id]


@pytest.mark.parametrize("path", sorted(VIEWS))
def test_a_body_is_a_json_object(app: webtest.TestApp, engine: Engine, path: str) -> None:
    sign_in_admin(app, engine)
    there = app.get(f"/api/{path}").json
    assert app.post_json(f"/api/{path}", ["Jarrett"], status=400).json == {"error": "expected a JSON object"}
    assert app.post(f"/api/{path}", "name=Jarrett", status=400).json == {"error": "expected a JSON object"}
    # nothing was added by a body that was refused
    assert app.post_json(f"/api/{path}", {}, status=400).json["error"]
    assert app.get(f"/api/{path}").json == there


@pytest.mark.parametrize("path", sorted(VIEWS))
def test_signed_out(app: webtest.TestApp, path: str) -> None:
    app.get(f"/api/{path}", status=401)
    app.post_json(f"/api/{path}", MINIMAL[path][0], status=401)
    app.put_json(f"/api/{path}/1", MINIMAL[path][0], status=401)
    app.delete(f"/api/{path}/1", status=401)


def test_a_page_that_is_not_one(app: webtest.TestApp) -> None:
    sign_in(app)
    app.post_json("/api/unicorns", {"name": "Bob"}, status=404)
    app.put_json("/api/unicorns/1", {"name": "Bob"}, status=404)
    app.delete("/api/unicorns/1", status=404)


@pytest.mark.parametrize("path", ["concert-visits", "audio-courses", "podcast-episodes", "youtube-videos"])
@pytest.mark.parametrize(("date", "precision", "sort"), [
    ("2003", "year", "2003"),
    ("2003-07", "month", "2003-07"),
    ("2003-07-14", "day", "2003-07-14"),
    ("", None, ""),
])
def test_a_date_is_as_exact_as_it_is_known(app: webtest.TestApp, path: str, date: str, precision: str | None, sort: str) -> None:
    sign_in(app)
    first = minimal(app, path)[0]
    added = app.post_json(f"/api/{path}", {**first, "date": date, "date_timezone": "Asia/Jerusalem"}, status=201).json
    assert (added["date"], added["date_precision"], added["date_sort"]) == (date or None, precision, sort)
    assert added["date_timezone"] == "Asia/Jerusalem"
    # sent back as it is shown, it stays; sent empty, it goes
    kept = app.put_json(f"/api/{path}/{added['id']}", {**first, "date": date}).json
    assert (kept["date"], kept["date_precision"], kept["date_timezone"]) == (date or None, precision, "")
    cleared = app.put_json(f"/api/{path}/{added['id']}", {**first, "date": ""}).json
    assert (cleared["date"], cleared["date_precision"], cleared["date_sort"]) == (None, None, "")


@pytest.mark.parametrize(("body", "error"), [
    ({"date": "2003-13"}, "date: no such month"),
    ({"date": "2003-00"}, "date: no such month"),
    ({"date": "2003-02-30"}, "date: expected YYYY, YYYY-MM or YYYY-MM-DD"),
    ({"date": "July 2003"}, "date: expected YYYY, YYYY-MM or YYYY-MM-DD"),
    ({"date": "03"}, "date: expected YYYY, YYYY-MM or YYYY-MM-DD"),
    ({"date": 2003}, "date: expected a string"),
    ({"date": "2003", "date_timezone": "Mars/Olympus"}, "date_timezone: unknown time zone 'Mars/Olympus'"),
])
def test_a_date_that_is_not_one(app: webtest.TestApp, body: dict[str, Any], error: str) -> None:
    sign_in(app)
    assert app.post_json("/api/concert-visits", {"name": "Jarrett", **body}, status=400).json == {"error": error}
    assert app.get("/api/concert-visits").json == []


def test_a_precision_replaces_another(app: webtest.TestApp) -> None:
    sign_in(app)
    concert = app.post_json("/api/concert-visits", {"name": "Jarrett", "date": "2003-07-14"}, status=201).json
    for date, precision in (("2003-07", "month"), ("2003", "year"), ("2004-01-02", "day")):
        concert = app.put_json(f"/api/concert-visits/{concert['id']}", {"name": "Jarrett", "date": date}).json
        assert (concert["date"], concert["date_precision"]) == (date, precision)


@pytest.mark.parametrize("path", sorted(path for path, view in VIEWS.items() if is_shared(view.model)))
def test_only_an_admin_changes_what_everyone_shares(app: webtest.TestApp, engine: Engine, path: str) -> None:
    sign_in_admin(app, engine, sub="the-admin")
    first, changed = MINIMAL[path]
    added = app.post_json(f"/api/{path}", first, status=201).json
    sign_in(app)
    # everyone sees it
    assert added["id"] in [row["id"] for row in app.get(f"/api/{path}").json]
    forbidden = {"error": "this is shared by everyone: only an admin may change it"}
    assert app.post_json(f"/api/{path}", changed, status=403).json == forbidden
    assert app.put_json(f"/api/{path}/{added['id']}", changed, status=403).json == forbidden
    assert app.delete(f"/api/{path}/{added['id']}", status=403).json == forbidden


@pytest.mark.parametrize("path", sorted(path for path, view in VIEWS.items() if is_shared(view.model)))
def test_an_admin_changes_shared_data_only_with_edit_shared_on(app: webtest.TestApp, engine: Engine, path: str) -> None:
    sign_in_admin(app, engine, sub="the-admin")
    first, changed = MINIMAL[path]
    added = app.post_json(f"/api/{path}", first, status=201).json
    # an admin starts locked, so shared data is not changed by accident
    sign_in_admin(app, engine, sub="the-admin", edit_shared=False)
    locked = {"error": "this is shared by everyone: turn on Edit shared data in Settings to change it"}
    assert app.post_json(f"/api/{path}", changed, status=403).json == locked
    assert app.put_json(f"/api/{path}/{added['id']}", changed, status=403).json == locked
    assert app.delete(f"/api/{path}/{added['id']}", status=403).json == locked
    # Settings turns it on
    assert app.put_json("/api/account/edit-shared", {"edit_shared": True}).json["edit_shared"] is True
    app.put_json(f"/api/{path}/{added['id']}", changed)


def test_only_an_admin_turns_edit_shared_on(app: webtest.TestApp) -> None:
    sign_in(app)
    assert app.get("/api/config").json["user"]["edit_shared"] is False
    assert app.put_json("/api/account/edit-shared", {"edit_shared": True}, status=403).json == {"error": "only an admin may change the shared data"}
    assert app.put_json("/api/account/edit-shared", {"edit_shared": "yes"}, status=400).json == {"error": "edit_shared: expected true or false"}


def test_a_users_rows_point_at_shared_ones(app: webtest.TestApp, engine: Engine) -> None:
    sign_in_admin(app, engine, sub="the-admin")
    barby = app.post_json("/api/places", {"name": "Barby"}, status=201).json["id"]
    haifa = app.post_json("/api/cities", {"name": "Haifa"}, status=201).json["id"]
    sign_in(app)
    concert = app.post_json("/api/concert-visits", {"name": "Jarrett", "place_id": barby}, status=201).json
    assert concert["place"]["name"] == "Barby"
    acme = app.post_json("/api/organizations", {"name": "ACME", "headquarters_id": haifa}, status=201).json
    assert acme["headquarters"]["name"] == "Haifa"
    # a shared place shows the user's own concerts there, not another account's
    sign_in(app, sub="someone-else")
    [place] = [p for p in app.get("/api/places").json if p["id"] == barby]
    assert place["concerts"] == []


def test_what_a_row_points_at_is_the_users_own(app: webtest.TestApp) -> None:
    sign_in(app, sub="someone-else")
    theirs = {
        "person": app.post_json("/api/people", {"first_name": "Dana"}, status=201).json["id"],
        "device": app.post_json("/api/devices", {"name": "Phone"}, status=201).json["id"],
        "type": app.post_json("/api/organization-types", {"name": "Company"}, status=201).json["id"],
        "podcast": app.post_json("/api/podcasts", {"name": "Mindscape"}, status=201).json["id"],
    }
    sign_in(app)
    for path, body, error in (
        ("concert-visits", {"name": "Jarrett", "people": [theirs["person"]]}, "people: unknown person"),
        ("concert-visits", {"name": "Jarrett", "people": "Dana"}, "people: expected a list of ids"),
        ("concert-visits", {"name": "Jarrett", "people": [True]}, "people: expected a list of ids"),
        ("organizations", {"name": "ACME", "type_id": theirs["type"]}, "type_id: unknown type"),
        ("audio-courses", {"name": "Logic", "device_id": theirs["device"]}, "device_id: unknown device"),
        ("podcast-episodes", {"name": "Trailer", "podcast_id": theirs["podcast"]}, "podcast_id: unknown podcast"),
        ("organizations", {"name": "ACME", "city_id": "Haifa"}, "city_id: expected a number"),
        ("organizations", {"name": "ACME", "city_id": 999999}, "city_id: unknown city"),
    ):
        assert app.post_json(f"/api/{path}", body, status=400).json == {"error": error}, (path, body)
        assert app.get(f"/api/{path}").json == []


@pytest.mark.parametrize(("path", "body", "error"), [
    ("places", {"name": "Barby"}, "Barby is already in Places"),
    ("groups", {"name": "Trio"}, "Trio is already in Groups"),
    ("countries", {"name": "Israel"}, "Israel is already in Countries"),
    ("cities", {"name": "Haifa"}, "Haifa is already in Cities"),
    ("organizations", {"name": "ACME"}, "ACME is already in Organizations"),
    ("youtube-videos", {"youtube_id": "dQw4w9WgXcQ", "name": "A song"}, "that video is in your list already"),
])
def test_what_is_there_is_not_added_again(app: webtest.TestApp, engine: Engine, path: str, body: dict[str, Any], error: str) -> None:
    sign_in_admin(app, engine)
    first = app.post_json(f"/api/{path}", body, status=201).json
    assert app.post_json(f"/api/{path}", body, status=409).json == {"error": error}
    # saved again as it is, a row does not clash with itself
    app.put_json(f"/api/{path}/{first['id']}", body, status=200)
    assert len(app.get(f"/api/{path}").json) == 1


def test_a_region_is_a_row_its_cities_share(app: webtest.TestApp, engine: Engine) -> None:
    sign_in_admin(app, engine)
    usa = app.post_json("/api/countries", {"name": "USA"}, status=201).json["id"]
    canada = app.post_json("/api/countries", {"name": "Canada"}, status=201).json["id"]
    assert app.get("/api/regions").json == []
    austin = app.post_json("/api/cities", {"name": "Austin", "region": " Texas ", "country_id": usa}, status=201).json
    dallas = app.post_json("/api/cities", {"name": "Dallas", "region": "Texas", "country_id": usa}, status=201).json
    assert (austin["region"], dallas["region"]) == ("Texas", "Texas")
    # one row for the two of them; the same name in another country is another region
    london = app.post_json("/api/cities", {"name": "London", "region": "Ontario", "country_id": canada}, status=201).json
    texas, = [region for region in app.get("/api/regions").json if region["name"] == "Texas"]
    assert texas["country"] == {"id": usa, "name": "USA"} and [city["name"] for city in texas["cities"]] == ["Austin", "Dallas"]
    assert [(region["name"], region["country"]["name"]) for region in app.get("/api/regions").json] == [("Ontario", "Canada"), ("Texas", "USA")]
    # a city is a name once in a region of a country, and once more in another region
    app.post_json("/api/cities", {"name": "Austin", "region": "Texas", "country_id": usa}, status=409)
    app.post_json("/api/cities", {"name": "Austin", "region": "Minnesota", "country_id": usa}, status=201)
    app.post_json("/api/cities", {"name": "Austin", "country_id": usa}, status=201)
    app.post_json("/api/cities", {"name": "Austin", "country_id": usa}, status=409)
    # a city that says no region any more leaves it; the last one out takes the region with it
    assert app.put_json(f"/api/cities/{london['id']}", {"name": "London", "country_id": canada}).json["region"] == ""
    assert "Ontario" not in [region["name"] for region in app.get("/api/regions").json]
    app.delete(f"/api/cities/{dallas['id']}", status=204)
    assert "Texas" in [region["name"] for region in app.get("/api/regions").json]
    app.delete(f"/api/cities/{austin['id']}", status=204)
    assert [region["name"] for region in app.get("/api/regions").json] == ["Minnesota"]
    # they are everyone's
    sign_in(app, sub="someone-else")
    assert [region["name"] for region in app.get("/api/regions").json] == ["Minnesota"]


def test_regions_need_a_session(app: webtest.TestApp) -> None:
    app.get("/api/regions", status=401)
