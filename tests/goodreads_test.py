"""
Connecting Goodreads (myworld.goodreads) by a shelf's RSS address, and the
importer of the to-read shelf (importers.goodreads_to_read): books not in
the library added as wanted, with author, cover and notes; the ones there
left as they are. Goodreads is faked: nothing here goes to the network.
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
from myworld.models import GoodreadsConnection, Person, User, UserWork
from tests.conftest import sign_in

KEY = "secretfeedkey"
ADDRESS = f"https://www.goodreads.com/review/list_rss/34371877?key={KEY}&shelf=%23ALL%23"


def item(book_id: str, title: str, author: str, isbn: str = "", year: str = "", image: str = "", added: str = "") -> str:
    return (
        f"<item><title>{title}</title><book_id>{book_id}</book_id><author_name>{author}</author_name><isbn>{isbn}</isbn>"
        f"<book_published>{year}</book_published><book_large_image_url>{image}</book_large_image_url>"
        f"<user_date_added><![CDATA[{added}]]></user_date_added></item>"
    )


def feed(*items: str) -> bytes:
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>shelf</title>{"".join(items)}</channel></rss>'.encode()


class FakeGoodreads:
    def __init__(self) -> None:
        self.pages = {
            "1": feed(
                item("234225", "Dune (Dune, #1)", "Frank Herbert", "0441172717", "1965", "https://i.gr-assets.com/dune.jpg", "Tue, 12 Mar 2019 04:05:06 -0700"),
                item("5907", "The Hobbit", "J.R.R. Tolkien", "", "1937", "https://s.gr-assets.com/nophoto/book/111x148.png"),
            ),
            "2": feed(item("11", "Kitchen Confidential", "Anthony Bourdain")),
            "3": feed(),
        }
        self.asked: list[dict[str, str]] = []

    def fetch(self, url: str, params: dict[str, str]) -> bytes:
        assert url == "https://www.goodreads.com/review/list_rss/34371877"
        self.asked.append(params)
        if params["key"] != KEY:
            raise goodreads.GoodreadsError("Goodreads does not know that feed (404)")
        return self.pages.get(params["page"], feed())

    def fetch_cover(self, url: str) -> tuple[bytes, str] | None:
        assert "nophoto" not in url
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
def fixture_fake(monkeypatch: pytest.MonkeyPatch) -> FakeGoodreads:
    fake = FakeGoodreads()
    monkeypatch.setattr(goodreads, "fetch", fake.fetch)
    monkeypatch.setattr(goodreads, "fetch_cover", fake.fetch_cover)
    return fake


def run(app: webtest.TestApp, dry_run: bool = False, status: int = 202) -> Any:
    return app.post_json("/api/importers/goodreads-to-read/runs", {"params": {}, "dry_run": dry_run}, status=status).json


def alice(engine: Engine) -> User:
    with Session(engine) as session:
        return session.scalars(select(User).where(User.email == "alice@example.com")).one()


def test_the_series_comes_off_the_title() -> None:
    assert split_series("Dune (Dune, #1)") == ("Dune", "Dune, #1")
    assert split_series("The Eye of the World (The Wheel of Time, #1)") == ("The Eye of the World", "The Wheel of Time, #1")
    assert split_series("Words (and Things)") == ("Words (and Things)", "")


@pytest.mark.usefixtures("fake")
def test_connecting_keeps_the_key_sealed(app: webtest.TestApp, engine: Engine) -> None:
    sign_in(app)
    listing = app.get("/api/importers").json
    assert listing["goodreads"]["connected"] is False
    assert next(i for i in listing["importers"] if i["name"] == "goodreads-to-read")["unavailable"] == "Connect Goodreads first"
    # not a shelf feed, a feed without its key, a key Goodreads does not know: refused
    app.post_json("/goodreads/connect", {"address": "https://www.goodreads.com/user/show/34371877-mark"}, status=400)
    app.post_json("/goodreads/connect", {"address": "https://www.goodreads.com/review/list_rss/34371877"}, status=400)
    app.post_json("/goodreads/connect", {"address": "https://www.goodreads.com/review/list_rss/34371877?key=wrong"}, status=400)
    status = app.post_json("/goodreads/connect", {"address": ADDRESS}).json
    assert (status["connected"], status["user_id"]) == (True, "34371877")
    with Session(engine) as session:
        kept = session.get(GoodreadsConnection, alice(engine).id)
        assert kept is not None and KEY not in kept.feed_key
        assert goodreads.unseal(kept.feed_key) == KEY
    app.post("/goodreads/disconnect", status=204)
    assert app.get("/goodreads/status").json["connected"] is False


def test_the_to_read_shelf_comes_in_as_wanted_books(app: webtest.TestApp, engine: Engine, fake: FakeGoodreads) -> None:
    sign_in(app)
    # a book the library has already: left as it is, given its Goodreads id
    hobbit = app.post_json("/api/library-entries", {"kind": "book", "title": "The Hobbit", "creator": "J.R.R. Tolkien", "year": 1937, "status": "done"}).json
    # the profession a new author is given, when the account keeps it
    app.post_json("/api/person-types", {"name": "Book Author"})
    app.post_json("/goodreads/connect", {"address": ADDRESS})
    dry = run(app, dry_run=True)
    assert dry["status"] == "done" and "books added, wanted" in dry["log"]
    assert len(app.get("/api/library-entries").json) == 1
    done = run(app)
    assert done["status"] == "done", done["log"]
    # every page of the to-read shelf was read, until an empty one
    assert [(p["shelf"], p["page"]) for p in fake.asked[-3:]] == [("to-read", "1"), ("to-read", "2"), ("to-read", "3")]
    entries = {e["title"]: e for e in app.get("/api/library-entries").json}
    assert set(entries) == {"Dune", "The Hobbit", "Kitchen Confidential"}
    dune = entries["Dune"]
    assert (dune["status"], dune["creator"], dune["year"], dune["isbn"], dune["goodreads_id"]) == ("wishlist", "Frank Herbert", 1965, "0441172717", "234225")
    assert [a["name"] for a in dune["authors"]] == ["Frank Herbert"]
    assert dune["image"]
    assert entries["Kitchen Confidential"]["image"] is None
    hobbit_now = entries["The Hobbit"]
    assert (hobbit_now["status"], hobbit_now["goodreads_id"], hobbit_now["work_id"]) == ("done", "5907", hobbit["work_id"])
    with Session(engine) as session:
        notes = session.get(UserWork, (alice(engine).id, dune["work_id"]))
        assert notes is not None and notes.notes == "Series: Dune, #1\nOn my Goodreads to-read shelf since 2019-03-12"
        author = session.scalars(select(Person).where(Person.surname == "Herbert")).one()
        assert [t.name for t in author.types] == ["Book Author"]
    # again: nothing new
    again = run(app)
    assert "books added" not in again["log"] and len(app.get("/api/library-entries").json) == 3


def test_a_key_goodreads_no_longer_knows_fails_the_run(app: webtest.TestApp, engine: Engine, fake: FakeGoodreads) -> None:
    sign_in(app)
    app.post_json("/goodreads/connect", {"address": ADDRESS})
    with Session(engine) as session:
        kept = session.get(GoodreadsConnection, alice(engine).id)
        assert kept is not None
        kept.feed_key = goodreads.seal("revoked")
        session.commit()
    failed = run(app)
    assert failed["status"] == "failed" and "404" in failed["log"]
    assert fake.asked[-1]["key"] == "revoked"
