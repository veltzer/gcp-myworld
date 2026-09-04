"""
The film lookups (The Movie Database plus Wikidata), with the HTTP calls
replaced by canned answers.
"""

from typing import Any

import pytest
import webtest

from myworld import movies
from tests.conftest import sign_in

SEARCH_ANSWER: dict[str, Any] = {
    "results": [
        {"id": 438631, "title": "Dune", "original_title": "Dune", "release_date": "2021-09-15",
         "overview": "Paul Atreides...", "poster_path": "/dune.jpg"},
        {"id": 841, "title": "Dune", "original_title": "Dune", "release_date": "1984-12-14",
         "overview": "", "poster_path": None},
        {"id": 1, "title": "Untitled", "original_title": "", "release_date": "", "overview": None},
    ],
}

DETAILS_ANSWER: dict[str, Any] = {
    "id": 438631,
    "title": "Dune",
    "original_title": "Dune",
    "release_date": "2021-09-15",
    "overview": "Paul Atreides...",
    "poster_path": "/dune.jpg",
    "runtime": 155,
    "genres": [{"name": "Science Fiction"}, {"name": "Adventure"}],
    "credits": {"crew": [{"job": "Producer", "name": "Someone"}, {"job": "Director", "name": "Denis Villeneuve"}]},
    "external_ids": {"imdb_id": "tt1160419", "wikidata_id": "Q60834962"},
}

WIKIDATA_ANSWER: dict[str, Any] = {
    "claims": {"P1258": [{"mainsnak": {"datavalue": {"value": "m/dune_2021"}}}]},
}


@pytest.fixture(name="tmdb")
def fixture_tmdb(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """ A configured TMDB with canned answers; returns the list of paths asked for. """
    monkeypatch.setenv("TMDB_API_KEY", "test-key")
    asked: list[str] = []

    def fake_tmdb_get(path: str, **params: str) -> dict[str, Any]:
        asked.append(path)
        if path == "/search/movie":
            assert params["query"] == "dune"
            return SEARCH_ANSWER
        if path == "/movie/438631":
            assert params["append_to_response"] == "credits,external_ids"
            return DETAILS_ANSWER
        raise movies.MovieLookupError("TMDB answered 404")

    def fake_wikidata(qid: str) -> dict[str, Any]:
        asked.append(f"wikidata:{qid}")
        return WIKIDATA_ANSWER

    monkeypatch.setattr(movies, "tmdb_get", fake_tmdb_get)
    monkeypatch.setattr(movies, "wikidata_entity", fake_wikidata)
    return asked


def test_unconfigured(app: webtest.TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    assert app.get("/api/config").json["tmdb"] is False
    sign_in(app)
    response = app.get("/api/movies/search?q=dune", status=503)
    assert "TMDB_API_KEY" in response.json["error"]
    app.get("/api/movies/438631", status=503)


def test_requires_login(app: webtest.TestApp, tmdb: list[str]) -> None:
    app.get("/api/movies/search?q=dune", status=401)
    app.get("/api/movies/438631", status=401)
    assert tmdb == []


def test_search(app: webtest.TestApp, tmdb: list[str]) -> None:
    assert app.get("/api/config").json["tmdb"] is True
    sign_in(app)
    app.get("/api/movies/search?q=", status=400)
    results = app.get("/api/movies/search?q=dune").json
    assert [r["tmdb_id"] for r in results] == [438631, 841, 1]
    assert results[0] == {
        "tmdb_id": 438631, "title": "Dune", "original_title": "Dune", "year": 2021,
        "overview": "Paul Atreides...", "poster": "https://image.tmdb.org/t/p/w92/dune.jpg",
    }
    assert results[1]["poster"] == ""
    assert results[2]["year"] is None
    assert results[2]["overview"] == ""
    assert tmdb == ["/search/movie"]


def test_details(app: webtest.TestApp, tmdb: list[str]) -> None:
    sign_in(app)
    film = app.get("/api/movies/438631").json
    assert film["title"] == "Dune"
    assert film["creator"] == "Denis Villeneuve"
    assert film["year"] == 2021
    assert film["imdb_id"] == "tt1160419"
    assert film["tmdb_id"] == 438631
    assert film["rotten_tomatoes_id"] == "m/dune_2021"
    assert film["runtime"] == 155
    assert film["genres"] == ["Science Fiction", "Adventure"]
    assert tmdb == ["/movie/438631", "wikidata:Q60834962"]


@pytest.mark.usefixtures("tmdb")
def test_details_without_rotten_tomatoes(app: webtest.TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_wikidata(qid: str) -> dict[str, Any]:
        raise movies.MovieLookupError("Wikidata answered 500")
    monkeypatch.setattr(movies, "wikidata_entity", no_wikidata)
    sign_in(app)
    film = app.get("/api/movies/438631").json
    assert film["imdb_id"] == "tt1160419"
    assert film["rotten_tomatoes_id"] == ""


@pytest.mark.usefixtures("tmdb")
def test_lookup_failure(app: webtest.TestApp) -> None:
    sign_in(app)
    response = app.get("/api/movies/999", status=502)
    assert "did not answer" in response.json["error"]


def test_ids_are_stored_with_the_work(app: webtest.TestApp) -> None:
    sign_in(app)
    entry = app.post_json("/api/library", {
        "kind": "film", "title": "Dune", "creator": "Denis Villeneuve", "year": 2021,
        "imdb_id": "tt1160419", "tmdb_id": "438631", "rotten_tomatoes_id": "m/dune_2021",
    }).json
    assert entry["imdb_id"] == "tt1160419"
    assert entry["tmdb_id"] == 438631
    assert entry["rotten_tomatoes_id"] == "m/dune_2021"
    [listed] = app.get("/api/library?kind=film").json
    assert listed["tmdb_id"] == 438631

    # adding the same film again without ids keeps them; with different ids updates them
    again = app.post_json("/api/library", {"kind": "film", "title": "Dune", "creator": "Denis Villeneuve", "year": 2021}).json
    assert again["work_id"] == entry["work_id"]
    assert again["imdb_id"] == "tt1160419"
    bad = {"kind": "film", "title": "Dune", "creator": "Denis Villeneuve", "year": 2021, "tmdb_id": "not a number"}
    app.post_json("/api/library", bad, status=400)

    # a book has no ids
    book = app.post_json("/api/library", {"kind": "book", "title": "Dune", "creator": "Frank Herbert", "year": 1965}).json
    assert book["imdb_id"] == ""
    assert book["tmdb_id"] is None
