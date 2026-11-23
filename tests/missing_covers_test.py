"""
The missing covers importer, an admin's, into the shared data
(myworld.importers.missing_covers), against Audible's image server and The
Movie Database faked: only what has no cover is given one, and a run again
asks only about those still missing one.
"""

from typing import Any

import pytest
import webtest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from myworld import audible, movies
from myworld.importers import core, jobs
from myworld.models import AudioBook, AudioBookVersion, Film, Image
from tests.conftest import sign_in, sign_in_admin

JPEG = b"\xff\xd8cover"


@pytest.fixture(autouse=True)
def fixture_inline_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """ A run's job is done right away, inside the request that starts it (as tests/audio_book_ids_test.py does). """
    def dispatcher(engine: Engine) -> Any:
        def dispatch(run_id: int) -> str:
            core.execute(engine, run_id)
            return f"projects/p/locations/r/jobs/myworld-import/executions/run-{run_id}"
        return dispatch
    monkeypatch.setattr(jobs, "dispatcher", dispatcher)


@pytest.fixture(name="asked")
def fixture_asked(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """ Audible gives a cover for B1 only; TMDB knows tt0816692 only, with a poster. """
    asked: list[str] = []

    def fetch_cover(url: str) -> bytes | None:
        asked.append(url)
        return JPEG + b"audible" if url.endswith("/B1.jpg") else None

    def tmdb_get(path: str, **_params: str) -> dict[str, Any]:
        imdb = path.removeprefix("/find/")
        asked.append(imdb)
        found = [{"id": 157336, "release_date": "2014-11-05", "poster_path": "/p.jpg"}] if imdb == "tt0816692" else []
        return {"movie_results": found, "tv_results": []}

    monkeypatch.setattr(audible, "fetch_cover", fetch_cover)
    monkeypatch.setattr(movies, "configured", lambda: True)
    monkeypatch.setattr(movies, "tmdb_get", tmdb_get)
    monkeypatch.setattr(movies, "poster_bytes", lambda url: JPEG + url.encode())
    return asked


def run(app: webtest.TestApp) -> Any:
    record = app.post_json("/api/importers/missing-covers/runs", {"params": {}, "dry_run": False}, status=202).json
    assert record["status"] == "done", record["log"]
    return record


def test_what_has_no_cover_is_given_one(app: webtest.TestApp, engine: Engine, asked: list[str]) -> None:
    sign_in_admin(app, engine)
    with Session(engine) as session:
        kept = Image(owner_id=1, filename="mine.jpg", content_type="image/jpeg", sha256="0", data=JPEG + b"mine")
        book = AudioBook(name="Letter", authors="Sam Harris")
        session.add_all([
            AudioBookVersion(book=book, kind="audible", asin="B1", genres=[], cover_url="https://m.media-amazon.com/images/I/B1.jpg"),
            AudioBookVersion(book=book, kind="audible", asin="B2", genres=[], cover_url="https://m.media-amazon.com/images/I/B2.jpg"),
            # one with a cover keeps it, and MP3 files are not Audible's to give one
            AudioBookVersion(book=AudioBook(name="Kept", authors="Someone"), kind="audible", asin="B3", genres=[], cover_url="https://x/B3.jpg", image=kept),
            AudioBookVersion(book=AudioBook(name="Files", authors="Someone"), kind="mp3", genres=[]),
            Film(name="Interstellar", imdb_id="tt0816692", genres=[]),
            Film(kind="series", name="Unknown", imdb_id="tt0000001", genres=[]),
        ])
        session.commit()
    # an admin's: another user does not see it
    sign_in(app, sub="someone-else")
    assert "missing-covers" not in [i["name"] for i in app.get("/api/importers").json["importers"]]
    sign_in_admin(app, engine)
    record = run(app)
    assert record["counts"] == {"audio book covers added": 1, "audio book covers not found": 1, "posters added": 1, "posters not found": 1}
    assert sorted(asked) == ["https://m.media-amazon.com/images/I/B1.jpg", "https://m.media-amazon.com/images/I/B2.jpg", "tt0000001", "tt0816692"]
    with Session(engine) as session:
        versions = {v.asin: v for v in session.scalars(select(AudioBookVersion))}
        films = {f.name: f for f in session.scalars(select(Film))}
        assert versions["B1"].image is not None
        assert versions["B1"].image.data == JPEG + b"audible"
        assert versions["B2"].image is None
        assert versions["B3"].image is not None
        assert versions["B3"].image.data == JPEG + b"mine"
        assert films["Interstellar"].image is not None
        assert films["Interstellar"].tmdb_id == 157336
        assert films["Unknown"].image is None
    # again: only those still missing one are asked about
    asked.clear()
    assert run(app)["counts"] == {"audio book covers not found": 1, "posters not found": 1}
    assert sorted(asked) == ["https://m.media-amazon.com/images/I/B2.jpg", "tt0000001"]
