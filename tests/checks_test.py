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

import pytest
import webtest
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from myworld import checks
from myworld.checks import logo_problems
from myworld.models import (
    KINDS,
    ROLE_ADMIN,
    AudioCourse,
    Base,
    Concert,
    Device,
    DisabledCheck,
    Group,
    Image,
    Museum,
    Organization,
    Person,
    PersonType,
    Place,
    RelationType,
    User,
    UserWork,
    Work,
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
    assert {"logos", "organization-logos", "organization-relations", "organization-addresses", "people-types", "museum-dates", "organization-locations", "museum-addresses", "museum-locations", "museum-company",
        "audio-course-lecturers", "audio-course-devices", "audio-course-status", "audio-course-reviews",
        "audio-course-covers", "audio-course-links", "audio-course-stalled", "audio-course-duplicates"} <= set(checks.CHECKS)
    for chosen in checks.CHECKS.values():
        assert chosen.title and chosen.description and chosen.noun
        assert chosen.dataset in checks.DATASETS
    # every dataset has checks to run from its page
    assert {c.dataset for c in checks.CHECKS.values()} == set(checks.DATASETS)
    assert {name for name, c in checks.CHECKS.items() if c.dataset == "book"} == {"book-covers", "book-links", "book-authors", "book-ratings", "book-duplicates"}


def test_a_name_is_registered_once() -> None:
    with pytest.raises(ValueError, match="twice"):
        checks.check("logos", "again", "logos", "organizations")(lambda session: checks.Result(0, []))
    with pytest.raises(ValueError, match="no dataset"):
        checks.check("plays", "Plays", "plays", "play")(lambda session: checks.Result(0, []))


def fill(engine: Engine) -> None:
    """ Two accounts: alice's organizations are fine, bob has a bad logo and an organization without one. """
    with Session(engine) as session:
        alice = User(google_sub="alice", email="alice@example.com")
        bob = User(google_sub="bob", email="bob@example.com")
        session.add_all([alice, bob])
        session.flush()
        good = Image(owner_id=alice.id, filename="acme.svg", content_type="image/svg+xml", sha256="", data=GOOD)
        bad = Image(owner_id=bob.id, filename="evil.svg", content_type="image/svg+xml", sha256="", data=svg(body="<script/>"))
        photo = Image(owner_id=bob.id, filename="photo.jpg", content_type="image/jpeg", sha256="", data=b"\xff\xd8\xff")
        session.add_all([
            Organization(owner_id=alice.id, name="Acme", image=good),
            Organization(owner_id=bob.id, name="Evil", image=bad),
            Organization(owner_id=bob.id, name="Bare"),
            photo,
        ])
        session.commit()


def test_checks_cover_every_account(engine: Engine) -> None:
    fill(engine)
    with Session(engine) as session:
        logos = checks.CHECKS["logos"].run(session)
        assert logos.checked == 2  # the photo is not an SVG
        assert [(p.subject, p.message) for p in logos.problems] == [("evil.svg (image 2, account 2: Evil)", "has a <script> element")]
        missing = checks.CHECKS["organization-logos"].run(session)
        assert missing.checked == 3
        assert [p.subject for p in missing.problems] == ["Bare (organization 3, account 2)"]
        # each problem says where its row is in the app, and whose it is
        assert [(p.link, p.owner) for p in logos.problems] == [("organizations/2", 2)]
        assert [(p.link, p.owner) for p in missing.problems] == [("organizations/3", 2)]


def test_checks_api_is_for_admins(app: webtest.TestApp, engine: Engine) -> None:
    app.get("/api/checks", status=401)
    fill(engine)
    sign_in(app, "carol")
    app.get("/api/checks", status=403)
    app.get("/api/checks/logos", status=403)
    with engine.begin() as connection:
        connection.execute(update(User).where(User.google_sub == "carol").values(role=ROLE_ADMIN))
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
        alice = User(google_sub="alice", email="alice@example.com")
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
        alice = User(google_sub="alice", email="alice@example.com")
        session.add(alice)
        session.flush()
        session.add_all([
            Organization(owner_id=alice.id, name="Acme", address="1 Main St., Haifa, Israel"),
            Organization(owner_id=alice.id, name="Bare"),
            # only spaces is no address either
            Organization(owner_id=alice.id, name="Blank", address="  "),
        ])
        session.commit()
        result = checks.CHECKS["organization-addresses"].run(session)
    assert result.checked == 3
    assert [p.subject for p in result.problems] == ["Bare (organization 2, account 1)", "Blank (organization 3, account 1)"]
    assert {p.message for p in result.problems} == {"has no address"}


def test_museum_dates(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(google_sub="alice", email="alice@example.com")
        session.add(alice)
        session.flush()
        session.add_all([
            # any one precision is a date
            Museum(owner_id=alice.id, name="Louvre", date_ymd=datetime.date(2019, 5, 1)),
            Museum(owner_id=alice.id, name="Prado", date_my="06-2018"),
            Museum(owner_id=alice.id, name="Tate", date_y=2015),
            Museum(owner_id=alice.id, name="MoMA", date_utcz=datetime.datetime(2020, 1, 2, 15, 0)),
            Museum(owner_id=alice.id, name="Uffizi"),
        ])
        session.commit()
        result = checks.CHECKS["museum-dates"].run(session)
    assert result.checked == 5
    assert [(p.subject, p.message) for p in result.problems] == [("Uffizi (museum visit 5, account 1)", "has no date")]


def test_locations(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(google_sub="alice", email="alice@example.com")
        session.add(alice)
        session.flush()
        session.add_all([
            Organization(owner_id=alice.id, name="Acme", latitude=32.8, longitude=35.0),
            Organization(owner_id=alice.id, name="Lost"),
            Museum(owner_id=alice.id, name="Louvre", address="Rue de Rivoli, 75001 Paris, France", latitude=48.86, longitude=2.34),
            Museum(owner_id=alice.id, name="Prado", address="Calle de Ruiz de Alarcón 23, Madrid, Spain"),
            Museum(owner_id=alice.id, name="Tate", address=" "),
        ])
        session.commit()
        organizations = checks.CHECKS["organization-locations"].run(session)
        addresses = checks.CHECKS["museum-addresses"].run(session)
        locations = checks.CHECKS["museum-locations"].run(session)
    assert [p.subject for p in organizations.problems] == ["Lost (organization 2, account 1)"]
    assert [p.subject for p in addresses.problems] == ["Tate (museum visit 3, account 1)"]
    assert [p.subject for p in locations.problems] == ["Prado (museum visit 2, account 1)", "Tate (museum visit 3, account 1)"]


def test_museum_company(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(google_sub="alice", email="alice@example.com")
        session.add(alice)
        session.flush()
        friend = Person(owner_id=alice.id, first_name="Dana")
        session.add_all([
            Museum(owner_id=alice.id, name="Louvre", people=[friend]),
            Museum(owner_id=alice.id, name="Prado", alone=True),
            Museum(owner_id=alice.id, name="Tate"),
            Museum(owner_id=alice.id, name="Uffizi", alone=True, people=[friend]),
        ])
        session.commit()
        result = checks.CHECKS["museum-company"].run(session)
    assert result.checked == 4
    # the ids follow the order the session flushes in, so only the names are compared
    assert [(p.subject.split(" (")[0], p.message) for p in result.problems] == [
        ("Tate", "has no one in With and is not marked alone"),
        ("Uffizi", "is marked alone but has people in With"),
    ]


def test_audio_courses(engine: Engine) -> None:
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    with Session(engine) as session:
        alice = User(google_sub="alice", email="alice@example.com")
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


def test_books(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(google_sub="alice", email="alice@example.com")
        bob = User(google_sub="bob", email="bob@example.com")
        session.add_all([alice, bob])
        session.flush()
        cover = Image(owner_id=alice.id, filename="b.jpg", content_type="image/jpeg", sha256="0" * 64, data=b"\xff\xd8")
        # the authors are each account's own people
        ann, bobs_ann = Person(owner_id=alice.id, first_name="Ann"), Person(owner_id=bob.id, first_name="Ann")
        works = {
            "Good": Work(kind="book", title="Good", creator="Ann", goodreads_id="1"),
            "Hebrew": Work(kind="book", title="Hebrew", creator="Ben", simania_id="2"),
            "Bare": Work(kind="book", title="Bare", creator=""),
            "Twice": Work(kind="book", title="Twice", creator="Cy", goodreads_id="3"),
            "twice ": Work(kind="book", title="twice ", creator="cy", goodreads_id="4"),
            # a film is not a book: none of the book checks look at it
            "Film": Work(kind="film", title="Film", creator=""),
        }
        session.add_all([cover, ann, bobs_ann, *works.values()])
        session.flush()
        session.add_all([
            # every rule kept: read, rated, with a cover and a link
            UserWork(user_id=alice.id, work_id=works["Good"].id, status="done", rating=8, image_id=cover.id, authors=[ann]),
            # not read yet: no rating asked for
            UserWork(user_id=alice.id, work_id=works["Hebrew"].id, status="wishlist", image_id=cover.id, authors=[ann]),
            # each of these breaks rules
            UserWork(user_id=alice.id, work_id=works["Bare"].id, status="done"),
            UserWork(user_id=alice.id, work_id=works["Twice"].id, status="done", rating=6, image_id=cover.id, authors=[ann]),
            UserWork(user_id=alice.id, work_id=works["twice "].id, status="done", rating=6, image_id=cover.id, authors=[ann]),
            UserWork(user_id=alice.id, work_id=works["Film"].id, status="done"),
            # bob has the same book as alice: two accounts, no duplicate
            UserWork(user_id=bob.id, work_id=works["Good"].id, status="done", rating=5, image_id=cover.id, authors=[bobs_ann]),
        ])
        session.commit()

        def found(name: str) -> list[tuple[str, str]]:
            return [(p.subject.split(" (")[0], p.message) for p in checks.CHECKS[name].run(session).problems]

        assert found("book-covers") == [("Bare", "has no cover")]
        assert found("book-links") == [("Bare", "has neither a Goodreads nor a Simania id")]
        assert found("book-authors") == [("Bare", "has no author")]
        assert found("book-ratings") == [("Bare", "is read but has no rating")]
        assert checks.CHECKS["book-ratings"].run(session).checked == 5
        assert [name for name, _ in found("book-duplicates")] == ["Twice", "twice "]
        # each problem opens its book on the Books page, for the account that has it
        [bare] = checks.CHECKS["book-covers"].run(session).problems
        assert (bare.link, bare.owner) == (f"book/{works['Bare'].id}", alice.id)
        assert checks.CHECKS["book-covers"].run(session).checked == 6


def test_person_types(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(google_sub="alice", email="alice@example.com")
        bob = User(google_sub="bob", email="bob@example.com")
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
        result = checks.CHECKS["people-types"].run(session)
    assert result.checked == 3
    assert [(p.subject, p.message) for p in result.problems] == [
        ("Eli (person 2, account 1)", "has no type"),
        ("the guide at the Louvre (person 3, account 2)", "has no type"),
    ]
    assert [(p.link, p.owner) for p in result.problems] == [("people/2", 1), ("people/3", 2)]


def test_person_names(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(google_sub="alice", email="alice@example.com")
        session.add(alice)
        session.flush()
        session.add_all([
            Person(owner_id=alice.id, first_name="John", middle_name="Ronald Reuel", surname="Tolkien"),
            Person(owner_id=alice.id, first_name="Shay Zalman Trio"),
            Person(owner_id=alice.id, first_name="Guy", surname="Bar Tor"),
            Person(owner_id=alice.id, description="the guide at the Louvre"),
        ])
        session.commit()
        result = checks.CHECKS["people-names"].run(session)
    assert result.checked == 4
    assert sorted((p.subject, p.message) for p in result.problems) == [
        ("Guy Bar Tor (person 3, account 1)", "surname has spaces"),
        ("Shay Zalman Trio (person 2, account 1)", "first name has spaces"),
    ]


def test_tidy_names_script(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        alice = User(google_sub="alice", email="alice@example.com")
        session.add(alice)
        session.flush()
        session.add_all([
            Person(owner_id=alice.id, first_name="Richard P. Feynman"),
            Person(owner_id=alice.id, first_name="Guy", surname="Bar Tor"),
            Person(owner_id=alice.id, first_name="Open stage"),
        ])
        session.commit()
    root = Path(__file__).resolve().parent.parent
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"} | {"DATABASE_URL": url}

    def tidy(*args: str) -> str:
        done = subprocess.run([sys.executable, str(root / "scripts" / "tidy_names.py"), *args], env=env, capture_output=True, text=True, check=True)
        return done.stdout
    assert tidy("--dry-run").splitlines()[-1] == "2 names would change"
    assert tidy().splitlines()[-1] == "2 names changed"
    assert tidy() == "0 names changed\n"
    with Session(engine) as session:
        people = session.scalars(select(Person).order_by(Person.id)).all()
        assert [(p.first_name, p.middle_name, p.surname) for p in people] == [
            ("Richard", "P.", "Feynman"), ("Guy", "", "Bar-Tor"), ("Open stage", "", ""),
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
        session.execute(update(Organization).where(Organization.name.in_(["Evil", "Bare"])).values(image_id=1))
        # an SVG nothing uses is still checked, so the bad one has to go
        session.execute(delete(Image).where(Image.filename == "evil.svg"))
        session.commit()
    # the two logo checks; the sample organizations have no relation types
    passing = run_script(url, "logos", "organization-logos")
    assert passing.returncode == 0, passing.stdout + passing.stderr
    assert "ok    logos: all 1 logos pass" in passing.stdout


def test_youtube(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(google_sub="alice", email="alice@example.com")
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
    """ Every page of data in the sidebar (the library's kinds, then NAV_GROUPS in app.js) is a dataset with checks. """
    app_js = (Path(__file__).resolve().parent.parent / "src" / "myworld" / "static" / "app.js").read_text(encoding="UTF8")
    groups = re.search(r"const NAV_GROUPS = \[(.*?)\n\];", app_js, re.DOTALL)
    assert groups is not None
    pages = set(KINDS) | set(re.findall(r'"([a-z-]+)"', re.sub(r'\["[A-Z][a-z]+", ', "", groups.group(1))))
    assert "concerts" in pages and "devices" in pages
    assert pages == set(checks.DATASETS)
    for page in pages:
        assert any(c.dataset == page for c in checks.CHECKS.values()), f"{page} has no checks"


def test_concerts(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(google_sub="alice", email="alice@example.com")
        session.add(alice)
        session.flush()
        band = Person(owner_id=alice.id, first_name="The Band")
        photo = Image(owner_id=alice.id, filename="p.jpg", content_type="image/jpeg", sha256="0" * 64, data=b"\xff\xd8")
        barby = Place(owner_id=alice.id, name="Barby", city="Tel Aviv")
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
        alice = User(google_sub="alice", email="alice@example.com")
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
        alice = User(google_sub="alice", email="alice@example.com")
        session.add(alice)
        session.flush()
        barby = Place(owner_id=alice.id, name="Barby", city="Tel Aviv", country="Israel", latitude=32.05, longitude=34.76)
        session.add_all([
            # every rule kept: something happened there, a city and a country, on the map
            Concert(owner_id=alice.id, name="Show", place=barby),
            # each of these breaks rules
            Place(owner_id=alice.id, name="Somewhere"),
            Place(owner_id=alice.id, name="barby ", city="tel aviv", country="Israel", latitude=1, longitude=1),
        ])
        session.commit()

        def found(name: str) -> list[tuple[str, str]]:
            return [(p.subject.split(" (")[0], p.message) for p in checks.CHECKS[name].run(session).problems]

        assert found("place-used") == [("Somewhere", "nothing happened there"), ("barby , tel aviv", "nothing happened there")]
        assert found("place-cities") == [("Somewhere", "has no city and no country")]
        assert found("place-locations") == [("Somewhere", "has no latitude and longitude")]
        assert [subject for subject, _ in found("place-duplicates")] == ["Barby, Tel Aviv", "barby , tel aviv"]
        assert checks.CHECKS["place-used"].run(session).problems[0].link == "places/2"


def test_enumerations(engine: Engine) -> None:
    with Session(engine) as session:
        alice = User(google_sub="alice", email="alice@example.com")
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
        assert found("organization-type-used") == []
        [unused] = checks.CHECKS["person-type-descriptions"].run(session).problems
        assert unused.link.startswith("person-types/")


def test_checks_can_be_turned_off(app: webtest.TestApp, engine: Engine) -> None:
    sign_in(app, "carol")
    app.put("/api/disabled-checks/logos", status=403)
    with engine.begin() as connection:
        connection.execute(update(User).where(User.google_sub == "carol").values(role=ROLE_ADMIN))
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
        connection.execute(update(User).where(User.google_sub == "dave").values(role=ROLE_ADMIN))
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
        session.add(DisabledCheck(user_id=alice.id, check_name="logos"))
        session.commit()
    engine.dispose()
    # the bad logo fails logos, unless the account that turned it off is named
    assert run_script(url, "logos").returncode == 1
    skipped = run_script(url, "logos", "--email", "alice@example.com")
    assert skipped.returncode == 0, skipped.stdout + skipped.stderr
    assert "off   logos: turned off by alice@example.com" in skipped.stdout
    assert run_script(url, "--email", "nobody@example.com").returncode == 2
