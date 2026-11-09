#!/usr/bin/env python

"""
Find the latitude and longitude of every museum visit and organization that
has an address, and every place (a concert hall, a club: name, city and
country), that has no coordinates yet, so it shows on the map.

  scripts/geocode.py             look them up and save them
  scripts/geocode.py --dry-run   look them up, print, save nothing
  scripts/geocode.py --all       look up those with coordinates too

The addresses go to OpenStreetMap's Nominatim, one a second as its usage
policy asks. Postcodes, floors and (remarks) are left out of
the query. An address it does not place on a building or a street is
tried as the name in its city ("Westminster Abbey, London"), then
taken on its street, and then without its first parts, down to city and country; each line says which
of these matched, so a place found only by its city is easy to spot and
correct in the dialog. A museum visited twice is looked up once.

A place has no address: it is looked up by its name in its city, then by
the first part of its name ("Logus pub" of "Logus pub, Nahalat Binyamin"),
each only when the match is a building or venue that carries the name; then
by the rest of its name as a street or area in its city ("Nahalat Binyamin,
Tel Aviv"), which places it roughly. A place only its city matches is left
without coordinates rather than put at the city's centre. A place found gets
the match as its address when it has none.

The database is DATABASE_URL (default: the local sqlite file); for Cloud SQL
run it through the proxy: scripts/with_cloud_db.sh scripts/geocode.py.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# the myworld package is in src/, not installed: find it from any directory
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld.models import Museum, Organization, Place, make_engine

NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "myworld-geocode/1.0 (+https://github.com/veltzer/gcp-myworld)"
# Nominatim's usage policy: at most one request a second
PAUSE = 1.1


# a match that is only an area (a city, a district) rather than a building or a street
AREAS = {"boundary", "place"}
# a match on a street, not a number on it
ROADS = {"highway"}
POSTCODE = re.compile(r"\b(\d{5,7}(-\d{4})?|[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2})\b")
# a part of an address that no map knows: a floor, a suite, a building number in a park
UNMAPPED = re.compile(r"^(\d+(st|nd|rd|th) floor|floor \d+|suite \d+|building \d+)$", re.IGNORECASE)


def lookup(query: str) -> dict[str, Any] | None:
    url = f"{NOMINATIM}?{urllib.parse.urlencode({'q': query, 'format': 'jsonv2', 'limit': 1})}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    time.sleep(PAUSE)
    with urllib.request.urlopen(request, timeout=30) as response:
        found = json.load(response)
    return found[0] if found else None


def address_parts(address: str) -> list[str]:
    """ The parts of an address a map can find: no (remarks), postcodes, floors or suites. """
    address = re.sub(r"\([^)]*\)", "", address)
    parts = [" ".join(POSTCODE.sub("", part).split()) for part in address.split(",")]
    return [part for part in parts if part and not UNMAPPED.match(part)]


# words that say what a place is, not which one: "Tel Aviv Museum" is not "Eretz Israel Museum"
GENERIC = {
    "the", "and", "museum", "museums", "gallery", "art", "arts", "national", "university", "school", "center", "centre", "ltd", "inc", "group",
    # what a concert place is, not which one
    "pub", "club", "bar", "cafe", "hall", "big", "small", "lawn", "port", "street", "house", "near",
}


def significant(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", text.lower()) if len(w) > 2 and w not in GENERIC}


def named(found: dict[str, Any], name: str, city: str) -> bool:
    """
    Whether a match is the place itself: the matched object's own name
    (the first part of what was matched) shares a word with the name that
    is neither generic nor the city's ("Tel Aviv Museum" in Tel Aviv
    needs more than "Tel Aviv").
    """
    own = significant(found["display_name"].split(",")[0])
    # a name that is its city and generic words ("Tel Aviv Museum of Art") has only the city's words to match on
    words = significant(name) - significant(city) or significant(name)
    return bool(own & words)


def geocode(name: str, address: str) -> tuple[float, float, str, str] | None:
    """
    (latitude, longitude, how it was found, what it matched), or None. In
    order: the whole address, on a building; the name in the address's city,
    when the match carries the name; the whole address on its street only
    (a long street's middle can be far off); then the address less its
    first parts, down to city and country, which places it only roughly.
    """
    parts = address_parts(address)
    if not parts:
        return None
    full = ", ".join(parts)
    on_street = lookup(full)
    if on_street is not None and on_street["category"] not in AREAS | ROADS:
        return float(on_street["lat"]), float(on_street["lon"]), "address", on_street["display_name"]
    city = ", ".join(parts[-2:])
    found = lookup(f"{name}, {city}")
    if found is not None and found["category"] not in AREAS | ROADS and named(found, name, city):
        return float(found["lat"]), float(found["lon"]), f"name in {city!r}", found["display_name"]
    if on_street is not None and on_street["category"] in ROADS:
        return float(on_street["lat"]), float(on_street["lon"]), "street only", on_street["display_name"]
    for start in range(1, len(parts) - 1):
        query = ", ".join(parts[start:])
        found = lookup(query)
        if found is not None:
            return float(found["lat"]), float(found["lon"]), f"area {query!r}", found["display_name"]
    if on_street is not None:
        return float(on_street["lat"]), float(on_street["lon"]), f"area {full!r}", on_street["display_name"]
    return None


def place_query_city(city: str, country: str) -> str:
    """ The city and country as a map knows them ("Tel-Aviv" is "Tel Aviv"). """
    return ", ".join(part for part in (city.replace("-", " "), country) if part)


# the spellings maps use: "Givatayim Theatre", "Caesarea Amphitheater"
SPELLINGS = [("Theater", "Theatre"), ("theater", "theatre"), ("amphitheatre", "amphitheater"), ("Amphitheatre", "Amphitheater")]


def spellings(name: str) -> list[str]:
    """ name, and name in the other spellings of its words. """
    out = [name]
    for one, other in SPELLINGS:
        for known in list(out):
            for a, b in ((one, other), (other, one)):
                if a in known:
                    out.append(known.replace(a, b))
    return list(dict.fromkeys(out))


def geocode_place(name: str, city: str, country: str) -> tuple[float, float, str, str] | None:
    """
    (latitude, longitude, how it was found, what it matched), or None. In
    order: the name in its city, then the name's first part in its city, each
    only on a building or venue that carries the name; then the rest of the
    name as a street or area in the city, which places it roughly. Never only
    the city.
    """
    if not city.strip():
        # without a city, a name matches wherever in the country it is common: not a place
        return None
    where = place_query_city(city, country)
    parts = [part.strip() for part in name.split(",") if part.strip()]
    for query_name in dict.fromkeys([*spellings(name), *spellings(parts[0])]):
        found = lookup(f"{query_name}, {where}" if where else query_name)
        if found is not None and found["category"] not in AREAS and named(found, query_name, city):
            return float(found["lat"]), float(found["lon"]), f"name {query_name!r} in {where!r}", found["display_name"]
    for part in parts[1:]:
        found = lookup(f"{part}, {where}" if where else part)
        if found is not None and found["category"] in AREAS | ROADS and named(found, part, city):
            return float(found["lat"]), float(found["lon"]), f"roughly, area {part!r} in {where!r}", found["display_name"]
    return None


def geocode_places(session: Session, every: bool) -> int:
    """ Look up the places without coordinates (all of them with every); how many were not found. """
    missed = 0
    for place in session.scalars(select(Place).order_by(Place.id)):
        if place.latitude is not None and not every:
            continue
        what = f"place {place.id}, {place.name}, {place.city}"
        found = geocode_place(place.name, place.city, place.country)
        if found is None:
            missed += 1
            print(f"MISS  {what}: {'no city to look in' if not place.city.strip() else 'nothing that carries its name'}")
            continue
        latitude, longitude, how, match = found
        print(f"ok    {what}: {latitude:.5f},{longitude:.5f} (by {how}) = {match}")
        place.latitude, place.longitude = latitude, longitude
        if not place.address.strip():
            place.address = match
        if how.startswith("roughly"):
            # say so where it is seen: the card's remark
            note = f"Location approximate: {how.removeprefix('roughly, ')}."
            if note not in place.remark:
                place.remark = f"{place.remark} {note}".strip()
    return missed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1] if __doc__ else None)
    parser.add_argument("--dry-run", action="store_true", help="print what is found, save nothing")
    parser.add_argument("--all", action="store_true", help="look up rows that already have coordinates too")
    args = parser.parse_args()
    engine = make_engine()
    print(engine.url.render_as_string(hide_password=True))
    missed = 0
    with Session(engine) as session:
        rows: list[Museum | Organization] = [*session.scalars(select(Museum).order_by(Museum.id)), *session.scalars(select(Organization).order_by(Organization.id))]
        cache: dict[str, tuple[float, float, str, str] | None] = {}
        for row in rows:
            what = f"{type(row).__name__.lower()} {row.id}, {row.name}"
            if not row.address.strip():
                print(f"skip  {what}: no address")
                continue
            if row.latitude is not None and not args.all:
                continue
            key = f"{row.name}|{row.address}"
            if key not in cache:
                cache[key] = geocode(row.name, row.address)
            found = cache[key]
            if found is None:
                missed += 1
                print(f"MISS  {what}: nothing for {row.address!r}")
                continue
            latitude, longitude, how, match = found
            print(f"ok    {what}: {latitude:.5f},{longitude:.5f} (by {how}) = {match}")
            row.latitude, row.longitude = latitude, longitude
        missed += geocode_places(session, args.all)
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
