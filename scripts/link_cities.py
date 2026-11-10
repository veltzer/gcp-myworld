#!/usr/bin/env python

"""
Point every place, museum visit and organization to its city (the cities
table), and every city to its country (the countries table), making both
from the text they had: a place's city and
country, a museum visit's city (its country from the end of its address),
an organization's location, for its headquarters (and its city when it has
none yet: "Santa Clara, California, USA (Nvidia)"; the
text stays, as it says more than the city). A city written two ways is one
city (src/myworld/cities.py). Only rows not linked yet are linked; safe to
run again. Run it after scripts/migrate.sh has added the city links and
before it drops the old city columns.

  scripts/link_cities.py            link them
  scripts/link_cities.py --dry-run  only print what it would do

The database is DATABASE_URL (default: the local sqlite file); for Cloud SQL
run it through the proxy: scripts/with_cloud_db.sh scripts/link_cities.py.
"""

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

# the myworld package is in src/, not installed (see scripts/check.py)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

from sqlalchemy import Connection, inspect, text

from myworld.cities import better, city_key, country_name, parse_location
from myworld.models import make_engine


def columns(connection: Connection, table: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="only print what it would do")
    args = parser.parse_args()
    engine = make_engine()
    print(engine.url.render_as_string(hide_password=True))
    with engine.begin() as connection:
        have_place_text = "city" in columns(connection, "places")
        have_museum_text = "city" in columns(connection, "museum_visits")
        # (table, id, owner, city, region, country) of every row not linked yet that names a city
        wanted: list[tuple[str, int, int, str, str, str]] = []
        # a place with a country but no city keeps its country in its remark: the column goes, nothing is lost
        kept_countries = 0
        if have_place_text:
            for row_id, owner, city, country, remark in connection.execute(text("SELECT id, owner_id, city, country, remark FROM places WHERE city_id IS NULL")):
                if city.strip():
                    wanted.append(("places", row_id, owner, city.strip(), "", country_name(country)))
                elif country.strip():
                    note = f"In {country_name(country)}; the city is not known."
                    if note not in remark:
                        kept_countries += 1
                        print(f"remark   place {row_id}: {note}")
                        if not args.dry_run:
                            connection.execute(text("UPDATE places SET remark = :remark WHERE id = :id"), {"remark": f"{remark} {note}".strip(), "id": row_id})
        if have_museum_text:
            for row_id, owner, city, address in connection.execute(text("SELECT id, owner_id, city, address FROM museum_visits WHERE city_id IS NULL")):
                if city.strip():
                    country = country_name(address.split(",")[-1]) if address.strip() else ""
                    wanted.append(("museum_visits", row_id, owner, city.strip(), "", country))
        for row_id, owner, location in connection.execute(text("SELECT id, owner_id, location FROM organizations WHERE city_id IS NULL")):
            found = parse_location(location)
            if found is not None:
                wanted.append(("organizations", row_id, owner, *found))
        # an organization's headquarters, from its location ("Santa Clara, California, USA (Nvidia)")
        if "headquarters_id" in columns(connection, "organizations"):
            for row_id, owner, location in connection.execute(text("SELECT id, owner_id, location FROM organizations WHERE headquarters_id IS NULL")):
                found = parse_location(location)
                if found is not None:
                    wanted.append(("organizations.headquarters_id", row_id, owner, *found))
        # the countries: those already there, then one per (owner, name) a city wanted is in
        countries: dict[tuple[int, str], int | None] = {}
        country_names: dict[int, str] = {}
        for country_id, owner, name in connection.execute(text("SELECT id, owner_id, name FROM countries")):
            countries[(owner, name.casefold())] = country_id
            country_names[country_id] = name
        made_countries = 0
        for _, _, owner, _, _, country in wanted:
            if country and (owner, country.casefold()) not in countries:
                made_countries += 1
                print(f"country  {country}")
                countries[(owner, country.casefold())] = None if args.dry_run else connection.execute(
                    text("INSERT INTO countries (owner_id, name, remark) VALUES (:owner, :name, '') RETURNING id"), {"owner": owner, "name": country},
                ).scalar_one()
        # the cities: those already there, then one per (owner, name, country) wanted, under its best spelling
        cities: dict[tuple[int, str, str], dict[str, object]] = {}
        for city_id, owner, name, region, country_id in connection.execute(text("SELECT id, owner_id, name, region, country_id FROM cities")):
            country = country_names.get(country_id, "") if country_id is not None else ""
            cities[(owner, *city_key(name, country))] = {"id": city_id, "name": name, "region": region, "country": country}
        for _, _, owner, name, region, country in wanted:
            key = (owner, *city_key(name, country))
            city = cities.setdefault(key, {"id": None, "name": name, "region": region, "country": country})
            if city["id"] is None:
                city["name"] = better(str(city["name"]), name)
            city["region"] = city["region"] or region
        made = 0
        for (owner, _, _), city in cities.items():
            if city["id"] is None:
                made += 1
                print(f"city     {city['name']}{', ' + str(city['region']) if city['region'] else ''}, {city['country'] or '(no country)'}")
                if not args.dry_run:
                    country_id = countries.get((owner, str(city["country"]).casefold())) if city["country"] else None
                    city["id"] = connection.execute(
                        text("INSERT INTO cities (owner_id, name, region, country_id, remark) VALUES (:owner, :name, :region, :country, '') RETURNING id"),
                        {"owner": owner, "name": city["name"], "region": city["region"], "country": country_id},
                    ).scalar_one()
        linked: Counter[str] = Counter()
        for target, row_id, owner, name, _, country in wanted:
            city = cities[(owner, *city_key(name, country))]
            linked[target] += 1
            table, _, column = target.partition(".")
            if not args.dry_run:
                connection.execute(text(f"UPDATE {table} SET {column or 'city_id'} = :city WHERE id = :id"), {"city": city["id"], "id": row_id})
        print(f"{made_countries} countries and {made} cities made; {kept_countries} countries kept in a place's remark; linked {linked['places']} places, {linked['museum_visits']} museum visits, {linked['organizations']} organizations, "
              f"{linked['organizations.headquarters_id']} organizations' headquarters"
              + (" (dry run: nothing changed)" if args.dry_run else ""))
        if args.dry_run:
            connection.rollback()
    return 0


if __name__ == "__main__":
    sys.exit(main())
