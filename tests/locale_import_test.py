"""
The Locale importer: the countries, currencies, languages and cities of the
world into the shared data, by admins only, run again and again without
adding anything twice, and never changing the id or the name of a row that
was there (whatever points at it stays).
"""

import io
import zipfile
from typing import Any

import pytest
import webtest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from myworld.importers import core, jobs
from myworld.importers import locale as locale_importer
from myworld.models import City, Country, Currency, Locale, Region
from tests.conftest import sign_in, sign_in_admin

# GeoNames' first-level divisions, and its cities: id, name, ascii name, other names, latitude, longitude,
# feature class and code, country, cc2, region, admin2-4, population, elevation, dem, timezone, modified
REGIONS = "IL.05\tTel Aviv\tTel Aviv\t293396\nUS.CA\tCalifornia\tCalifornia\t5332921\nUS.MA\tMassachusetts\tMassachusetts\t6254926\nUA.12\tKyiv City\tKyiv City\t703447\n"
CITIES = [
    (293397, "Tel Aviv", "Tel Aviv", "Tel Aviv-Yafo,Tel-Aviv", 32.08, 34.78, "PPLA", "IL", "05", 432892),
    (281184, "Jerusalem", "Jerusalem", "Yerushalayim", 31.77, 35.21, "PPLC", "IL", "06", 801000),
    (703448, "Kyiv", "Kyiv", "Kiev,Kiew", 50.45, 30.52, "PPLC", "UA", "12", 2952301),
    (5339111, "Concord", "Concord", "", 37.97, -122.03, "PPL", "US", "CA", 125410),
    (4933743, "Concord", "Concord", "", 42.46, -71.35, "PPL", "US", "MA", 16810),
    (9999999, "Atlantis", "Atlantis", "", 0.0, 0.0, "PPL", "ZZ", "01", 500000),
]


def _cities_zip() -> bytes:
    lines = [
        "\t".join(map(str, [gid, name, ascii_name, others, lat, lon, "P", code, country, "", region, "", "", "", population, "", "", "UTC", "2024-01-01"]))
        for gid, name, ascii_name, others, lat, lon, code, country, region, population in CITIES
    ]
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("cities15000.txt", "\n".join(lines) + "\n")
    return out.getvalue()


@pytest.fixture(autouse=True)
def fixture_geonames(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """ GeoNames' files, from here; and a run's job done right away, inside the request that starts it. """
    fetched: list[str] = []

    def fetch(name: str) -> bytes:
        fetched.append(name)
        return _cities_zip() if name == "cities15000.zip" else REGIONS.encode()

    def dispatcher(engine: Engine) -> Any:
        def dispatch(run_id: int) -> str:
            core.execute(engine, run_id)
            return ""
        return dispatch

    monkeypatch.setattr(locale_importer, "fetch", fetch)
    monkeypatch.setattr(jobs, "dispatcher", dispatcher)
    return fetched


EVERYTHING = {"what": ["currencies", "languages", "countries", "cities"], "cities_over": ["100000"]}


def _snapshot(engine: Engine) -> dict[str, Any]:
    """ Every row the importer writes, as it is: a second run must leave it so. """
    with Session(engine) as session:
        return {
            "countries": sorted((c.id, c.name, c.code, c.code3, c.latitude, c.longitude, tuple(x.code for x in c.currencies), tuple(x.code for x in c.languages)) for c in session.scalars(select(Country))),
            "currencies": sorted((c.id, c.code, c.name, c.symbol, c.digits) for c in session.scalars(select(Currency))),
            "locales": sorted((x.code, x.name, x.script, x.position, x.native) for x in session.scalars(select(Locale))),
            "regions": sorted((r.id, r.name, r.code, r.country_id) for r in session.scalars(select(Region))),
            "cities": sorted((c.id, c.name, c.region_id, c.country_id, c.geonames_id, c.population, c.latitude, c.longitude) for c in session.scalars(select(City))),
        }


def _existing(app: webtest.TestApp) -> dict[str, int]:
    """ What an admin added by hand before any import: countries by their own names, cities the way they wrote them. """
    usa = app.post_json("/api/countries", {"name": "United States of America"}, status=201).json["id"]
    israel = app.post_json("/api/countries", {"name": "Israel"}, status=201).json["id"]
    ukraine = app.post_json("/api/countries", {"name": "Ukraine"}, status=201).json["id"]
    return {
        "usa": usa, "israel": israel, "ukraine": ukraine,
        "kiev": app.post_json("/api/cities", {"name": "Kiev", "country_id": ukraine}, status=201).json["id"],
        "tel-aviv": app.post_json("/api/cities", {"name": "Tel Aviv", "region": "Tel Aviv District", "country_id": israel}, status=201).json["id"],
        "concord": app.post_json("/api/cities", {"name": "Concord", "region": "Massachusetts", "country_id": usa}, status=201).json["id"],
    }


def _run(app: webtest.TestApp, params: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    run = app.post_json("/api/importers/locale/runs", {"params": params, "dry_run": dry_run}, status=202).json
    return next(r for r in app.get("/api/import-runs").json["ended"] if r["id"] == run["id"])


def test_only_an_admin_sees_and_runs_an_importer_of_shared_data(app: webtest.TestApp, engine: Engine) -> None:
    sign_in(app)
    assert "locale" not in [i["name"] for i in app.get("/api/importers").json["importers"]]
    app.post_json("/api/importers/locale/runs", {"params": EVERYTHING}, status=404)
    sign_in_admin(app, engine, sub="the-admin")
    [importer] = [i for i in app.get("/api/importers").json["importers"] if i["name"] == "locale"]
    assert importer["shared"] is True
    assert importer["for_admins"] is True
    assert [p["single"] for p in importer["params"]] == [False, True]


def test_it_brings_the_world_and_keeps_the_ids_and_names_there_were(app: webtest.TestApp, engine: Engine) -> None:
    sign_in_admin(app, engine)
    before = _existing(app)
    run = _run(app, EVERYTHING)
    assert run["status"] == "done", run["log"]
    with Session(engine) as session:
        usa = session.get(Country, before["usa"])
        assert usa is not None
        # known again by its name, and given its code: its name stays the admin's
        assert (usa.name, usa.code, usa.code3) == ("United States of America", "US", "USA")
        assert "USD" in [c.code for c in usa.currencies]
        israel = session.scalars(select(Country).where(Country.code == "IL")).one()
        assert israel.id == before["israel"]
        assert [c.code for c in israel.currencies] == ["ILS"]
        assert {"he", "ar"} <= {x.code for x in israel.languages}
        # put on the map where its capital is
        assert (israel.latitude, israel.longitude) == (31.77, 35.21)
        # every country of the world is there, each once
        assert session.scalars(select(Country).where(Country.code == "FR")).one().name == "France"
        # Kiev is GeoNames' Kyiv (by its other names): the same row, with its name, its id and now its region
        kiev = session.get(City, before["kiev"])
        assert kiev is not None
        assert (kiev.name, kiev.geonames_id, kiev.population, kiev.region) == ("Kiev", 703448, 2952301, "Kyiv City")
        tel_aviv = session.get(City, before["tel-aviv"])
        assert tel_aviv is not None
        assert (tel_aviv.geonames_id, tel_aviv.region) == (293397, "Tel Aviv District")
        # Concord, California is not Concord, Massachusetts (another region), and the latter is too small to be brought
        concord = session.get(City, before["concord"])
        assert concord is not None
        assert concord.geonames_id is None
        california = session.scalars(select(City).where(City.geonames_id == 5339111)).one()
        assert (california.name, california.region, california.population) == ("Concord", "California", 125410)
        # Jerusalem is new (in no region: GeoNames names none for it here); a city of no country there is is not brought
        assert session.scalars(select(City).where(City.geonames_id == 281184)).one().region == ""
        assert session.scalars(select(City).where(City.geonames_id == 9999999)).first() is None
        assert session.scalars(select(Currency).where(Currency.code == "ILS")).one().symbol == "₪"
        assert session.get(Locale, "ja") is not None


def test_a_second_run_adds_nothing_and_changes_nothing(app: webtest.TestApp, engine: Engine) -> None:
    sign_in_admin(app, engine)
    _existing(app)
    assert _run(app, EVERYTHING)["status"] == "done"
    first = _snapshot(engine)
    again = _run(app, EVERYTHING)
    assert again["status"] == "done", again["log"]
    assert _snapshot(engine) == first
    assert not any(what.endswith(("added", "matched", "filled in", "put on the map")) for what in again["counts"]), again["counts"]


def test_a_dry_run_keeps_nothing(app: webtest.TestApp, engine: Engine) -> None:
    sign_in_admin(app, engine)
    before = _snapshot(engine)
    run = _run(app, EVERYTHING, dry_run=True)
    assert run["status"] == "done"
    assert run["counts"]["countries added"] > 200
    assert _snapshot(engine) == before


def test_cities_need_a_size(app: webtest.TestApp, engine: Engine) -> None:
    sign_in_admin(app, engine)
    run = _run(app, {"what": ["cities"], "cities_over": []})
    assert run["status"] == "failed"
    assert "Cities over: choose how big a city must be" in run["log"]
    app.post_json("/api/importers/locale/runs", {"params": {"what": ["cities"], "cities_over": ["100000", "15000"]}}, status=400)


def test_an_admin_runs_it_with_the_shared_data_locked(app: webtest.TestApp, engine: Engine, fixture_geonames: list[str]) -> None:
    # the lock is on changing it by hand: an import is asked for on purpose
    sign_in_admin(app, engine, edit_shared=False)
    assert _run(app, {"what": ["countries"], "cities_over": []})["status"] == "done"
    # only what was asked for: countries need no GeoNames download
    assert fixture_geonames == []
    with Session(engine) as session:
        assert session.scalars(select(Currency)).first() is None
        assert session.scalars(select(Country).where(Country.code == "IL")).one().name == "Israel"


@pytest.mark.parametrize(("here", "there", "same"), [
    ("Tel Aviv District", "Tel Aviv", True),
    ("Haifa District", "Haifa", True),
    ("Central District", "Central District", True),
    ("Massachusetts", "California", False),
    ("District", "Region", False),
])
def test_region_like(here: str, there: str, same: bool) -> None:
    assert locale_importer.region_like(here, there) is same
