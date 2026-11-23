"""
Goodreads (myworld.goodreads) and the importer of the to-read shelf of an
uploaded library export (goodreads-to-read): books not in the library come
in as wanted, with author, cover and notes; the ones there are left as they
are. The export is in Goodreads' columns; covers are faked: nothing here
goes to the network.
"""

from typing import Any

import pytest
import webtest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from myworld import goodreads
from myworld.importers import core, jobs
from myworld.importers.goodreads_to_read import split_series
from myworld.models import Person, User, UserWork
from tests.conftest import sign_in

HEADER = (
    "﻿Book Id,Title,Author,Author l-f,Additional Authors,ISBN,ISBN13,My Rating,Average Rating,Publisher,Binding,"
    "Number of Pages,Year Published,Original Publication Year,Date Read,Date Added,Bookshelves,Bookshelves with positions,"
    "Exclusive Shelf,My Review,Spoiler,Private Notes,Read Count,Owned Copies\n"
)
EXPORT = HEADER + (
    '234225,"Dune (Dune, #1)",Frank Herbert,"Herbert, Frank",,"=""0441172717""","=""9780441172719""",0,4.27,Ace,Paperback,'
    '658,1990,1965,,2019/03/12,to-read,to-read (#1),to-read,,,,0,0\n'
    '5907,The Hobbit,J.R.R. Tolkien,"Tolkien, J.R.R.",,"=""""","=""""",0,4.29,Houghton,Paperback,366,2002,1937,'
    ',2020/01/05,to-read,to-read (#2),to-read,,,,0,0\n'
    '11,Kitchen Confidential,Anthony Bourdain,"Bourdain, Anthony",,"=""""","=""""",0,4.1,Ecco,Paperback,312,2000,,'
    ',2021/07/01,to-read,to-read (#3),to-read,,,,0,0\n'
    '42,Read Already,Some One,"One, Some",,"=""""","=""""",5,4.0,X,Paperback,100,2001,2001,'
    '2001/05/01,2001/04/01,,,read,"A private review",,,1,0\n'
)


class FakeCovers:
    def __init__(self) -> None:
        self.covers: list[str] = []

    def fetch_cover(self, url: str) -> tuple[bytes, str] | None:
        self.covers.append(url)
        return (b"\xff\xd8cover", "image/jpeg")


@pytest.fixture(autouse=True)
def fixture_inline_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """ A run's job is done right away, inside the request that starts it. """
    def dispatcher(engine: Engine) -> Any:
        def dispatch(run_id: int) -> str:
            core.execute(engine, run_id)
            return f"run-{run_id}"
        return dispatch
    monkeypatch.setattr(jobs, "dispatcher", dispatcher)


@pytest.fixture(name="fake")
def fixture_fake(monkeypatch: pytest.MonkeyPatch) -> FakeCovers:
    fake = FakeCovers()
    monkeypatch.setattr(goodreads, "fetch_cover", fake.fetch_cover)
    return fake


def run(app: webtest.TestApp, export: Any, dry_run: bool = False, status: int = 202) -> Any:
    return app.post_json("/api/importers/goodreads-to-read/runs", {"params": {"export": export}, "dry_run": dry_run}, status=status).json


def alice(engine: Engine) -> User:
    with Session(engine) as session:
        return session.scalars(select(User).where(User.email == "alice@example.com")).one()


def test_the_series_comes_off_the_title() -> None:
    assert split_series("Dune (Dune, #1)") == ("Dune", "Dune, #1")
    assert split_series("The Eye of the World (The Wheel of Time, #1)") == ("The Eye of the World", "The Wheel of Time, #1")
    assert split_series("Words (and Things)") == ("Words (and Things)", "")


def test_an_export_is_read_as_the_books_of_a_shelf() -> None:
    dune, hobbit, kitchen = goodreads.parse_export(EXPORT, "to-read")
    assert (dune.goodreads_id, dune.title, dune.author, dune.isbn, dune.year) == ("234225", "Dune (Dune, #1)", "Frank Herbert", "9780441172719", 1965)
    # the export has no covers: Open Library's, by ISBN
    assert dune.image_url == "https://covers.openlibrary.org/b/isbn/9780441172719-L.jpg?default=false"
    assert dune.added is not None
    assert dune.added.isoformat() == "2019-03-12"
    # no ISBN: no cover; no original year: the edition's
    assert (hobbit.isbn, hobbit.image_url, hobbit.year) == ("", "", 1937)
    assert kitchen.year == 2000
    assert [b.title for b in goodreads.parse_export(EXPORT, "read")] == ["Read Already"]
    with pytest.raises(goodreads.GoodreadsError, match="not a Goodreads library export"):
        goodreads.parse_export("Title,Author\nDune,Frank Herbert\n", "to-read")


def test_the_importer_takes_a_file(app: webtest.TestApp) -> None:
    sign_in(app)
    importer = next(i for i in app.get("/api/importers").json["importers"] if i["name"] == "goodreads-to-read")
    assert importer["unavailable"] == ""
    assert [(p["name"], p["kind"], p["accept"]) for p in importer["params"]] == [("export", "file", ".csv")]
    # no file, a file that is not an export, something that is not a file's text: refused before anything runs
    assert "choose a file" in run(app, "", status=400)["error"]
    assert "not a Goodreads library export" in run(app, "a,b\n1,2\n", status=400)["error"]
    run(app, ["not", "text"], status=400)


def test_the_to_read_shelf_comes_in_as_wanted_books(app: webtest.TestApp, engine: Engine, fake: FakeCovers) -> None:
    sign_in(app)
    # a book the library has already: left as it is, given its Goodreads id
    hobbit = app.post_json("/api/library-entries", {"kind": "book", "title": "The Hobbit", "creator": "J.R.R. Tolkien", "year": 1937, "status": "done"}).json
    # the profession a new author is given, when the account keeps it
    app.post_json("/api/person-types", {"name": "Book Author"})
    dry = run(app, EXPORT, dry_run=True)
    assert dry["status"] == "done"
    assert "books added, wanted" in dry["log"]
    assert len(app.get("/api/library-entries").json) == 1
    # a dry run does it all, covers too, and keeps nothing
    fake.covers.clear()
    done = run(app, EXPORT)
    assert done["status"] == "done", done["log"]
    # the log says what the file was, not what was in it; only the to-read shelf is kept of it
    assert "a library export with 3 books to read" in done["log"]
    assert "private review" not in str(done)
    entries = {e["title"]: e for e in app.get("/api/library-entries").json}
    assert set(entries) == {"Dune", "The Hobbit", "Kitchen Confidential"}
    dune = entries["Dune"]
    assert (dune["status"], dune["creator"], dune["year"], dune["isbn"], dune["goodreads_id"]) == ("wishlist", "Frank Herbert", 1965, "9780441172719", "234225")
    assert [a["name"] for a in dune["authors"]] == ["Frank Herbert"]
    assert dune["image"]
    assert entries["Kitchen Confidential"]["image"] is None
    assert fake.covers == ["https://covers.openlibrary.org/b/isbn/9780441172719-L.jpg?default=false"]
    hobbit_now = entries["The Hobbit"]
    assert (hobbit_now["status"], hobbit_now["goodreads_id"], hobbit_now["work_id"]) == ("done", "5907", hobbit["work_id"])
    with Session(engine) as session:
        notes = session.get(UserWork, (alice(engine).id, dune["work_id"]))
        assert notes is not None
        assert notes.notes == "Series: Dune, #1\nOn my Goodreads to-read shelf since 2019-03-12"
        author = session.scalars(select(Person).where(Person.surname == "Herbert")).one()
        assert [t.name for t in author.types] == ["Book Author"]
    # again: nothing new
    again = run(app, EXPORT)
    assert "books added" not in again["log"]
    assert len(app.get("/api/library-entries").json) == 3
