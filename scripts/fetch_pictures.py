#!/usr/bin/env python

"""
Give every city a photo and every country its flag, 800 pixels wide, with
the credit its license asks for (the file's page on Wikimedia Commons, its
license and its author). The picture is the one Wikidata keeps for the
city's or country's English Wikipedia article: a city's image (P18), else
the article's lead image when it is a photo (not a map drawing); a
country's flag (P41).

  scripts/fetch_pictures.py            fetch and save them
  scripts/fetch_pictures.py --dry-run  only print what it would take
  scripts/fetch_pictures.py --all      replace the pictures there are too

A city's article is looked up as "City, Region" (US cities: "Austin,
Texas"), then "City, Country", then "City", and taken only when its text
names the country, so "Arad" in Israel is not Arad in Romania. A row with
no article found keeps no picture; each line says what was taken.

The database is DATABASE_URL (default: the local sqlite file); for Cloud SQL
run it through the proxy: scripts/with_cloud_db.sh scripts/fetch_pictures.py.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# the myworld package is in src/, not installed (see scripts/check.py)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from myworld.models import City, Country, Image, make_engine

USER_AGENT = "myworld-pictures/1.0 (+https://github.com/veltzer/gcp-myworld)"
SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
WIKIDATA = "https://www.wikidata.org/wiki/Special:EntityData/"
API = "https://en.wikipedia.org/w/api.php"
WIDTH = 800
PAUSE = 0.3
# how a country is named in articles, when it differs from its name here
SHORT = {"United States of America": "United States"}
# other words an article may place a city in its country by ("a town in England")
ALIASES = {"United Kingdom": ["England", "Scotland", "Wales", "UK"], "United States of America": ["U.S."]}
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}


def get(url: str) -> bytes:
    time.sleep(PAUSE)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def summary(title: str) -> dict[str, Any] | None:
    try:
        return json.loads(get(SUMMARY + urllib.parse.quote(title.replace(" ", "_"))))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def file_name(image_url: str) -> str:
    """
    The Commons file of an image URL: ".../commons/a/ab/Tel_Aviv.jpg" is
    "Tel_Aviv.jpg", and so is a thumbnail of it,
    ".../commons/thumb/a/ab/Tel_Aviv.jpg/3840px-Tel_Aviv.jpg".
    """
    parts = image_url.split("/")
    return urllib.parse.unquote(parts[-2] if "thumb" in parts else parts[-1])


def plain(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", "", html).split())


def file_info(name: str) -> dict[str, str] | None:
    """ The file's thumbnail URL (WIDTH wide), its page, license and author. """
    query = urllib.parse.urlencode({
        "action": "query", "titles": f"File:{name}", "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": WIDTH, "format": "json",
    })
    pages = json.loads(get(f"{API}?{query}"))["query"]["pages"]
    info = next(iter(pages.values())).get("imageinfo")
    if not info:
        return None
    meta = info[0].get("extmetadata", {})
    return {
        "thumb": info[0].get("thumburl") or info[0]["url"],
        "page": info[0]["descriptionurl"],
        "license": plain(meta.get("LicenseShortName", {}).get("value", "")),
        "author": plain(meta.get("Artist", {}).get("value", ""))[:300],
    }


def wikidata_file(item: str, prop: str) -> str | None:
    """ The Commons file of a Wikidata item's property (P18 image, P41 flag), or None. """
    entity = json.loads(get(f"{WIKIDATA}{item}.json"))["entities"][item]
    claims = entity.get("claims", {}).get(prop, [])
    for claim in claims:
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, str):
            return value
    return None


def picture(found: dict[str, Any], is_country: bool) -> str | None:
    """ The Commons file to show for an article: a country's flag, a city's image, else its lead photo (not a drawing). """
    item = found.get("wikibase_item")
    chosen = wikidata_file(item, "P41" if is_country else "P18") if item else None
    if chosen is None and not is_country and "originalimage" in found:
        lead = file_name(found["originalimage"]["source"])
        chosen = None if lead.lower().endswith(".svg") else lead
    return chosen


def article(titles: list[str], country: str, region: str = "") -> dict[str, Any] | None:
    """
    The first of titles that is an article whose text names country, a
    word for it ("England") or the region ("New Jersey"); any article when
    country is empty.
    """
    words = [SHORT.get(country, country), *ALIASES.get(country, []), *([region] if region else [])]
    for title in dict.fromkeys(titles):
        found = summary(title)
        if found is None or found.get("type") != "standard":
            continue
        text = found.get("extract", "") + " " + found.get("description", "")
        if country and not any(word in text for word in words):
            continue
        return found
    return None


def city_titles(city: City) -> list[str]:
    country = city.country.name if city.country else ""
    titles = [f"{city.name}, {city.region}"] if city.region else []
    return [*titles, *([f"{city.name}, {SHORT.get(country, country)}"] if country else []), city.name]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1] if __doc__ else None)
    parser.add_argument("--dry-run", action="store_true", help="only print what it would take")
    parser.add_argument("--all", action="store_true", help="replace the pictures there are too")
    args = parser.parse_args()
    engine = make_engine()
    print(engine.url.render_as_string(hide_password=True))
    missed = 0
    with Session(engine) as session:
        rows: list[Country | City] = [
            *session.scalars(select(Country).order_by(Country.id)),
            *session.scalars(select(City).order_by(City.id).options(selectinload(City.country))),
        ]
        for row in rows:
            if row.image_id is not None and not args.all:
                continue
            what = f"{type(row).__name__.lower()} {row.id}, {row.name}"
            if isinstance(row, City):
                found = article(city_titles(row), row.country.name if row.country else "", row.region)
            else:
                found = article([row.name], "")
            chosen = picture(found, isinstance(row, Country)) if found else None
            info = file_info(chosen) if chosen else None
            if found is None or info is None:
                missed += 1
                print(f"MISS  {what}: {'no article' if found is None else 'no picture for ' + found['title']}")
                continue
            print(f"ok    {what}: {found['title']} -> {chosen} ({info['license'] or 'no license given'}; {info['author'][:60]})")
            if args.dry_run:
                continue
            data = get(info["thumb"])
            content_type = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg" if data[:3] == b"\xff\xd8\xff" else ""
            if content_type not in EXTENSIONS:
                missed += 1
                print(f"MISS  {what}: {info['thumb']} is not a JPEG or PNG")
                continue
            sha256 = hashlib.sha256(data).hexdigest()
            filename = f"{type(row).__name__.lower()}-{row.id}-{sha256[:16]}.{EXTENSIONS[content_type]}"
            image = session.scalars(select(Image).where(Image.owner_id == row.owner_id, Image.filename == filename)).first()
            if image is None:
                image = Image(owner_id=row.owner_id, filename=filename, content_type=content_type, sha256=sha256, data=data)
                session.add(image)
                session.flush()
            row.image_id = image.id
            row.image_source, row.image_license, row.image_author = info["page"], info["license"], info["author"]
            session.commit()
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
