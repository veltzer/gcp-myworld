#!/usr/bin/env python

"""
Split the one-line addresses of places, museum visits and organizations into
street, neighbourhood and postcode (src/myworld/addresses.py); the city they
point to carries the region and the country.

A museum visit's or an organization's address was typed: it is split, the
parts that are its city or country left out; when it says more than the
three parts hold (a remark in brackets, a county) it is also kept in the
remark ("Address as written: ..."), so nothing is lost. An organization's
city becomes the one its address is in (the office the user knew; its
location keeps where its headquarters are), made with its country when the
user has no such city yet. A place's
address was mostly the map's own (scripts/geocode.py): a place at a known
spot gets the parts the map gives for that spot; one whose location is
approximate gets none, rather than a street that is not its own, and keeps
a short (typed) address in its remark.

  scripts/split_addresses.py            split them
  scripts/split_addresses.py --dry-run  only print what it would do
  scripts/split_addresses.py --drop     split, then drop the address columns

Run it after scripts/migrate.sh has added the parts; --drop once the version
that no longer has the address column is deployed (right after: that
version cannot add a place while places.address is there). Rows that have
parts already are left alone, so it is safe to run again.

The database is DATABASE_URL (default: the local sqlite file); for Cloud SQL
run it through the proxy: scripts/with_cloud_db.sh scripts/split_addresses.py.
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# the myworld package is in src/, not installed (see scripts/check.py)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

from sqlalchemy import Connection, inspect, text

from myworld.addresses import from_osm, parse_address, split_text
from myworld.cities import city_key
from myworld.models import make_engine

REVERSE = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "myworld-geocode/1.0 (+https://github.com/veltzer/gcp-myworld)"
# Nominatim's usage policy: at most one request a second
PAUSE = 1.1
TABLES = ("places", "museum_visits", "organizations")


def reverse(latitude: float, longitude: float) -> dict[str, str]:
    """ OpenStreetMap's address parts at a spot (a building or a street). """
    query = urllib.parse.urlencode({"lat": latitude, "lon": longitude, "format": "jsonv2", "addressdetails": 1, "zoom": 18})
    request = urllib.request.Request(f"{REVERSE}?{query}", headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    time.sleep(PAUSE)
    with urllib.request.urlopen(request, timeout=30) as response:
        found: dict[str, Any] = json.load(response)
    return found.get("address", {})


def columns(connection: Connection, table: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="only print what it would do")
    parser.add_argument("--drop", action="store_true", help="then drop the address columns")
    args = parser.parse_args()
    engine = make_engine()
    print(engine.url.render_as_string(hide_password=True))
    with engine.begin() as connection:
        # every account's cities, to find the one an address is in: (owner, name key, country key) -> id
        cities: dict[tuple[int, str, str], int] = {}
        names: dict[int, set[str]] = {}
        for city_id, owner, name, country in connection.execute(text(
            "SELECT c.id, c.owner_id, c.name, co.name FROM cities c LEFT JOIN countries co ON co.id = c.country_id",
        )):
            cities[(owner, *city_key(name, country or ""))] = city_id
            names.setdefault(owner, set()).add(city_key(name, "")[0])

        def city_of(owner: int, name: str, region: str, country: str) -> int | None:
            """ The account's city of that name in that country (the one of that name, when only one), made when there is none. """
            key = (owner, *city_key(name, country))
            if key in cities:
                return cities[key]
            same = [city_id for (o, n, _), city_id in cities.items() if o == owner and n == key[1]]
            if len(same) == 1:
                return same[0]
            print(f"city     {name}{', ' + region if region else ''}, {country or '(no country)'} (new)")
            if args.dry_run:
                return None
            country_id = None
            if country:
                country_id = connection.execute(text("SELECT id FROM countries WHERE owner_id = :o AND lower(name) = lower(:n)"), {"o": owner, "n": country}).scalar()
                if country_id is None:
                    country_id = connection.execute(text("INSERT INTO countries (owner_id, name, remark) VALUES (:o, :n, '') RETURNING id"), {"o": owner, "n": country}).scalar_one()
            city_id = connection.execute(
                text("INSERT INTO cities (owner_id, name, region, country_id, remark) VALUES (:o, :n, :r, :c, '') RETURNING id"),
                {"o": owner, "n": name, "r": region, "c": country_id},
            ).scalar_one()
            cities[key] = city_id
            names.setdefault(owner, set()).add(key[1])
            return city_id

        for table in TABLES:
            if "address" not in columns(connection, table):
                print(f"{table}: no address column (split already)")
                continue
            rows = connection.execute(text(f"""
                SELECT t.id, t.name, t.address, t.remark, t.latitude, t.longitude, c.name, c.region, co.name, t.owner_id, t.city_id
                FROM {table} t LEFT JOIN cities c ON c.id = t.city_id LEFT JOIN countries co ON co.id = c.country_id
                WHERE t.address <> '' AND t.street = '' AND t.neighbourhood = '' AND t.postcode = '' ORDER BY t.id
            """)).all()
            split = kept = empty = 0
            for row_id, name, address, remark, latitude, longitude, city, region, country, owner, city_id in rows:
                city, region, country = city or "", region or "", country or ""
                whole = True
                if table == "places":
                    if "Location approximate" in remark or latitude is None:
                        empty += 1
                        # the map's own address is long ("Tmuna, 8, Shonzino, Tel Aviv, ..., Israel"); a short one was typed: kept
                        typed = address.count(",") < 4
                        print(f"{'keep' if typed else 'none'}  {table} {row_id}, {name}: located only roughly; no street{'; kept as written' if typed else ''}")
                        if typed and not args.dry_run:
                            connection.execute(text(f"UPDATE {table} SET remark = :remark WHERE id = :id"),
                                               {"remark": f"{remark} Address as written: {address}".strip(), "id": row_id})
                        continue
                    street, neighbourhood, postcode = from_osm(reverse(latitude, longitude), country)
                elif table == "organizations":
                    parsed = parse_address(address, names.get(owner, set()), country)
                    street, neighbourhood, postcode, whole = str(parsed["street"]), str(parsed["neighbourhood"]), str(parsed["postcode"]), bool(parsed["whole"])
                    if parsed["city"]:
                        moved = city_of(owner, str(parsed["city"]), str(parsed["region"]), str(parsed["country"]))
                        if moved != city_id:
                            print(f"city     {table} {row_id}, {name}: {city or '(none)'} -> {parsed['city']}")
                            if moved is not None and not args.dry_run:
                                connection.execute(text(f"UPDATE {table} SET city_id = :c WHERE id = :id"), {"c": moved, "id": row_id})
                else:
                    street, neighbourhood, postcode, whole = split_text(address, city, region, country)
                note = "" if whole else f"Address as written: {address}"
                if not (street or neighbourhood or postcode):
                    empty += 1
                print(f"{'keep' if note else 'ok'}    {table} {row_id}, {name}: {address!r} -> street {street!r}, neighbourhood {neighbourhood!r}, postcode {postcode!r}")
                split += 1
                kept += bool(note)
                if not args.dry_run:
                    connection.execute(
                        text(f"UPDATE {table} SET street = :street, neighbourhood = :neighbourhood, postcode = :postcode, remark = :remark WHERE id = :id"),
                        {"street": street[:300], "neighbourhood": neighbourhood[:200], "postcode": postcode[:20],
                         "remark": f"{remark} {note}".strip() if note else remark, "id": row_id},
                    )
            print(f"{table}: {split} split, {kept} also kept as written in the remark, {empty} with nothing to split into")
        if args.drop and not args.dry_run:
            for table in TABLES:
                if "address" in columns(connection, table):
                    connection.execute(text(f"ALTER TABLE {table} DROP COLUMN address"))
                    print(f"{table}: address column dropped")
        if args.dry_run:
            connection.rollback()
            print("dry run: nothing changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
