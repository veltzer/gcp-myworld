"""
What ties a person to the user (myworld.connections): every table that
points at a person is either in PERSON_LINKS (shown in the person's
connections, counted by the people-used check) or said to be shown
elsewhere or not to be a link at all; and every link finds its rows, through
the API too, a shared view showing only its own pages. A table added that
names people and is left out of all three fails here.
"""

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld import checks, connections
from myworld.checks.core import DATASETS
from myworld.models import (
    MUSEUM_VISIT,
    AudioCourse,
    Concert,
    Course,
    Film,
    FilmWatch,
    Group,
    Lecture,
    Loan,
    Person,
    Place,
    Rally,
    Trip,
    User,
    UserWork,
    Visit,
    VisitType,
    Work,
)
from tests.conftest import sign_in

if TYPE_CHECKING:
    import webtest
    from sqlalchemy.engine import Engine


def test_every_column_that_names_a_person_is_accounted_for() -> None:
    linked = {f"{link.column.table.name}.{link.column.name}" for link in connections.PERSON_LINKS}
    accounted = linked | set(connections.LINKED_ELSEWHERE) | set(connections.NOT_A_LINK)
    missing = [column for column in connections.columns_to_people() if column not in accounted]
    assert missing == [], f"columns that name a person, shown nowhere: add each to connections.PERSON_LINKS (or say why not): {missing}"
    # and nothing is said of a column there is not
    assert accounted <= set(connections.columns_to_people())
    assert {f"{c.table.name}.{c.name}" for c in connections.LINKED_ELSEWHERE_COLUMNS} == set(connections.LINKED_ELSEWHERE)


def test_every_link_is_on_a_page() -> None:
    for link in connections.PERSON_LINKS:
        assert link.view in DATASETS, link


def _everything_names(session: Session, alice: User, bob: Person) -> None:
    """ One row of every kind PERSON_LINKS reads, each naming bob. """
    museum_visit = session.scalars(select(VisitType).where(VisitType.name == MUSEUM_VISIT)).one()
    louvre = Place(name="Louvre")
    film = Film(name="Heat", kind="film")
    work = Work(owner_id=alice.id, kind="book", title="Bob's Book", creator="Bob")
    session.add_all([louvre, film, work])
    session.flush()
    session.add_all([
        Concert(owner_id=alice.id, name="Together", people=[bob]),
        Concert(owner_id=alice.id, name="Bob live", performers=[bob]),
        Visit(owner_id=alice.id, place=louvre, type=museum_visit, people=[bob]),
        Trip(owner_id=alice.id, name="Kiev", people=[bob]),
        Lecture(owner_id=alice.id, name="Heard with Bob", people=[bob]),
        Lecture(owner_id=alice.id, name="Bob speaks", lecturers=[bob]),
        Rally(owner_id=alice.id, name="Memorial", people=[bob]),
        FilmWatch(owner_id=alice.id, film=film, people=[bob]),
        FilmWatch(owner_id=alice.id, film=film, recommended_by=bob),
        AudioCourse(owner_id=alice.id, name="Bob's course", lecturers=[bob]),
        Course(owner_id=alice.id, name="Bob's class", lecturers=[bob]),
        UserWork(owner_id=alice.id, work_id=work.id, work=work, authors=[bob]),
        Group(owner_id=alice.id, name="Bob's band", members=[bob]),
        Loan(owner_id=alice.id, name="The Hobbit", person=bob),
    ])
    session.commit()


def test_every_link_finds_its_rows(app: webtest.TestApp, engine: Engine) -> None:
    sign_in(app)
    with Session(engine) as session:
        alice = session.scalars(select(User).where(User.email == "alice@example.com")).one()
        bob = Person(owner_id=alice.id, first_name="Bob")
        loner = Person(owner_id=alice.id, first_name="Nobody")
        session.add_all([bob, loner])
        session.flush()
        _everything_names(session, alice, bob)
        bob_id, loner_id = bob.id, loner.id
        # the check counts every one of them as a link; one with none is not linked
        used = checks.CHECKS["people-used"].run(session)
        assert [p.subject.split(" (")[0] for p in used.problems] == ["Nobody"]
    groups = {g["label"]: g for g in app.get(f"/api/people/{bob_id}/connections").json}
    assert set(groups) == {link.label for link in connections.PERSON_LINKS}
    assert [i["name"] for i in groups["Trips you took together"]["items"]] == ["Kiev"]
    # a museum is its card, a book its work, a loan itself
    museum = groups["Museums you visited together"]["items"][0]
    assert (museum["name"], museum["view"]) == ("Louvre", "museums")
    assert groups["Books they wrote"]["items"][0]["name"] == "Bob's Book"
    assert groups["Things you lent them"]["items"][0]["view"] == "loans"
    assert app.get(f"/api/people/{loner_id}/connections").json == []
    # another account's person is not there
    app.get("/api/people/999999/connections", status=404)


def test_a_view_shows_only_the_connections_of_its_pages(app: webtest.TestApp, engine: Engine) -> None:
    sign_in(app)
    app.put_json("/api/account/username", {"username": "veltzer"})
    with Session(engine) as session:
        alice = session.scalars(select(User).where(User.email == "alice@example.com")).one()
        bob = Person(owner_id=alice.id, first_name="Bob")
        session.add(bob)
        session.flush()
        _everything_names(session, alice, bob)
        bob_id = bob.id
    app.post_json("/api/shared-views", {"name": "friends", "datasets": ["people", "trips"]}, status=201)
    groups = app.get(f"/api/views/veltzer/friends/data/people/{bob_id}/connections").json
    assert [g["label"] for g in groups] == ["Trips you took together"]
    # a view without people does not show anyone's connections
    app.post_json("/api/shared-views", {"name": "trips", "datasets": ["trips"]}, status=201)
    app.get(f"/api/views/veltzer/trips/data/people/{bob_id}/connections", status=404)
