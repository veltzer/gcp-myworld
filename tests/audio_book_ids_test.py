"""
The audio book ids importer, an admin's, into the shared data
(myworld.importers.audio_book_ids), against an Open Library search that is
faked: which result is the same book, and that only what is empty is filled.
"""

from typing import Any

import pytest
import webtest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from myworld.importers import audio_book_ids, core, jobs
from myworld.models import AudioBook
from tests.conftest import sign_in, sign_in_admin

# title -> what the faked search answers
ANSWERS: dict[str, list[dict[str, Any]]] = {
    # another book of the same title first: not taken
    "Heretic": [
        {"key": "/works/OL1W", "title": "Heretic", "author_name": ["Bernard Cornwell"], "id_goodreads": ["68527"]},
        {"key": "/works/OL17803776W", "title": "Heretic: Why Islam Needs a Reformation Now", "author_name": ["Ayaan Hirsi Ali"],
         "id_goodreads": ["22609305", "24452364"], "id_wikidata": ["Q19865478"]},
    ],
    "Letter to a Christian Nation": [{"key": "/works/OL3902907W", "title": "Letter to a Christian Nation", "author_name": ["Sam Harris"], "id_goodreads": ["8284"]}],
    "Unknown Book": [],
}


@pytest.fixture(autouse=True)
def fixture_inline_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """ A run's job is done right away, inside the request that starts it (as tests/podcast_feeds_test.py does). """
    def dispatcher(engine: Engine) -> Any:
        def dispatch(run_id: int) -> str:
            core.execute(engine, run_id)
            return f"projects/p/locations/r/jobs/myworld-import/executions/run-{run_id}"
        return dispatch
    monkeypatch.setattr(jobs, "dispatcher", dispatcher)


@pytest.fixture(name="asked")
def fixture_asked(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    asked: list[tuple[str, str]] = []

    def search(title: str, author: str) -> list[dict[str, Any]]:
        asked.append((title, author))
        return ANSWERS[title]
    monkeypatch.setattr(audio_book_ids, "search", search)
    monkeypatch.setattr(audio_book_ids, "PAUSE", 0)
    return asked


def books(engine: Engine) -> dict[str, AudioBook]:
    with Session(engine) as session:
        return {b.name: b for b in session.scalars(select(AudioBook))}


def run(app: webtest.TestApp) -> Any:
    record = app.post_json("/api/importers/audio-book-ids/runs", {"params": {}, "dry_run": False}, status=202).json
    assert record["status"] == "done", record["log"]
    return record


def test_the_ids_of_the_same_book_fill_what_is_empty(app: webtest.TestApp, engine: Engine, asked: list[tuple[str, str]]) -> None:
    with Session(engine) as session:
        session.add_all([
            AudioBook(name="Heretic: Why Islam Needs a Reformation Now", authors="Ayaan Hirsi Ali"),
            # its Goodreads id typed in by hand: kept
            AudioBook(name="Letter to a Christian Nation", authors="Sam Harris", goodreads_id="999"),
            AudioBook(name="Unknown Book", authors="Nobody"),
        ])
        session.commit()
    # an admin's: another user does not see it
    sign_in(app)
    assert "audio-book-ids" not in [i["name"] for i in app.get("/api/importers").json["importers"]]
    sign_in_admin(app, engine)
    record = run(app)
    # by the title without its subtitle, and the first author
    assert sorted(asked) == [("Heretic", "Ayaan Hirsi Ali"), ("Letter to a Christian Nation", "Sam Harris"), ("Unknown Book", "Nobody")]
    assert record["counts"] == {"Open Library ids added": 2, "Goodreads ids added": 1, "Wikidata ids added": 1, "audio books not found": 1}
    found = books(engine)
    heretic, letter = found["Heretic: Why Islam Needs a Reformation Now"], found["Letter to a Christian Nation"]
    assert (heretic.openlibrary_id, heretic.goodreads_id, heretic.wikidata_id) == ("OL17803776W", "22609305", "Q19865478")
    assert (letter.openlibrary_id, letter.goodreads_id, letter.wikidata_id) == ("OL3902907W", "999", "")
    assert "Unknown Book: Open Library does not have it" in record["log"]
    # again: only the books still missing an id are looked up, and nothing changes
    asked.clear()
    assert run(app)["counts"] == {"audio books not found": 1}
    assert sorted(asked) == [("Letter to a Christian Nation", "Sam Harris"), ("Unknown Book", "Nobody")]


def test_an_id_typed_in_is_checked(app: webtest.TestApp, engine: Engine) -> None:
    sign_in_admin(app, engine)
    book = app.post_json("/api/audio-books", {"name": "Free Will", "authors": "Sam Harris", "openlibrary_id": "OL16801432W", "goodreads_id": "13259167",
                                              "wikidata_id": "Q7500364"}, status=201).json
    assert (book["openlibrary_id"], book["goodreads_id"], book["wikidata_id"]) == ("OL16801432W", "13259167", "Q7500364")
    for key, value in (("openlibrary_id", "OL123M"), ("goodreads_id", "abc"), ("wikidata_id", "7500364")):
        assert key in app.put_json(f"/api/audio-books/{book['id']}", {"name": "Free Will", key: value}, status=400).json["error"]


def test_a_hyphen_is_not_a_not() -> None:
    # Open Library's search reads "-word" as without word
    assert audio_book_ids.query_words("Capital in the Twenty-First Century") == "Capital in the Twenty First Century"
    assert audio_book_ids.query_words("The Gulag Archipelago 1918-1956") == "The Gulag Archipelago 1918 1956"
