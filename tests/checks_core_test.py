"""
What the checks are made of (myworld/checks/core.py): the register, the
readers every check shares and the way a problem is told; and the small
functions the checks of several pages are built from.
"""

import datetime as dt
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld import checks
from myworld.checks import common, core
from myworld.models import (
    MUSEUM_KIND,
    MUSEUM_VISIT,
    AudioCourse,
    City,
    Concert,
    Country,
    Device,
    Group,
    Organization,
    Person,
    PersonType,
    Place,
    PlaceKind,
    Read,
    User,
    UserWork,
    Visit,
    VisitType,
    Work,
    YouTubeVideo,
)
from myworld.timeutil import naive_utc

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


def test_squashed() -> None:
    assert core.squashed("  Pink   Floyd ") == "pink floyd"
    assert core.squashed("PINK\tFLOYD") == core.squashed("pink floyd")
    assert core.squashed("Straße") == core.squashed("STRASSE")
    assert core.squashed("") == ""


def test_same() -> None:
    assert core.same([], len) == []
    assert core.same(["a", "b", "c"], str) == []
    # those alike are together, in the order they came; one of a kind is left out
    assert core.same(["a", "bb", "c", "dd", "eee", "f"], len) == [["a", "c", "f"], ["bb", "dd"]]
    assert core.same([1, 1, 1], lambda n: n) == [[1, 1, 1]]


def test_a_check_is_registered_once_for_a_page_there_is(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core, "CHECKS", dict(core.CHECKS))

    def run(_session: Session) -> core.Result:
        """  Says   what it
        looks at.  """
        return core.Result(checked=0, problems=[])

    with pytest.raises(ValueError, match="no dataset called 'unicorns'"):
        core.check("unicorn-horns", "Every unicorn has a horn", "unicorns", "unicorns")
    assert core.check("concert-encores", "Every concert has an encore", "concerts", "concerts")(run) is run
    made = core.CHECKS["concert-encores"]
    assert (made.title, made.noun, made.dataset, made.run) == ("Every concert has an encore", "concerts", "concerts", run)
    # its description is its docstring, on one line
    assert made.description == "Says what it looks at."
    with pytest.raises(ValueError, match="'concert-encores' is registered twice"):
        core.check("concert-encores", "Again", "concerts", "concerts")(run)


def test_every_module_registered_its_checks() -> None:
    assert checks.CHECKS is core.CHECKS
    for dataset in checks.DATASETS:
        assert any(c.dataset == dataset for c in checks.CHECKS.values()), dataset
    # the ones made by a function, once for each page
    for name in ("places-credits", "people-credits", "place-near-city", "group-websites", "device-duplicates", "book-covers", "relation-type-used"):
        assert name in checks.CHECKS, name
    assert all(c.description and c.title and c.noun for c in checks.CHECKS.values())


def test_result_json_sends_only_so_many_problems() -> None:
    chosen = checks.CHECKS["concert-dates"]
    none = checks.result_json(chosen, checks.Result(checked=3, problems=[]))
    assert none == {"name": "concert-dates", "title": chosen.title, "noun": "concerts", "dataset": "concerts", "checked": 3, "ok": True, "problem_count": 0, "problems": []}
    many = [checks.Problem(f"Concert {n}", "has no date", f"concerts/{n}", 1) for n in range(checks.PROBLEMS_SHOWN + 20)]
    sent = checks.result_json(chosen, checks.Result(checked=len(many), problems=many))
    assert (sent["ok"], sent["problem_count"], len(sent["problems"])) == (False, checks.PROBLEMS_SHOWN + 20, checks.PROBLEMS_SHOWN)
    assert sent["problems"][0] == {"subject": "Concert 0", "message": "has no date", "link": "concerts/0", "owner": 1}


@pytest.fixture(name="world")
def fixture_world(engine: Engine) -> Any:
    """ One row of every kind a problem can be about, of two accounts. """
    with Session(engine) as session:
        alice, bob = User(email="alice@example.com"), User(email="bob@example.com")
        session.add_all([alice, bob])
        session.flush()
        # shared: no account's
        france = Country(name="France")
        paris = City(name="Paris", country=france)
        nowhere = City(name="Nowhere")
        book = Work(owner_id=alice.id, kind="book", title="Dune", creator="Frank Herbert")
        session.add_all([
            france, paris, nowhere, book,
            Place(name="Olympia", city=paris), Place(name="A field"),
            Concert(owner_id=alice.id, name="Jarrett"), AudioCourse(owner_id=alice.id, name="Logic"), YouTubeVideo(owner_id=alice.id, youtube_id="dQw4w9WgXcQ", name="A song"),
            Person(owner_id=alice.id, first_name="Dana", surname="Levi"), Person(owner_id=alice.id, first_name="Avi", surname="Cohen"),
            Person(owner_id=bob.id, first_name="Zed"), Person(owner_id=alice.id, first_name="Avi", surname="Adler"),
            Organization(owner_id=alice.id, name="ACME"), Group(owner_id=alice.id, name="Trio"),
            Device(owner_id=alice.id, name="Phone"), PersonType(owner_id=alice.id, name="Pianist"),
        ])
        session.flush()
        # a museum (a shared place of the kind Museum) and alice's visit to it
        museum = session.scalars(select(PlaceKind).where(PlaceKind.name == MUSEUM_KIND)).one()
        louvre = Place(name="Louvre", city=paris, kinds=[museum])
        session.add(louvre)
        visited = session.scalars(select(VisitType).where(VisitType.name == MUSEUM_VISIT)).one()
        session.add_all([louvre, Visit(owner_id=alice.id, place=louvre, type=visited)])
        session.add(UserWork(owner_id=alice.id, work_id=book.id, reads=[Read()]))
        session.commit()
        yield session


@pytest.mark.parametrize(("model", "subject", "link"), [
    (Concert, "Jarrett (concert 1, account 1)", "concerts/1"),
    (Visit, "Louvre (museum visit 1, account 1)", "museums/3"),
    (AudioCourse, "Logic (audio course 1, account 1)", "audio-courses/1"),
    (YouTubeVideo, "A song (YouTube video 1, account 1)", "youtube/1"),
    (Organization, "ACME (organization 1, account 1)", "organizations/1"),
    (Group, "Trio (group 1, account 1)", "groups/1"),
    (Device, "Phone (device 1, account 1)", "devices/1"),
    (PersonType, "Pianist (profession 1, account 1)", "person-types/1"),
])
def test_a_problem_says_what_it_is_about(world: Session, model: Any, subject: str, link: str) -> None:
    row = world.get(model, 1)
    assert core.problem(row, "is wrong") == core.Problem(subject, "is wrong", link, 1)


def test_a_problem_with_a_shared_row_is_no_accounts(world: Session) -> None:
    assert core.problem(world.get(Country, 1), "is wrong") == core.Problem("France (country 1, shared)", "is wrong", "countries/1", None)


def test_a_problem_tells_a_place_with_its_city(world: Session) -> None:
    told = {p.subject for p in (core.problem(row, "x") for row in core.rows(world, Place))}
    assert told == {"Olympia, Paris (place 1, shared)", "A field (place 2, shared)", "Louvre, Paris (place 3, shared)"}
    told = {p.subject for p in (core.problem(row, "x") for row in core.rows(world, City))}
    assert told == {"Paris, France (city 1, shared)", "Nowhere (city 2, shared)"}
    entry = core.entries_of(world, "book")[0]
    assert core.problem(entry, "x") == core.Problem(f"Dune (book {entry.work_id}, account 1)", "x", f"book/{entry.work_id}", 1)
    assert core.entries_of(world, "film") == []


def test_rows_are_by_account_then_by_name(world: Session) -> None:
    assert [(p.owner_id, p.name) for p in core.rows(world, Person)] == [(1, "Avi Adler"), (1, "Avi Cohen"), (1, "Dana Levi"), (2, "Zed")]
    assert [c.name for c in core.rows(world, City)] == ["Nowhere", "Paris"]
    assert core.rows(world, Group)[0].name == "Trio"


def test_twice(world: Session) -> None:
    people = core.rows(world, Person)
    assert core.twice(people, lambda p: p.id, "name") == []
    found = core.twice(people, lambda p: (p.owner_id, p.first_name), "first name")
    assert [(p.subject.split(" (")[0], p.message) for p in found] == [
        ("Avi Adler", "has the same first name as 1 other of the account"), ("Avi Cohen", "has the same first name as 1 other of the account"),
    ]
    # told with what the rows are called, one or several
    found = core.twice(people, lambda p: p.owner_id, "account", "person")
    assert [p.message for p in found] == ["has the same account as 2 other persons of the account"] * 3
    assert [p.message for p in core.twice(people[:2], lambda p: p.owner_id, "account", "person")] == ["has the same account as 1 other person of the account"] * 2


def test_ids_and_dated(world: Session) -> None:
    assert core.ids(world, Place.city_id) == {1}
    assert core.ids(world, Place.city_id, City.country_id) == {1}
    assert core.ids(world, Organization.city_id) == set()
    concert = world.get(Concert, 1)
    assert concert is not None
    assert not core.dated(concert)
    for field, value in (("date_y", 2003), ("date_my", "07-2003"), ("date_ymd", dt.date(2003, 7, 14)), ("date_utcz", naive_utc(2003, 7, 14, 20, 0))):
        setattr(concert, field, value)
        assert core.dated(concert), field
        setattr(concert, field, "" if field == "date_my" else None)
    assert not core.dated(concert)


def test_one_of() -> None:
    assert core.one_of("devices") == "device"
    assert core.one_of("person-types") == "profession"
    assert core.one_of("organization-types") == "organization tag"
    assert core.one_of("relation-types") == "organization relation type"


@pytest.mark.parametrize(("credit", "gaps"), [
    (("", "", ""), []),
    (("  ", "\t", ""), []),
    (("https://example.com/a", "CC0", "Ann"), []),
    (("https://example.com/a", "", ""), ["license"]),
    (("", "CC0", ""), ["source"]),
    (("", "", "Ann"), ["source", "license"]),
    # who made it is not asked for
    (("https://example.com/a", "CC0", " "), []),
])
def test_a_credit_says_its_source_and_license_or_is_absent(credit: tuple[str, str, str], gaps: list[str]) -> None:
    assert common.credit_gaps(*credit) == gaps


def test_km() -> None:
    km = common.km
    tel_aviv, jerusalem, paris = (32.0853, 34.7818), (31.7683, 35.2137), (48.8566, 2.3522)
    assert km(paris, paris) == 0
    assert km(tel_aviv, jerusalem) == pytest.approx(54, abs=2)
    assert km(tel_aviv, paris) == pytest.approx(3280, abs=30)
    assert km(tel_aviv, paris) == pytest.approx(km(paris, tel_aviv))
    # a quarter of the way round, and across the date line
    assert km((0, 0), (0, 90)) == pytest.approx(10008, abs=5)
    assert km((0, 179.5), (0, -179.5)) == pytest.approx(111, abs=2)
    assert km(tel_aviv, jerusalem) > common.NEAR_KM > km(tel_aviv, (32.07288, 34.78746))


@pytest.mark.parametrize("address", [
    "https://veltzer.org", "http://example.com/", "https://www.example.co.il/a/b?c=d#e", "https://mod.gov.il/%D7%90%D7%92%D7%A4%D7%99%D7%9D",
    "https://sub.domain.example.org/path.html",
])
def test_a_website_is_an_address(address: str) -> None:
    assert common.WEBSITE.fullmatch(address)


@pytest.mark.parametrize("address", [
    "", "example.com", "www.example.com", "ftp://example.com", "https://localhost", "https://example", "https://example.com/a b", "https:// example.com",
    "see https://example.com", "https://.com", "mailto:someone@example.com",
])
def test_what_is_no_address(address: str) -> None:
    assert not common.WEBSITE.fullmatch(address)
