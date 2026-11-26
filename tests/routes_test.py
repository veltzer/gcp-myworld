"""
The routes every page of the world has (myworld/world.py): one table of
views drives adding, editing and deleting, so each page is put through the
same steps here. Also the dates, which several pages share.
"""

from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld.models import (
    AudioBook,
    AudioBookVersion,
    Film,
    Podcast,
    PodcastEpisode,
    is_shared,
)
from myworld.world import VIEWS
from tests.conftest import sign_in, sign_in_admin

if TYPE_CHECKING:
    import webtest
    from sqlalchemy.engine import Engine

# what a row is called after its edit, where the edit does not say a name
NAMED = {
    "people": "Dana Levi", "chess-games": "me vs Deeper Blue", "podcasts-heard": "Mindscape", "episodes-heard": "Trailer",
    "audio-book-versions": "Free Will (MP3)", "audio-books-heard": "Free Will", "audio-book-listens": "Free Will",
    "film-watches": "Interstellar", "series-watches": "The Leftovers",
}

# the least a row of each page can be added with, and what an edit changes it to
MINIMAL: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "concert-visits": ({"name": "Jarrett"}, {"name": "Jarrett Trio"}),
    "audio-courses": ({"name": "Logic"}, {"name": "Logic 101"}),
    "audio-books": ({"name": "Dune"}, {"name": "Dune Messiah"}),
    # of a shared book, of a shared book, and of a shared version, which minimal() adds first
    "audio-book-versions": ({"kind": "mp3"}, {"kind": "mp3", "minutes": 60, "parts": 3}),
    "audio-books-heard": ({}, {"rating": 7}),
    "audio-book-listens": ({}, {"finished": True, "listened_at": "Car"}),
    "podcasts": ({"name": "Mindscape"}, {"name": "Mindscape 2"}),
    # and the podcast it is of, which minimal() adds first
    "podcast-episodes": ({"name": "Trailer"}, {"name": "The trailer"}),
    # of a shared podcast, and of a shared episode, which minimal() adds first
    "podcasts-heard": ({}, {"rating": 7}),
    "episodes-heard": ({}, {"rating": 7, "listened_at": "Car"}),
    "films": ({"name": "Dune"}, {"name": "Dune: Part One", "year": 2021, "imdb_id": "tt1160419"}),
    # of a shared film, which minimal() adds first
    "film-watches": ({}, {"rating": 8, "watched_at": "Home"}),
    "series": ({"name": "Fauda"}, {"name": "Fauda", "year": 2015, "imdb_id": "tt4565380"}),
    # of a shared series, which minimal() adds first
    "series-watches": ({}, {"rating": 7, "seasons_seen": "1, 2", "seasons_not_seen": [3]}),
    "youtube-videos": ({"youtube_id": "dQw4w9WgXcQ", "name": "A song"}, {"youtube_id": "dQw4w9WgXcQ", "name": "That song"}),
    # a game is added by its text and named by its players: an edit that sends another text renames it
    "chess-games": (
        {"pgn": '[White "me"]\n[Black "Deep Blue"]\n[Result "1-0"]\n\n1. e4 e5 1-0', "color": "white"},
        {"pgn": '[White "me"]\n[Black "Deeper Blue"]\n[Result "1-0"]\n\n1. e4 e5 1-0', "color": "white"},
    ),
    "certifications": ({"name": "AWS Instructor"}, {"name": "AWS Certified Instructor", "kind": "instructor", "date": "2014-02"}),
    "courses": ({"name": "Jazz"}, {"name": "Jazz Improvisation", "date": "2013", "remark": "via Coursera"}),
    "loans": ({"name": "The Hobbit"}, {"name": "The Hobbit", "returned": True, "date": "2010"}),
    "websites": ({"name": "TED", "url": "http://www.ted.com"}, {"name": "TED Talks", "url": "https://www.ted.com", "topic": "Free study"}),
    "trips": ({"name": "Kiev"}, {"name": "Kiev and Lviv", "days": 5, "date": "2016-05-04", "alone": True}),
    "lectures": ({"name": "Nietzsche"}, {"name": "Friedrich Nietzsche", "location": "TalkHouse", "rating": 8, "date": "2016-11"}),
    "rallies": ({"name": "Memorial"}, {"name": "Rabin memorial", "location": "Kikar Rabin", "review": "Not very interesting", "date": "2016"}),
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
    """ MINIMAL[path], with what the row needs there to be first (an episode's podcast, the shared podcast or episode heard). """
    first, changed = MINIMAL[path]
    if path in ("podcast-episodes", "podcasts-heard"):
        podcast = {"podcast_id": shared_episode(app).podcast_id}
        return {**first, **podcast}, {**changed, **podcast}
    if path == "episodes-heard":
        episode = {"episode_id": shared_episode(app).id}
        return {**first, **episode}, {**changed, **episode}
    if path in ("audio-book-versions", "audio-books-heard"):
        book = {"book_id": shared_version(app).book_id}
        return {**first, **book}, {**changed, **book}
    if path == "audio-book-listens":
        version = {"version_id": shared_version(app).id}
        return {**first, **version}, {**changed, **version}
    if path in ("film-watches", "series-watches"):
        film = {"film_id": shared_film(app, series=path == "series-watches").id}
        return {**first, **film}, {**changed, **film}
    return first, changed


def shared_film(app: webtest.TestApp, *, series: bool = False) -> Film:
    """ The shared film Interstellar (or the series The Leftovers), put there as an admin's import would (once). """
    flask_app: Any = app.app
    name, imdb = ("The Leftovers", "tt2699128") if series else ("Interstellar", "tt0816692")
    with Session(flask_app.config["engine"], expire_on_commit=False) as session:
        film = session.scalars(select(Film).where(Film.imdb_id == imdb)).first()
        if film is None:
            film = Film(kind="series" if series else "film", name=name, year=2014, imdb_id=imdb, genres=[])
            session.add(film)
            session.commit()
        return film


def shared_version(app: webtest.TestApp) -> AudioBookVersion:
    """ The shared audio book Free Will's Audible version, put there as an Audible library run would (once). """
    flask_app: Any = app.app
    with Session(flask_app.config["engine"], expire_on_commit=False) as session:
        version = session.scalars(select(AudioBookVersion).where(AudioBookVersion.asin == "B00FW")).first()
        if version is None:
            book = AudioBook(name="Free Will", authors="Sam Harris")
            version = AudioBookVersion(book=book, kind="audible", asin="B00FW")
            session.add(version)
            session.commit()
        return version


def shared_episode(app: webtest.TestApp) -> PodcastEpisode:
    """ The shared podcast Mindscape's episode Trailer, put there as an admin's Podcast feeds run would (once). """
    flask_app: Any = app.app
    with Session(flask_app.config["engine"], expire_on_commit=False) as session:
        episode = session.scalars(select(PodcastEpisode).where(PodcastEpisode.name == "Trailer", PodcastEpisode.guid == "t1")).first()
        if episode is None:
            podcast = session.scalars(select(Podcast).where(Podcast.name == "Mindscape")).first() or Podcast(name="Mindscape")
            episode = PodcastEpisode(podcast=podcast, name="Trailer", guid="t1")
            session.add(episode)
            session.commit()
        return episode


def test_every_view_is_tried() -> None:
    assert set(MINIMAL) == set(VIEWS)


# Your podcasts and Your audio books are added to by hearing an episode or a version, not by adding one (test_your_podcasts, test_your_audio_books)
ADDED = sorted(path for path in VIEWS if path not in ("podcasts-heard", "audio-books-heard"))


@pytest.mark.parametrize("path", ADDED)
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


@pytest.mark.parametrize("path", [path for path in ADDED if not is_shared(VIEWS[path].model)])
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


def test_your_podcasts(app: webtest.TestApp) -> None:
    """ The shared podcasts, filtered to those the user heard an episode of, with their rating and review. """
    sign_in(app)
    first, _ = minimal(app, "podcasts-heard")
    error = "Mindscape is in Your podcasts once you heard an episode of it: add the episode in Episodes heard"
    assert app.post_json("/api/podcasts-heard", first, status=409).json == {"error": error}
    heard = app.post_json("/api/episodes-heard", minimal(app, "episodes-heard")[0], status=201).json
    [mine] = app.get("/api/podcasts-heard").json
    assert (mine["name"], [e["id"] for e in mine["episodes"]], mine["rating"]) == ("Mindscape", [heard["id"]], None)
    app.put_json(f"/api/podcasts-heard/{mine['id']}", {**first, "rating": 7, "review": "Good"})
    # with no episode heard it is not listed, and keeps what the user said of it for when one is heard again
    app.delete(f"/api/episodes-heard/{heard['id']}", status=204)
    assert app.get("/api/podcasts-heard").json == []
    app.post_json("/api/episodes-heard", minimal(app, "episodes-heard")[0], status=201)
    assert [(p["rating"], p["review"]) for p in app.get("/api/podcasts-heard").json] == [(7, "Good")]
    sign_in(app, sub="someone-else")
    assert app.get("/api/podcasts-heard").json == []
    app.put_json(f"/api/podcasts-heard/{mine['id']}", first, status=404)


def test_your_audio_books(app: webtest.TestApp, engine: Engine) -> None:
    """ The shared audio books, filtered to those the user heard a version of, with their rating and review; a book heard stays. """
    sign_in(app)
    first, _ = minimal(app, "audio-books-heard")
    error = "Free Will is in Your audio books once you heard a version of it: add it in Audio book listens"
    assert app.post_json("/api/audio-books-heard", first, status=409).json == {"error": error}
    listen = app.post_json("/api/audio-book-listens", minimal(app, "audio-book-listens")[0], status=201).json
    assert (listen["name"], listen["kind_name"], listen["version"]["name"]) == ("Free Will", "Audible", "Free Will (Audible)")
    [mine] = app.get("/api/audio-books-heard").json
    assert (mine["name"], [v["name"] for v in mine["listens"]], mine["rating"]) == ("Free Will", ["Audible"], None)
    app.put_json(f"/api/audio-books-heard/{mine['id']}", {**first, "rating": 7, "review": "Good"})
    # the shared version says the user heard it; the book, and the version, stay while it is heard
    [version] = app.get("/api/audio-book-versions").json
    assert version["listen"]["id"] == listen["id"]
    sign_in_admin(app, engine)
    app.delete(f"/api/audio-books/{first['book_id']}", status=409)
    app.delete(f"/api/audio-book-versions/{version['id']}", status=409)
    app.delete(f"/api/audio-books-heard/{mine['id']}", status=409)
    # with no version heard it is not listed, and keeps what the user said of it for when one is heard again
    app.delete(f"/api/audio-book-listens/{listen['id']}", status=204)
    assert app.get("/api/audio-books-heard").json == []
    app.post_json("/api/audio-book-listens", minimal(app, "audio-book-listens")[0], status=201)
    assert [(b["rating"], b["review"]) for b in app.get("/api/audio-books-heard").json] == [(7, "Good")]
    sign_in(app, sub="someone-else")
    assert app.get("/api/audio-books-heard").json == []
    app.put_json(f"/api/audio-books-heard/{mine['id']}", first, status=404)


def test_film_watches(app: webtest.TestApp, engine: Engine) -> None:
    """ A film is shared; each time the user watched it, or means to, is theirs, and a film watched stays. """
    sign_in(app)
    first, _ = minimal(app, "film-watches")
    person = app.post_json("/api/people", {"first_name": "Doron"}, status=201).json
    seen = app.post_json("/api/film-watches", {**first, "date": "2020-12-31", "rating": 8, "review": "Good", "people": [person["id"]]}, status=201).json
    again = app.post_json("/api/film-watches", {**first, "date": "2022-07-23", "rating": 9}, status=201).json
    wanted = app.post_json("/api/film-watches", {**first, "status": "wishlist", "recommended_by_id": person["id"]}, status=201).json
    assert (seen["name"], seen["year"], seen["url"], seen["with"]) == ("Interstellar", 2014, "https://www.imdb.com/title/tt0816692/", ["Doron"])
    assert (wanted["status_name"], wanted["recommended_by"]) == ("Want to see", {"id": person["id"], "name": "Doron"})
    # the latest watched first, the one still to see last
    assert [w["id"] for w in app.get("/api/film-watches").json] == [again["id"], seen["id"], wanted["id"]]
    [film] = app.get("/api/films").json
    assert [w["name"] for w in film["watches"]] == ["2022-07-23", "2020-12-31", "Want to see"]
    app.post_json("/api/film-watches", {**first, "status": "seen"}, status=400)
    # a film someone watched stays; and two films are not one IMDb id
    sign_in_admin(app, engine)
    app.delete(f"/api/films/{first['film_id']}", status=409)
    assert app.post_json("/api/films", {"name": "Interstellar", "imdb_id": "https://www.imdb.com/title/tt0816692/"}, status=409).json == {
        "error": "imdb_id: tt0816692 is in Films already",
    }
    added = app.post_json("/api/films", {"name": "Dune", "imdb_id": "1160419", "genres": "science fiction, drama, drama", "wikidata_id": "Q60834962"}, status=201).json
    assert (added["imdb_id"], added["genres"]) == ("tt1160419", ["science fiction", "drama"])
    app.post_json("/api/films", {"name": "Dune", "rotten_tomatoes_id": "dune"}, status=400)
    # the other account sees the film, and none of the watches
    sign_in(app, sub="someone-else")
    assert app.get("/api/film-watches").json == []
    assert [f["watches"] for f in app.get("/api/films").json] == [[], []]


def test_series_are_films_of_another_kind(app: webtest.TestApp, engine: Engine) -> None:
    """ A series is listed on the Series pages, a film on the Films pages; a film made a series moves, with its watches. """
    sign_in(app)
    series_watch = app.post_json("/api/series-watches", {**minimal(app, "series-watches")[0], "seasons_seen": "3, 1, 2", "seasons_not_seen": "4"}, status=201).json
    film_watch = app.post_json("/api/film-watches", minimal(app, "film-watches")[0], status=201).json
    assert (series_watch["kind_name"], series_watch["seasons_seen"], series_watch["seasons_not_seen"]) == ("Series", [1, 2, 3], [4])
    assert [w["id"] for w in app.get("/api/series-watches").json] == [series_watch["id"]]
    assert [w["id"] for w in app.get("/api/film-watches").json] == [film_watch["id"]]
    assert [f["name"] for f in app.get("/api/series").json] == ["The Leftovers"]
    app.post_json("/api/series-watches", {**minimal(app, "series-watches")[0], "seasons_seen": "1", "seasons_not_seen": "1"}, status=400)
    app.post_json("/api/series-watches", {**minimal(app, "series-watches")[0], "seasons_seen": "one"}, status=400)
    sign_in_admin(app, engine)
    film = app.get("/api/films").json[0]
    app.put_json(f"/api/films/{film['id']}", {"name": film["name"], "imdb_id": film["imdb_id"], "kind": "series"})
    assert app.get("/api/films").json == []
    assert sorted(f["name"] for f in app.get("/api/series").json) == ["Interstellar", "The Leftovers"]
    assert app.post_json("/api/series", {"name": "Fauda", "kind": "anime"}, status=400).json == {"error": "kind: expected one of film, series"}


def test_a_page_that_is_not_one(app: webtest.TestApp) -> None:
    sign_in(app)
    app.post_json("/api/unicorns", {"name": "Bob"}, status=404)
    app.put_json("/api/unicorns/1", {"name": "Bob"}, status=404)
    app.delete("/api/unicorns/1", status=404)


@pytest.mark.parametrize("path", ["concert-visits", "audio-courses", "episodes-heard", "film-watches", "series-watches", "youtube-videos"])
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
    first, changed = minimal(app, path)
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
    first, changed = minimal(app, path)
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
    }
    sign_in(app)
    for path, body, error in (
        ("concert-visits", {"name": "Jarrett", "people": [theirs["person"]]}, "people: unknown person"),
        ("concert-visits", {"name": "Jarrett", "people": "Dana"}, "people: expected a list of ids"),
        ("concert-visits", {"name": "Jarrett", "people": [True]}, "people: expected a list of ids"),
        ("organizations", {"name": "ACME", "type_ids": [theirs["type"]]}, "type_ids: unknown organizationtype"),
        ("audio-courses", {"name": "Logic", "device_id": theirs["device"]}, "device_id: unknown device"),
        ("episodes-heard", {"episode_id": 999999}, "episode_id: unknown episode"),
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
    assert texas["country"] == {"id": usa, "name": "USA"}
    assert [city["name"] for city in texas["cities"]] == ["Austin", "Dallas"]
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
