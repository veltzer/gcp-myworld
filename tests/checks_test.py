"""
The database checks: the logo rules themselves, the registry, the admin
API that runs them and scripts/check.py, which runs the same ones.
"""

import datetime
import os
import subprocess
import sys
from pathlib import Path

import pytest
import webtest
from sqlalchemy import create_engine, delete, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from myworld import checks
from myworld.checks import logo_problems
from myworld.models import (
    ROLE_ADMIN,
    Base,
    Image,
    Museum,
    Organization,
    Person,
    PersonType,
    RelationType,
    User,
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
    assert {"logos", "organization-logos", "organization-relations", "organization-addresses", "person-types", "museum-dates", "organization-locations", "museum-addresses", "museum-locations", "museum-company"} <= set(checks.CHECKS)
    for chosen in checks.CHECKS.values():
        assert chosen.title and chosen.description and chosen.noun


def test_a_name_is_registered_once() -> None:
    with pytest.raises(ValueError, match="twice"):
        checks.check("logos", "again", "logos")(lambda session: checks.Result(0, []))


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
    assert [c["name"] for c in listed] == list(checks.CHECKS)
    result = app.get("/api/checks/logos").json
    assert (result["ok"], result["checked"], len(result["problems"])) == (False, 2, 1)
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
        result = checks.CHECKS["person-types"].run(session)
    assert result.checked == 3
    assert [(p.subject, p.message) for p in result.problems] == [
        ("Eli (person 2, account 1)", "has no type"),
        ("the guide at the Louvre (person 3, account 2)", "has no type"),
    ]
    assert [(p.link, p.owner) for p in result.problems] == [("people/2", 1), ("people/3", 2)]


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
    assert listed.returncode == 0 and "logos" in listed.stdout
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
