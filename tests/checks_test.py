"""
The database checks: the logo rules themselves, the registry, the admin
API that runs them and scripts/check.py, which runs the same ones.
"""

import datetime
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import webtest
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from myworld import checks
from myworld.checks import logo_problems
from myworld.models import (
    KINDS,
    MUSEUM_KIND,
    MUSEUM_VISIT,
    ROLE_ADMIN,
    AudioBook,
    AudioBookHeard,
    AudioBookListen,
    AudioBookVersion,
    AudioCourse,
    Base,
    Certification,
    City,
    Concert,
    Country,
    Course,
    Device,
    DisabledCheck,
    EpisodeHeard,
    Group,
    Image,
    Lecture,
    Login,
    Organization,
    Person,
    PersonPhoto,
    PersonType,
    Place,
    PlaceKind,
    Podcast,
    PodcastEpisode,
    PodcastHeard,
    Rally,
    Read,
    Region,
    RelationType,
    Trip,
    User,
    UserWork,
    Visit,
    VisitType,
    Work,
    WorkTitle,
    YouTubeVideo,
)
from tests.conftest import sign_in

GOOD = b'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1000" viewBox="-1 -1 12 12"><rect width="10" height="10"/></svg>'


def svg(attributes: str = 'width="1000" height="1000" viewBox="0 0 10 10"', body: str = "<rect/>") -> bytes:
    return f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" {attributes}>{body}</svg>'.encode()


def test_good_logo() -> None:
    assert not logo_problems(GOOD)
    # a gradient referred to inside the file, and an inkscape-style header, are fine
    assert not logo_problems(svg(body='<defs><linearGradient id="g"/></defs><rect fill="url(#g)"/><use xlink:href="#g"/>'))
    assert not logo_problems(svg('width="1000" height="1000" viewBox="-18.89,-143.49,349.01,349.01"'))


@pytest.mark.parametrize(("data", "wanted"), [
    (b"<svg", "not well-formed XML"),
    (b"<html/>", "not an SVG"),
    (svg('width="500" height="1000" viewBox="0 0 10 10"'), "width/height"),
    (svg('width="1000" height="1000"'), "no viewBox"),
    (svg('width="1000" height="1000" viewBox="0 0 10"'), "not four numbers"),
    (svg('width="1000" height="1000" viewBox="0 0 10 20"'), "not a square"),
    (svg(body="<script>alert(1)</script>"), "<script>"),
    (svg(body="<foreignObject/>"), "<foreignObject>"),
    (svg(body='<image href="logo.png"/>'), "<image>"),
    (svg(body='<rect onclick="x()"/>'), "event handler"),
    (svg(body='<a href="https://example.com"><rect/></a>'), "links to"),
    (svg(body='<use xlink:href="other.svg#g"/>'), "links to"),
    (svg(body='<rect style="fill:url(https://example.com/x)"/>'), "outside the file"),
    (svg(body="<style>@import url(x.css);</style>"), "<style>"),
])
def test_bad_logo(data: bytes, wanted: str) -> None:
    problems = logo_problems(data)
    assert any(wanted in p for p in problems), problems


def test_every_check_describes_itself() -> None:
    assert {"logos", "organization-logos", "organization-has-website", "organization-relations", "organization-addresses", "people-known", "museum-dates", "museum-visit-places", "organization-locations", "museum-addresses", "museum-locations", "museum-company",
        "audio-course-lecturers", "audio-course-devices", "audio-course-status", "audio-course-reviews",
        "audio-course-covers", "audio-course-links", "audio-course-stalled", "audio-course-duplicates",
        "audio-book-authors", "audio-book-covers", "audio-book-reviews", "audio-book-duplicates"} <= set(checks.CHECKS)
    for chosen in checks.CHECKS.values():
        assert chosen.title and chosen.description and chosen.noun
        assert chosen.dataset in checks.DATASETS
    # every dataset has checks to run from its page
    assert {c.dataset for c in checks.CHECKS.values()} == set(checks.DATASETS)
    assert {name for name, c in checks.CHECKS.items() if c.dataset == "book"} == {"book-covers", "book-links", "book-authors", "book-years", "book-original-languages", "book-original-titles", "book-languages", "book-reads", "book-read-dates", "book-titles", "book-english-titles", "book-title-languages", "book-ratings", "book-duplicates", "book-notes", "book-translations"}


def test_a_name_is_registered_once() -> None:
    with pytest.raises(ValueError, match="twice"):
        checks.check("logos", "again", "logos", "organizations")(lambda session: checks.Result(0, []))
    with pytest.raises(ValueError, match="no dataset"):
        checks.check("plays", "Plays", "plays", "play")(lambda session: checks.Result(0, []))


def fill(engine: Engine) -> None:
    """ Two accounts: alice's organizations are fine; bob has a bad logo, an organization with no logo nor website, and one whose logo is a photo. """
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        bob = User(email="bob@example.com")
        session.add_all([alice, bob])
        session.flush()
        good = Image(owner_id=alice.id, filename="acme.svg", content_type="image/svg+xml", sha256="", data=GOOD)
        bad = Image(owner_id=bob.id, filename="evil.svg", content_type="image/svg+xml", sha256="", data=svg(body="<script/>"))
        photo = Image(owner_id=bob.id, filename="photo.jpg", content_type="image/jpeg", sha256="", data=b"\xff\xd8\xff")
        session.add_all([
            Organization(owner_id=alice.id, name="Acme", image=good, website="https://acme.example"),
            Organization(owner_id=bob.id, name="Evil", image=bad, website="https://web.archive.org/web/2009/http://evil.example/"),
            Organization(owner_id=bob.id, name="Bare"),
            Organization(owner_id=bob.id, name="Bitmap", image=photo, website="https://bitmap.example"),
        ])
        session.commit()


def test_checks_cover_every_account(engine: Engine) -> None:
    fill(engine)
    with Session(engine) as session:
        logos = checks.CHECKS["logos"].run(session)
        assert logos.checked == 2  # the photo is not an SVG
        assert [(p.subject, p.message) for p in logos.problems] == [("evil.svg (image 2, account 2: Evil)", "has a <script> element")]
        missing = checks.CHECKS["organization-logos"].run(session)
        assert missing.checked == 4
        assert [(p.subject, p.message) for p in missing.problems] == [
            ("Bare (organization 3, account 2)", "has no logo"),
            ("Bitmap (organization 4, account 2)", "has a logo that is not an SVG (image/jpeg)"),
        ]
        # each problem says where its row is in the app, and whose it is
        assert [(p.link, p.owner) for p in logos.problems] == [("organizations/2", 2)]
        assert [(p.link, p.owner) for p in missing.problems] == [("organizations/3", 2), ("organizations/4", 2)]
        # a Wayback Machine snapshot is a website too
        websites = checks.CHECKS["organization-has-website"].run(session)
        assert websites.checked == 4
        assert [(p.subject, p.message) for p in websites.problems] == [("Bare (organization 3, account 2)", "has no website")]


def test_checks_api_is_for_admins(app: webtest.TestApp, engine: Engine) -> None:
    app.get("/api/checks", status=401)
    fill(engine)
    sign_in(app, "carol")
    app.get("/api/checks", status=403)
    app.get("/api/checks/logos", status=403)
    with engine.begin() as connection:
        connection.execute(update(User).where(User.id.in_(select(Login.owner_id).where(Login.subject == "google:" + "carol"))).values(role=ROLE_ADMIN))
    listed = app.get("/api/checks").json
    assert sorted(c["name"] for c in listed) == sorted(checks.CHECKS)
    # grouped by dataset, in the order of DATASETS
    order = list(checks.DATASETS)
    assert [order.index(c["dataset"]) for c in listed] == sorted(order.index(c["dataset"]) for c in listed)
    assert listed[0]["dataset_name"] == "Books"
    books = app.get("/api/checks?dataset=book").json
    assert {c["name"] for c in books} == {name for name, c in checks.CHECKS.items() if c.dataset == "book"}
    app.get("/api/checks?dataset=nonesuch", status=404)
    result = app.get("/api/checks/logos").json
    assert (result["ok"], result["checked"], len(result["problems"]), result["dataset"]) == (False, 2, 1, "organizations")
    assert set(result["problems"][0]) == {"subject", "message", "link", "owner"}
    app.get("/api/checks/nonesuch", status=404)


def test_organization_relations(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        session.add(alice)
        session.flush()
        teaching = RelationType(owner_id=alice.id, name="Teaching")
        session.add_all([
            Organization(owner_id=alice.id, name="Acme", relations=[teaching]),
            Organization(owner_id=alice.id, name="Bare"),
        ])
        session.commit()
        result = checks.CHECKS["organization-relations"].run(session)
    assert result.checked == 2
    assert [(p.subject, p.message) for p in result.problems] == [("Bare (organization 2, account 1)", "has no relation type")]


def test_organization_addresses(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        session.add(alice)
        session.flush()
        session.add_all([
            Organization(owner_id=alice.id, name="Acme", street="1 Main St."),
            Organization(owner_id=alice.id, name="Bare"),
            # only spaces is no address either
            Organization(owner_id=alice.id, name="Blank", street="  "),
        ])
        session.commit()
        result = checks.CHECKS["organization-addresses"].run(session)
    assert result.checked == 3
    assert [p.subject for p in result.problems] == ["Bare (organization 2, account 1)", "Blank (organization 3, account 1)"]
    assert {p.message for p in result.problems} == {"has no address"}


def museum(session: Session, name: str, **columns: Any) -> Place:
    """ A museum: a shared place of the kind Museum. """
    kind = session.scalars(select(PlaceKind).where(PlaceKind.name == MUSEUM_KIND)).one()
    return Place(name=name, kinds=[kind], **columns)


def visit(session: Session, owner_id: int, place: Place | None, **columns: Any) -> Visit:
    """ A user's museum visit to place. """
    kind = session.scalars(select(VisitType).where(VisitType.name == MUSEUM_VISIT)).one()
    return Visit(owner_id=owner_id, place=place, type=kind, **columns)


def test_museum_dates(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        session.add(alice)
        session.flush()
        louvre, tate, moma, uffizi = (museum(session, name) for name in ("Louvre", "Tate", "MoMA", "Uffizi"))
        # one no one visited yet has no visit to date
        session.add_all([louvre, tate, moma, uffizi, museum(session, "Prado")])
        session.flush()
        session.add_all([
            # any one precision is a date
            visit(session, alice.id, louvre, date_ymd=datetime.date(2019, 5, 1)), visit(session, alice.id, louvre, date_my="06-2018"),
            visit(session, alice.id, tate, date_y=2015),
            visit(session, alice.id, moma, date_utcz=datetime.datetime(2020, 1, 2, 15, 0)),
            visit(session, alice.id, uffizi),
            # and a visit to a place that is no museum, or to none (an admin deleted it)
            visit(session, alice.id, Place(name="A club"), date_y=2001), visit(session, alice.id, None, date_y=2002),
        ])
        session.commit()
        result = checks.CHECKS["museum-dates"].run(session)
        places = checks.CHECKS["museum-visit-places"].run(session)
    assert result.checked == 7
    assert [(p.subject, p.message, p.link) for p in result.problems] == [("Uffizi (museum visit 5, account 1)", "has no date", f"museums/{uffizi.id}")]
    assert [(p.subject, p.message) for p in places.problems] == [
        ("A club (museum visit 6, account 1)", "is to A club, which is not of the kind Museum"),
        ("No place (museum visit 7, account 1)", "is to no place"),
    ]


def test_locations(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        session.add(alice)
        session.flush()
        session.add_all([
            Organization(owner_id=alice.id, name="Acme", latitude=32.8, longitude=35.0),
            Organization(owner_id=alice.id, name="Lost"),
            museum(session, "Louvre", street="Rue de Rivoli", postcode="75001", latitude=48.86, longitude=2.34),
            museum(session, "Prado", street="Calle de Ruiz de Alarcón 23"),
            museum(session, "Tate", street=" "),
            # a place that is no museum is no museum's problem
            Place(name="A field"),
        ])
        session.commit()
        organizations = checks.CHECKS["organization-locations"].run(session)
        addresses = checks.CHECKS["museum-addresses"].run(session)
        locations = checks.CHECKS["museum-locations"].run(session)
    assert [p.subject for p in organizations.problems] == ["Lost (organization 2, account 1)"]
    assert [p.subject for p in addresses.problems] == ["Tate (place 3, shared)"]
    assert [p.subject for p in locations.problems] == ["Prado (place 2, shared)", "Tate (place 3, shared)"]


def test_museum_company(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        session.add(alice)
        session.flush()
        friend = Person(owner_id=alice.id, first_name="Dana")
        session.add_all([
            visit(session, alice.id, museum(session, "Louvre"), people=[friend]),
            visit(session, alice.id, museum(session, "Prado"), alone=True),
            visit(session, alice.id, museum(session, "Tate")),
            visit(session, alice.id, museum(session, "Uffizi"), alone=True, people=[friend]),
        ])
        session.commit()
        result = checks.CHECKS["museum-company"].run(session)
    assert result.checked == 4
    # the ids follow the order the session flushes in, so only the names are compared
    assert sorted((p.subject.split(" (")[0], p.message) for p in result.problems) == [
        ("Tate", "has no one in With and is not marked alone"),
        ("Uffizi", "is marked alone but has people in With"),
    ]


def test_audio_courses(engine: Engine) -> None:
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        session.add(alice)
        session.flush()
        lecturer = Person(owner_id=alice.id, first_name="Robert", surname="Greenberg")
        phone = Device(owner_id=alice.id, name="Samsung S10")
        cover = Image(owner_id=alice.id, filename="c.jpg", content_type="image/jpeg", sha256="0" * 64, data=b"\xff\xd8")
        good = {"lecturers": [lecturer], "device": phone, "image": cover, "great_courses_slug": "x"}
        session.add_all([
            # every rule kept: finished, rated and reviewed
            AudioCourse(owner_id=alice.id, name="Good", date_ymd=datetime.date(2020, 1, 1), rating=8, review="Fine", **good),
            # in progress a month: not stalled, and not asked for a review
            AudioCourse(owner_id=alice.id, name="Running", started_utcz=now - datetime.timedelta(days=30), **good),
            # no longer sold: a link to any page about it will do
            AudioCourse(
                owner_id=alice.id, name="Out of print", date_y=2016, rating=7, review="ok",
                **dict(good, great_courses_slug="", link="https://example.org/course"),
            ),
            # each of these breaks one rule (or two)
            AudioCourse(owner_id=alice.id, name="Bare", date_y=2019, rating=7, review="ok"),
            AudioCourse(owner_id=alice.id, name="Limbo", **good),
            AudioCourse(owner_id=alice.id, name="Unrated", date_y=2018, review="ok", **good),
            AudioCourse(owner_id=alice.id, name="Stalled", started_utcz=now - datetime.timedelta(days=800), progress="4/24", **good),
            AudioCourse(owner_id=alice.id, name="Twice", date_y=2017, rating=6, review="a", **good),
            AudioCourse(owner_id=alice.id, name="twice ", date_y=2017, rating=6, review="b", **good),
        ])
        session.commit()

        def found(name: str) -> list[tuple[str, str]]:
            return [(p.subject.split(" (")[0], p.message) for p in checks.CHECKS[name].run(session).problems]

        assert found("audio-course-lecturers") == [("Bare", "has no lecturer")]
        assert found("audio-course-devices") == [("Bare", "has no device")]
        assert found("audio-course-covers") == [("Bare", "has no cover")]
        assert found("audio-course-links") == [("Bare", "has no Great Courses slug, Audible ASIN or link")]
        assert found("audio-course-status") == [("Limbo", "has neither a finished date nor a start: is it finished or in progress?")]
        assert found("audio-course-reviews") == [("Unrated", "is finished but has no rating")]
        stalled = checks.CHECKS["audio-course-stalled"].run(session)
        assert stalled.checked == 2
        assert [(p.subject.split(" (")[0], p.message.split(" (")[1]) for p in stalled.problems] == [("Stalled", "800 days, at 4/24)")]
        assert [name for name, _ in found("audio-course-duplicates")] == ["Twice", "twice "]
        # each problem opens its course
        assert [(p.link.split("/")[0], p.owner) for p in stalled.problems] == [("audio-courses", alice.id)]


def test_audio_books(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        session.add(alice)
        session.flush()
        cover = Image(owner_id=alice.id, filename="c.jpg", content_type="image/jpeg", sha256="0" * 64, data=b"\xff\xd8")
        good = {"authors": "Sam Harris"}

        def heard(name: str, *, finished: bool = False, rating: int | None = None, review: str = "", percent: float | None = None, **book: object) -> AudioBook:
            """ A shared book with an MP3 version alice heard. """
            row = AudioBook(name=name, **book)
            version = AudioBookVersion(book=row, kind="mp3", image=cover)
            session.add_all([row, AudioBookHeard(owner_id=alice.id, book=row, rating=rating, review=review),
                             AudioBookListen(owner_id=alice.id, version=version, finished=finished, percent_heard=percent)])
            return row

        # every rule kept: finished, rated and reviewed; one not finished is not asked for a review, and says how far it got
        heard("Good", finished=True, rating=8, review="Fine", **good)
        heard("Halfway", percent=50, **good)
        # the same title with another subtitle is another book
        session.add_all([AudioBook(name="Political Order", subtitle="Volume 1", **good), AudioBook(name="Political Order", subtitle="Volume 2", **good)])
        # a version with no cover
        # each of these breaks one rule
        session.add(AudioBookVersion(book=AudioBook(name="Bare"), kind="mp3"))
        heard("Unreviewed", finished=True, rating=7, **good)
        heard("Nowhere", **good)
        session.add_all([AudioBook(name="Twice", **good), AudioBook(name="twice ", authors="Someone")])
        session.add(AudioBookVersion(book=AudioBook(name="No ASIN", **good), kind="audible", image=cover))
        session.commit()

        def found(name: str) -> list[tuple[str, str]]:
            return [(p.subject.split(" (")[0], p.message) for p in checks.CHECKS[name].run(session).problems]

        assert found("audio-book-authors") == [("Bare", "has no author")]
        assert found("audio-book-covers") == [("Bare", "has no cover")]
        [bare] = checks.CHECKS["audio-book-covers"].run(session).problems
        assert bare.link.split("/")[0] == "audio-book-versions"
        assert found("audio-book-reviews") == [("Unreviewed", "is finished but has no review")]
        assert found("audio-book-version-asins") == [("No ASIN", "has no ASIN")]
        assert found("audio-book-listen-progress") == [("Nowhere", "says neither how much was heard nor how far it got")]
        duplicates = checks.CHECKS["audio-book-duplicates"].run(session).problems
        assert [p.subject.split(" (")[0] for p in duplicates] == ["Twice", "twice "]
        # each problem opens its book: a shared one any admin may; one heard, the account's own
        assert [(p.link.split("/")[0], p.owner) for p in duplicates] == [("audio-books", None)] * 2
        [review] = checks.CHECKS["audio-book-reviews"].run(session).problems
        assert (review.link.split("/")[0], review.owner) == ("audio-books-heard", alice.id)


def test_podcasts(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        session.add(alice)
        session.flush()
        cover = Image(owner_id=alice.id, filename="p.jpg", content_type="image/jpeg", sha256="0" * 64, data=b"\xff\xd8")
        good = Podcast(name="Good", rss_feed="https://feeds.example.com/good", image=cover)
        bare = Podcast(name="Bare")
        trailer = PodcastEpisode(podcast=good, name="Trailer", guid="g1")
        typed = PodcastEpisode(podcast=good, name="Typed in")
        session.add_all([good, bare, trailer, typed])
        session.add_all([
            PodcastHeard(owner_id=alice.id, podcast=good),
            PodcastHeard(owner_id=alice.id, podcast=bare),
            EpisodeHeard(owner_id=alice.id, episode=trailer, date_ymd=datetime.date(2026, 3, 22)),
            EpisodeHeard(owner_id=alice.id, episode=typed),
        ])
        session.commit()

        def found(name: str) -> list[tuple[str, str]]:
            return [(p.subject.split(" (")[0], p.message) for p in checks.CHECKS[name].run(session).problems]

        assert found("podcast-covers") == [("Bare", "has no cover")]
        assert found("podcast-feeds") == [("Bare", "has no RSS feed")]
        assert found("podcast-episode-guids") == [("Typed in", "has no id in the feed")]
        assert found("episode-heard-dates") == [("Typed in", "has no date")]
        problems = checks.CHECKS["episode-heard-dates"].run(session).problems
        assert [(p.link.split("/")[0], p.subject.split(" (")[1]) for p in problems] == [("episodes-heard", f"episode heard {problems[0].link.split('/')[1]}, account {alice.id})")]
        heard = session.scalars(select(PodcastHeard).where(PodcastHeard.podcast_id == good.id)).one()
        # Bare has no episode heard: it is not in Your podcasts, whatever it says
        assert found("podcast-reviews") == [("Good", "has no rating and no review")]
        heard.rating, heard.review = 8, "Fine"
        session.commit()
        assert found("podcast-reviews") == []
        # a shared row is told as everyone's
        assert checks.CHECKS["podcast-covers"].run(session).problems[0].subject == f"Bare (podcast {bare.id}, shared)"


def test_books(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        bob = User(email="bob@example.com")
        session.add_all([alice, bob])
        session.flush()
        cover = Image(owner_id=alice.id, filename="b.jpg", content_type="image/jpeg", sha256="0" * 64, data=b"\xff\xd8")
        # the authors are each account's own people
        ann, bobs_ann = Person(owner_id=alice.id, first_name="Ann"), Person(owner_id=bob.id, first_name="Ann")
        works = {
            "Good": Work(owner_id=alice.id, kind="book", title="Good", creator="Ann", goodreads_id="1", year=1999, original_locale="en"),
            # written in Hebrew, but its only title is an English one
            "Hebrew": Work(owner_id=alice.id, kind="book", title="Hebrew", creator="Ben", simania_id="2", year=2001, original_locale="he"),
            "Bare": Work(owner_id=alice.id, kind="book", title="Bare", creator=""),
            "Twice": Work(owner_id=alice.id, kind="book", title="Twice", creator="Cy", goodreads_id="3", year=1990, original_locale="en"),
            "twice ": Work(owner_id=alice.id, kind="book", title="twice ", creator="cy", goodreads_id="4", year=1990, original_locale="en"),
            # a film is not a book: none of the book checks look at it
            "Film": Work(owner_id=alice.id, kind="film", title="Film", creator=""),
            # bob has the same book as alice: his own row of it
            "Bob's": Work(owner_id=bob.id, kind="book", title="Good", creator="Ann", goodreads_id="1", year=1999, original_locale="en"),
        }
        session.add_all([cover, ann, bobs_ann, *works.values()])
        session.flush()
        session.add_all([
            # every rule kept: read, rated, with a cover and a link
            UserWork(owner_id=alice.id, work_id=works["Good"].id, image_id=cover.id, authors=[ann], reads=[Read(locale="en", rating=8)]),
            # not read yet: no rating asked for, nor the language and the day of a reading that was not
            UserWork(owner_id=alice.id, work_id=works["Hebrew"].id, image_id=cover.id, authors=[ann], reads=[Read(status="wishlist")]),
            # each of these breaks rules
            UserWork(owner_id=alice.id, work_id=works["Bare"].id),
            UserWork(owner_id=alice.id, work_id=works["Twice"].id, image_id=cover.id, authors=[ann], reads=[Read(locale="he", rating=6)]),
            UserWork(owner_id=alice.id, work_id=works["twice "].id, image_id=cover.id, authors=[ann], reads=[Read(locale="he", rating=6)]),
            UserWork(owner_id=alice.id, work_id=works["Film"].id, reads=[Read()]),
            # bob has the same book as alice: two accounts, no duplicate
            UserWork(owner_id=bob.id, work_id=works["Bob's"].id, image_id=cover.id, authors=[bobs_ann], reads=[Read(locale="en", rating=5)]),
        ])
        session.commit()

        def found(name: str) -> list[tuple[str, str]]:
            return [(p.subject.split(" (")[0], p.message) for p in checks.CHECKS[name].run(session).problems]

        assert found("book-covers") == [("Bare", "has no cover")]
        assert found("book-links") == [("Bare", "has neither a Goodreads nor a Simania id")]
        assert found("book-authors") == [("Bare", "has no author")]
        assert found("book-years") == [("Bare", "has no year it came out")]
        assert found("book-original-languages") == [("Bare", "has no original language")]
        # a book has a title in the language it was written in; one that does not say its language is not asked
        assert found("book-original-titles") == [("Hebrew", "was written in Hebrew but has no title in it")]
        works["Hebrew"].titles.append(WorkTitle(locale="he", title="עברית"))
        session.commit()
        assert found("book-original-titles") == []
        # every book has a reading, where its status is; one finished says its language and its day
        assert found("book-reads") == [("Bare", "has no reading")]
        assert found("book-languages") == []
        assert [name for name, _ in found("book-read-dates")] == ["Good", "Twice", "twice ", "Good"]
        good = session.get(UserWork, (alice.id, works["Good"].id))
        assert good is not None
        # the entry goes by its latest dated read
        good.reads = [Read(read_on=datetime.date(2001, 5, 1), locale="he"), Read(read_on=datetime.date(1999, 1, 1), locale="en"), Read()]
        session.commit()
        assert (good.locale, good.finished_on) == ("he", datetime.date(2001, 5, 1))
        assert found("book-languages") == [("Good", "has a reading that does not say the language it was read in")]
        assert [name for name, _ in found("book-read-dates")] == ["Good", "Twice", "twice ", "Good"]
        # it is rated by the latest reading rated, and where it is by a reading still open
        good.reads = [Read(read_on=datetime.date(2001, 5, 1), locale="en", rating=8), Read(read_on=datetime.date(2003, 5, 1), locale="en")]
        session.commit()
        assert (good.status, good.rating) == ("done", 8)
        good.reads = [*good.reads, Read(status="in_progress")]
        session.commit()
        assert (good.status, good.rating, good.finished_on) == ("in_progress", 8, None)
        good.reads = [Read(read_on=datetime.date(2001, 5, 1), locale="en", rating=8)]
        session.commit()
        assert found("book-ratings") == []
        assert checks.CHECKS["book-ratings"].run(session).checked == 4
        bare = session.get(UserWork, (alice.id, works["Bare"].id))
        assert bare is not None
        bare.reads = [Read()]
        session.commit()
        assert found("book-ratings") == [("Bare", "is read but has no rating")]
        assert found("book-languages") == [("Bare", "has a reading that does not say the language it was read in")]
        bare.reads = []
        session.commit()
        assert [name for name, _ in found("book-duplicates")] == ["Twice", "twice "]
        # each problem opens its book on the Books page, for the account that has it
        [bare] = checks.CHECKS["book-covers"].run(session).problems
        assert (bare.link, bare.owner) == (f"book/{works['Bare'].id}", alice.id)
        assert checks.CHECKS["book-covers"].run(session).checked == 6


def test_person_types(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        bob = User(email="bob@example.com")
        session.add_all([alice, bob])
        session.flush()
        family = PersonType(owner_id=alice.id, name="family")
        session.add_all([
            Person(owner_id=alice.id, first_name="Dana", surname="Cohen", types=[family]),
            Person(owner_id=alice.id, first_name="Eli"),
            # a nameless person is named by the description, as everywhere else
            Person(owner_id=bob.id, description="the guide at the Louvre"),
        ])
        session.commit()
        result = checks.CHECKS["people-known"].run(session)
    assert result.checked == 3
    assert [(p.subject, p.message) for p in result.problems] == [
        ("Eli (person 2, account 1)", "has no profession, relation or organization"),
        ("the guide at the Louvre (person 3, account 2)", "has no profession, relation or organization"),
    ]
    assert [(p.link, p.owner) for p in result.problems] == [("people/2", 1), ("people/3", 2)]


def test_person_names(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        session.add(alice)
        session.flush()
        session.add_all([
            Person(owner_id=alice.id, first_name="John", middle_name="Ronald Reuel", surname="Tolkien"),
            Person(owner_id=alice.id, first_name="Shay Zalman Trio"),
            Person(owner_id=alice.id, first_name="Guy", surname="Bar Tor"),
            Person(owner_id=alice.id, description="the guide at the Louvre"),
            Person(owner_id=alice.id, honorific="Dr. Prof.", first_name="Dana"),
        ])
        session.commit()
        result = checks.CHECKS["people-names"].run(session)
    assert result.checked == 5
    assert sorted((p.subject, p.message) for p in result.problems) == [
        ("Dr. Prof. Dana (person 5, account 1)", "honorific has spaces"),
        ("Guy Bar Tor (person 3, account 1)", "surname has spaces"),
        ("Shay Zalman Trio (person 2, account 1)", "first name has spaces"),
    ]


def test_tidy_names_script(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        session.add(alice)
        session.flush()
        session.add_all([
            Person(owner_id=alice.id, first_name="Richard P. Feynman"),
            Person(owner_id=alice.id, first_name="Guy", surname="Bar Tor"),
            Person(owner_id=alice.id, first_name="Open stage"),
            Person(owner_id=alice.id, first_name="Sir Arthur Conan Doyle"),
        ])
        session.commit()
    root = Path(__file__).resolve().parent.parent
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"} | {"DATABASE_URL": url}

    def tidy(*args: str) -> str:
        done = subprocess.run([sys.executable, str(root / "scripts" / "tidy_names.py"), *args], env=env, capture_output=True, text=True, check=True)
        return done.stdout
    assert tidy("--dry-run").splitlines()[-1] == "3 names would change"
    assert tidy().splitlines()[-1] == "3 names changed"
    assert tidy() == "0 names changed\n"
    with Session(engine) as session:
        people = session.scalars(select(Person).order_by(Person.id)).all()
        assert [(p.honorific, p.first_name, p.middle_name, p.surname) for p in people] == [
            ("", "Richard", "P.", "Feynman"), ("", "Guy", "", "Bar-Tor"), ("", "Open stage", "", ""), ("Sir", "Arthur", "Conan", "Doyle"),
        ]
    engine.dispose()


def run_script(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    root = Path(__file__).resolve().parent.parent
    # no PYTHONPATH: the script finds src/ by itself
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"} | {"DATABASE_URL": url}
    return subprocess.run([sys.executable, str(root / "scripts" / "check.py"), *args], env=env, capture_output=True, text=True, check=False)


def test_script(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    fill(engine)
    engine.dispose()
    listed = run_script(url, "--list")
    assert listed.returncode == 0 and "logos" in listed.stdout and "Books (--dataset book):" in listed.stdout
    # one dataset's checks only: the organizations' fail, the books' (none there) pass
    organizations = run_script(url, "--dataset", "organizations")
    assert organizations.returncode == 1 and "FAIL  logos" in organizations.stdout and "book-covers" not in organizations.stdout
    books = run_script(url, "--dataset", "book")
    assert books.returncode == 0, books.stdout + books.stderr
    assert "ok    book-covers: all 0 books pass" in books.stdout and "logos" not in books.stdout
    assert run_script(url, "--dataset", "book", "logos").returncode == 2
    failing = run_script(url)
    assert failing.returncode == 1
    assert "FAIL  logos: 1 problems in 2 logos" in failing.stdout
    assert "evil.svg (image 2, account 2: Evil): has a <script> element" in failing.stdout
    assert run_script(url, "nonesuch").returncode == 2
    with Session(create_engine(url)) as session:
        session.execute(update(Organization).where(Organization.name.in_(["Evil", "Bare", "Bitmap"])).values(image_id=1))
        # an SVG nothing uses is still checked, so the bad one has to go
        session.execute(delete(Image).where(Image.filename == "evil.svg"))
        session.commit()
    # the two logo checks; the sample organizations have no relation types
    passing = run_script(url, "logos", "organization-logos")
    assert passing.returncode == 0, passing.stdout + passing.stderr
    assert "ok    logos: all 1 logos pass" in passing.stdout


def test_youtube(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        session.add(alice)
        session.flush()
        desktop = Device(owner_id=alice.id, name="Desktop")
        good = {"date_y": 2015, "rating": 7, "review": "nice", "device": desktop}
        session.add_all([
            YouTubeVideo(owner_id=alice.id, youtube_id="VNIRUigPxA8", name="Good", **good),
            # one character too many: links to no video
            YouTubeVideo(owner_id=alice.id, youtube_id="JbNJoHFsQncS", name="Long id", **good),
            YouTubeVideo(owner_id=alice.id, youtube_id="5jqXEzplxeo", name="Bare"),
        ])
        session.commit()

        def found(name: str) -> list[tuple[str, str]]:
            return [(p.subject.split(" (")[0], p.message) for p in checks.CHECKS[name].run(session).problems]

        assert found("youtube-ids") == [("Long id", "has the id 'JbNJoHFsQncS', not 11 letters, digits, - and _")]
        assert found("youtube-dates") == [("Bare", "has no date")]
        assert found("youtube-reviews") == [("Bare", "has no rating and no review")]
        assert found("youtube-devices") == [("Bare", "has no device")]
        # each problem opens its video
        assert checks.CHECKS["youtube-devices"].run(session).problems[0].link.startswith("youtube/")


def test_every_page_has_checks() -> None:
    """ Every page of data in the sidebar (the library's kinds, then NAV_GROUPS in js/sidebar.js) is a dataset with checks. """
    app_js = (Path(__file__).resolve().parent.parent / "src" / "myworld" / "static" / "js" / "sidebar.js").read_text(encoding="UTF8")
    groups = re.search(r"const NAV_GROUPS = \[(.*?)\n\];", app_js, re.DOTALL)
    assert groups is not None
    pages = set(KINDS) | set(re.findall(r'"([a-z-]+)"', re.sub(r'\["[A-Z][a-z]+", ', "", groups.group(1))))
    assert "concerts" in pages and "devices" in pages
    assert pages == set(checks.DATASETS)
    for page in pages:
        assert any(c.dataset == page for c in checks.CHECKS.values()), f"{page} has no checks"


def test_concerts(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        session.add(alice)
        session.flush()
        band = Person(owner_id=alice.id, first_name="The Band")
        photo = Image(owner_id=alice.id, filename="p.jpg", content_type="image/jpeg", sha256="0" * 64, data=b"\xff\xd8")
        barby = Place(name="Barby", city=City(name="Tel Aviv"))
        good = {"place": barby, "performers": [band], "image": photo}
        session.add_all([
            # every rule kept
            Concert(owner_id=alice.id, name="Good", date_y=2010, **good),
            # seen on TV: no place asked for
            Concert(owner_id=alice.id, name="On TV", date_y=2011, broadcast=True, **dict(good, place=None)),
            # each of these breaks rules
            Concert(owner_id=alice.id, name="Bare"),
            Concert(owner_id=alice.id, name="Twice", date_y=2012, **good),
            Concert(owner_id=alice.id, name="twice ", date_y=2012, **good),
            # the same name on another date is another concert
            Concert(owner_id=alice.id, name="Twice", date_y=2013, **good),
            # a group on stage is a performer too
            Concert(owner_id=alice.id, name="Group", date_y=2014, **dict(good, performers=[]), groups=[Group(owner_id=alice.id, name="Trio")]),
        ])
        session.commit()

        def found(name: str) -> list[tuple[str, str]]:
            return [(p.subject.split(" (")[0], p.message) for p in checks.CHECKS[name].run(session).problems]

        assert found("concert-dates") == [("Bare", "has no date")]
        assert found("concert-places") == [("Bare", "has no place")]
        assert found("concert-performers") == [("Bare", "has no performer")]
        assert found("concert-photos") == [("Bare", "has no photo")]
        assert [name for name, _ in found("concert-duplicates")] == ["Twice", "twice "]
        assert checks.CHECKS["concert-photos"].run(session).problems[0].link.startswith("concerts/")


def test_groups(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        session.add(alice)
        session.flush()
        roger = Person(owner_id=alice.id, first_name="Roger")
        floyd = Group(owner_id=alice.id, name="Pink Floyd", members=[roger])
        session.add_all([
            # every rule kept: members, and a concert it performed at
            Concert(owner_id=alice.id, name="The Wall", groups=[floyd]),
            # each of these breaks rules
            Group(owner_id=alice.id, name="pink  floyd"),
        ])
        session.commit()

        def found(name: str) -> list[tuple[str, str]]:
            return [(p.subject.split(" (")[0], p.message) for p in checks.CHECKS[name].run(session).problems]

        assert found("group-members") == [("pink  floyd", "has no members")]
        assert found("group-used") == [("pink  floyd", "performed at no concert")]
        assert [subject for subject, _ in found("group-duplicates")] == ["Pink Floyd", "pink  floyd"]
        assert checks.CHECKS["group-members"].run(session).problems[0].link == "groups/2"


def test_places(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        session.add(alice)
        session.flush()
        tel_aviv = City(name="Tel Aviv", country=Country(name="Israel"))
        barby = Place(name="Barby", city=tel_aviv, latitude=32.05, longitude=34.76)
        session.add_all([
            # every rule kept: something happened there, a city and a country, on the map
            Concert(owner_id=alice.id, name="Show", place=barby),
            # each of these breaks rules
            Place(name="Somewhere"),
            Place(name="barby ", city=tel_aviv, latitude=1, longitude=1),
        ])
        session.commit()

        def found(name: str) -> list[tuple[str, str]]:
            return [(p.subject.split(" (")[0], p.message) for p in checks.CHECKS[name].run(session).problems]

        assert found("place-used") == [("Somewhere", "nothing happened there"), ("barby , Tel Aviv", "nothing happened there")]
        assert found("place-cities") == [("Somewhere", "has no city")]
        assert found("place-locations") == [("Somewhere", "has no latitude and longitude")]
        assert [subject for subject, _ in found("place-duplicates")] == ["Barby, Tel Aviv", "barby , Tel Aviv"]
        somewhere = session.scalars(select(Place).where(Place.name == "Somewhere")).one()
        assert checks.CHECKS["place-used"].run(session).problems[0].link == f"places/{somewhere.id}"


def test_enumerations(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        session.add(alice)
        session.flush()
        friend = PersonType(owner_id=alice.id, name="Friend", description="A friend")
        session.add_all([
            friend,
            PersonType(owner_id=alice.id, name="friend ", description="Again"),
            PersonType(owner_id=alice.id, name="Unused"),
            Person(owner_id=alice.id, first_name="Dana", types=[friend]),
            Device(owner_id=alice.id, name="Phone", description="A phone"),
        ])
        session.commit()

        def found(name: str) -> list[tuple[str, str]]:
            return [(p.subject.split(" (")[0], p.message) for p in checks.CHECKS[name].run(session).problems]

        assert sorted(found("person-type-used")) == [("Unused", "is used by nothing"), ("friend ", "is used by nothing")]
        assert found("person-type-descriptions") == [("Unused", "has no description")]
        assert [name for name, _ in found("person-type-duplicates")] == ["Friend", "friend "]
        assert found("device-used") == [("Phone", "is used by nothing")]
        assert found("device-photos") == [("Phone", "has no photo")]
        assert sorted(found("person-type-photos")) == [("Friend", "has no photo"), ("Unused", "has no photo"), ("friend ", "has no photo")]
        assert found("organization-type-used") == []
        [unused] = checks.CHECKS["person-type-descriptions"].run(session).problems
        assert unused.link.startswith("person-types/")


def test_checks_can_be_turned_off(app: webtest.TestApp, engine: Engine) -> None:
    sign_in(app, "carol")
    app.put("/api/disabled-checks/logos", status=403)
    with engine.begin() as connection:
        connection.execute(update(User).where(User.id.in_(select(Login.owner_id).where(Login.subject == "google:" + "carol"))).values(role=ROLE_ADMIN))
    assert all(c["enabled"] for c in app.get("/api/checks").json)
    app.put("/api/disabled-checks/logos", status=204)
    # turning it off again is fine
    app.put("/api/disabled-checks/logos", status=204)
    assert app.get("/api/disabled-checks").json == ["logos"]
    assert {c["name"]: c["enabled"] for c in app.get("/api/checks").json}["logos"] is False
    app.put("/api/disabled-checks/nonesuch", status=404)
    # it is saved: another admin still has it on
    app.post("/auth/logout")
    sign_in(app, "dave")
    with engine.begin() as connection:
        connection.execute(update(User).where(User.id.in_(select(Login.owner_id).where(Login.subject == "google:" + "dave"))).values(role=ROLE_ADMIN))
    assert app.get("/api/disabled-checks").json == []
    app.post("/auth/logout")
    sign_in(app, "carol")
    app.delete("/api/disabled-checks/logos", status=204)
    app.delete("/api/disabled-checks/logos", status=204)
    assert app.get("/api/disabled-checks").json == []
    assert all(c["enabled"] for c in app.get("/api/checks").json)


def test_script_skips_what_an_account_turned_off(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    fill(engine)
    with Session(engine) as session:
        alice = session.scalars(select(User).where(User.email == "alice@example.com")).one()
        session.add(DisabledCheck(owner_id=alice.id, check_name="logos"))
        session.commit()
    engine.dispose()
    # the bad logo fails logos, unless the account that turned it off is named
    assert run_script(url, "logos").returncode == 1
    skipped = run_script(url, "logos", "--email", "alice@example.com")
    assert skipped.returncode == 0, skipped.stdout + skipped.stderr
    assert "off   logos: turned off by alice@example.com" in skipped.stdout
    assert run_script(url, "--email", "nobody@example.com").returncode == 2


def test_more_checks(engine: Engine) -> None:
    """ What is missing, what is said twice and what cannot be, of museums, places, people, books, concerts, organizations and cities. """
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        session.add(alice)
        session.flush()
        me = alice.id
        photo = Image(owner_id=me, filename="p.jpg", content_type="image/jpeg", sha256="1" * 64, data=b"\xff\xd8")
        session.add(photo)
        session.flush()
        france, israel = Country(name="France"), Country(name="Israel")
        paris = City(name="Paris", country=france, region_row=Region(name="Île-de-France", country=france), latitude=48.86, longitude=2.35)
        lyon = City(name="Lyon", country=france, latitude=45.76, longitude=4.84)
        haifa = City(name="Haifa", country=israel)
        author = PersonType(owner_id=me, name="Book Author")
        dana = Person(owner_id=me, first_name="Dana", types=[author], photos=[PersonPhoto(image_id=photo.id, image_source="https://commons.wikimedia.org/x", image_license="CC0", image_author="Ann")])
        twin = Person(owner_id=me, first_name="dana ", types=[author], photos=[PersonPhoto(image_id=photo.id, image_source="https://commons.wikimedia.org/y")])
        loner = Person(owner_id=me, first_name="Lone")
        myself = Person(owner_id=me, first_name="Me", is_self=True)
        session.add_all([france, israel, paris, lyon, haifa, author, dana, twin, loner, myself])
        session.flush()
        works = {title: Work(owner_id=me, kind="book", title=title, creator="x", original_locale=original) for title, original in (("Dune", "en"), ("The Joke", "cs"), ("Esau", "he"), ("Wanted", "en"))}
        session.add_all(works.values())
        session.flush()
        louvre = museum(session, "Louvre", city=paris, street="Rue de Rivoli", image_id=photo.id, website="https://louvre.fr", latitude=48.86, longitude=2.34)
        other = museum(session, " louvre", city=paris, street="Quai", website="louvre", latitude=43.3, longitude=5.37)
        session.add_all([
            louvre, other, museum(session, "Nowhere", street="Nowhere 1"),
            visit(session, me, louvre, rating=9, review="grand"), visit(session, me, other, rating=8), visit(session, me, other),
            Place(name="Olympia", city=paris, street="28 Boulevard des Capucines", image_id=photo.id, image_source="https://x.org/o", image_license="CC BY", image_author="Bo", website="https://olympiahall.com/x"),
            Place(name="A lawn", city=lyon, image_id=photo.id, image_license="CC BY", website="www.lawn.fr"),
            Organization(owner_id=me, name="Acme", city=paris), Organization(owner_id=me, name="ACME"), Organization(owner_id=me, name="Solo", city=haifa),
            Concert(owner_id=me, name="Alone", alone=True, review="fine"),
            Concert(owner_id=me, name="Together", people=[dana]),
            Concert(owner_id=me, name="Both", alone=True, people=[dana], review="odd"),
            Concert(owner_id=me, name="Unsaid"),
            UserWork(owner_id=me, work_id=works["Dune"].id, owned=["en"], reads=[Read(locale="en")], authors=[dana]),
            UserWork(owner_id=me, work_id=works["The Joke"].id, reads=[Read(locale="he")], notes="Written in Czech. was named: Zert"),
            UserWork(owner_id=me, work_id=works["Esau"].id, reads=[Read(locale="he")], notes="was named: Eisav"),
            # not read yet: nothing is asked of it
            UserWork(owner_id=me, work_id=works["Wanted"].id, reads=[Read(status="wishlist")]),
        ])
        session.commit()

        def found(name: str) -> list[tuple[str, str]]:
            return [(p.subject.split(" (")[0], p.message) for p in checks.CHECKS[name].run(session).problems]

        def who(name: str) -> list[str]:
            return [subject for subject, _ in found(name)]

        assert who("museum-photos") == [" louvre, Paris", "Nowhere"]
        assert who("museum-cities") == ["Nowhere"]
        assert found("museum-ratings") == [(" louvre", "has no review"), (" louvre", "has no rating and no review")]
        assert who("museum-duplicates") == [" louvre, Paris", "Louvre, Paris"]
        assert who("place-addresses") == ["A lawn, Lyon"]
        # a museum is a place
        assert who("place-photos") == [" louvre, Paris", "Nowhere"]
        # Lone has no profession: no photo is asked of them; but they are linked to nothing (the user's own row may be)
        assert who("people-photos") == []
        assert who("people-duplicates") == ["Dana", "dana "]
        assert who("people-used") == ["Lone", "dana "]
        assert who("book-notes") == ["The Joke"]
        assert found("book-translations") == [("The Joke", "was read only in translation: written in Czech, read in Hebrew")]
        assert found("concert-company") == [("Both", "is marked alone but has people in With"), ("Unsaid", "has no one in With and is not marked alone")]
        assert who("concert-reviews") == ["Together", "Unsaid"]
        assert who("organization-cities") == ["ACME"]
        assert who("organization-duplicates") == ["ACME", "Acme"]
        # Paris has a region, so Lyon lacks one; Israel's cities have none, which is as good
        assert who("city-regions") == ["Lyon, France"]
        # a credit, once there, says its source and its license (its author need not be known)
        assert found("places-credits") == [("A lawn, Lyon", "has a photo credited with no source")]
        assert found("people-credits") == [("dana ", "has a photo credited with no license")]
        # the second Louvre is in Marseille by its pin
        assert [(subject, message.split(" km ")[1]) for subject, message in found("place-near-city")] == [(" louvre, Paris", "from Paris, the city it is in")]
        assert who("organization-near-city") == []
        assert who("place-websites") == [" louvre, Paris", "A lawn, Lyon"]
        assert checks.CHECKS["place-websites"].description and checks.CHECKS["places-credits"].description and checks.CHECKS["place-near-city"].description


def test_certification_checks(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        session.add(alice)
        session.flush()
        aws = Organization(owner_id=alice.id, name="AWS")
        session.add_all([
            Certification(owner_id=alice.id, name="Architect", organization=aws, kind="professional"),
            # each of these breaks one rule
            Certification(owner_id=alice.id, name="Orphan", kind="instructor"),
            Certification(owner_id=alice.id, name="Kindless", organization=aws),
        ])
        session.commit()
        issuers = checks.CHECKS["certification-issuers"].run(session)
        assert issuers.checked == 3
        orphan = session.scalars(select(Certification).where(Certification.name == "Orphan")).one()
        assert [(p.subject.split(" (")[0], p.message, p.link) for p in issuers.problems] == [("Orphan", "has no issuing organization", f"certifications/{orphan.id}")]
        assert [(p.subject.split(" (")[0], p.message) for p in checks.CHECKS["certification-kinds"].run(session).problems] == [
            ("Kindless", "has no kind (instructor or professional)"),
        ]


def test_trip_lecture_and_rally_checks(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        session.add(alice)
        session.flush()
        bob = Person(owner_id=alice.id, first_name="Bob")
        israel = Country(name="Testland")
        session.add_all([
            Trip(owner_id=alice.id, name="Fine trip", countries=[israel], people=[bob]),
            # no one along and not alone, and no country
            Trip(owner_id=alice.id, name="Gap trip"),
            Lecture(owner_id=alice.id, name="Fine lecture", lecturers=[bob], alone=True),
            # alone with people, and no lecturer
            Lecture(owner_id=alice.id, name="Odd lecture", alone=True, people=[bob]),
            Rally(owner_id=alice.id, name="Fine rally", people=[bob]),
            Rally(owner_id=alice.id, name="Gap rally"),
        ])
        session.commit()

        def who(check_id: str) -> list[tuple[str, str]]:
            return [(p.subject.split(" (")[0], p.message) for p in checks.CHECKS[check_id].run(session).problems]

        assert who("trip-company") == [("Gap trip", "has no one in With and is not marked alone")]
        assert who("trip-countries") == [("Gap trip", "has no country")]
        assert who("lecture-company") == [("Odd lecture", "is marked alone but has people in With")]
        assert who("lecture-lecturers") == [("Odd lecture", "has no lecturer")]
        assert who("rally-company") == [("Gap rally", "has no one in With and is not marked alone")]
        # going along to them is being linked to something
        assert "Bob" not in [p.subject for p in checks.CHECKS["people-used"].run(session).problems]


def test_course_checks(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(email="alice@example.com")
        session.add(alice)
        session.flush()
        teacher = Person(owner_id=alice.id, first_name="Gary")
        session.add_all([
            Course(owner_id=alice.id, name="Fine", provider=Organization(owner_id=alice.id, name="Coursera"), lecturers=[teacher]),
            Course(owner_id=alice.id, name="Through no one"),
        ])
        session.commit()
        assert [(p.subject.split(" (")[0], p.message) for p in checks.CHECKS["course-providers"].run(session).problems] == [("Through no one", "has no provider")]
        # teaching a course is being linked to something
        assert "Gary" not in [p.subject for p in checks.CHECKS["people-used"].run(session).problems]
