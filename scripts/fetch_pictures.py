#!/usr/bin/env python

"""
Give every city, group, device and profession a photo and every country its flag, 800
pixels wide, with the credit its license asks for (the file's page on
Wikimedia Commons, its license and its author). The picture is the one Wikidata keeps for the
city's or country's English Wikipedia article: a city's image (P18), else
the article's lead image when it is a photo (not a map drawing); a
country's flag (P41).

  scripts/fetch_pictures.py            fetch and save them
  scripts/fetch_pictures.py --dry-run  only print what it would take
  scripts/fetch_pictures.py --all      replace the pictures there are too
  scripts/fetch_pictures.py --only groups
  scripts/fetch_pictures.py --only devices
  scripts/fetch_pictures.py --only professions
  scripts/fetch_pictures.py --only people
  scripts/fetch_pictures.py --title "group:The Blues Messengers=he:שליחי הבלוז"

A group's picture is its own article's (Wikidata's image of it, else its
lead photo), the article taken only when it is about music; else a photo
of its leader (the member a "... Trio" is named after), then of another
member, credited with whose photo it is. --title points a group or a
person at an article by name, in any language ("he:" for Hebrew), where
their English name finds none.

A device's picture ("Samsung S10", "Sansa Clip 2") is that of the first
article about a device that its name is, or that Wikipedia's search finds
for it ("Samsung Galaxy S10"); --title "device:Webos TV=en:LG Smart TV"
points it at another. --file "device:Sansa Clip 2=Sansa clip plus 8gb black.jpg"
takes a Commons file itself, for a device (or anything) no article shows.

A profession's picture ("Performer", "Book Author") is that of the article
about the occupation its name is, else its last word is ("Author"), else
Wikipedia's search finds; --title "profession:Lecturer=en:Lecture" and
--file "profession:Lecturer=..." point it elsewhere.

A person's photo is taken only for someone with a profession (a performer,
a book author, a lecturer: people one may find in an encyclopedia; a friend
or a relative has none and is never looked up), from the article whose title
is their name, in English and then in Hebrew by their Hebrew name, and only
when that article is about a human being and says they do that kind of work,
so a namesake is not taken for them. It becomes their first photo, the
default one; --title "person:Shalom Hanoch=he:שלום חנוך" points one elsewhere.

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

from myworld.models import (
    City,
    Country,
    Device,
    Group,
    Image,
    Person,
    PersonPhoto,
    PersonType,
    make_engine,
)

USER_AGENT = "myworld-pictures/1.0 (+https://github.com/veltzer/gcp-myworld)"
SUMMARY = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/"
WIKIDATA = "https://www.wikidata.org/wiki/Special:EntityData/"
API = "https://{lang}.wikipedia.org/w/api.php"
# what an article about a band or a musician says it is about
MUSIC = re.compile(
    r"\b(band|musician|jazz|singer|guitarist|drummer|saxophonist|bassist|double-bassist|pianist|trumpeter|composer|rock|ensemble|percussionist|music)\b"
    r"|להקת|זמר|מתופף|נגן|מוזיק",
    re.IGNORECASE,
)
# what an article about someone who performs, writes or lectures says they are
PUBLIC = re.compile(
    MUSIC.pattern + r"|\b(actor|actress|comedian|dancer|conductor|performer|entertainer|writer|author|novelist|poet|playwright|journalist|essayist"
    r"|scientist|physicist|mathematician|philosopher|biologist|psychologist|economist|historian|professor|lecturer|scholar|academic|musicologist"
    r"|programmer|engineer|chess|cartoonist|critic|educator)\b|סופר|משורר|שחקן|פרופסור|מדען|עיתונאי|פסנתרן|גיטריסט|יוצר|קומיקאי|רקדן|מלחין|מרצה|חוקר",
    re.IGNORECASE,
)
# what an article about a device says it is ("a smartphone", "a desktop computer")
DEVICE = re.compile(
    r"\b(smartphones?|phones?|computers?|laptops?|tablets?|media players?|mp3 players?|televisions?|tv|devices?|operating system|hardware|console)\b",
    re.IGNORECASE,
)
# the short description of an article about a role a person has: "Person who writes computer software",
# "Officer in charge of technical operations", "An occupation"
ROLE = re.compile(r"^(an? )?(person|people|someone|one|individual|professional|practitioner|worker|officer)\b|\b(officer|occupation|profession|job)$", re.IGNORECASE)
# the words a group named after its leader ends with: "Mads Vinding Trio"
ENSEMBLE = re.compile(r"\s+(trio|quartet|quintet|sextet|band|orchestra|ensemble|group)$", re.IGNORECASE)
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


def summary(title: str, lang: str = "en") -> dict[str, Any] | None:
    try:
        found: dict[str, Any] = json.loads(get(SUMMARY.format(lang=lang) + urllib.parse.quote(title.replace(" ", "_"))))
        found["lang"] = lang
        return found
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
    # the path only: the URL may carry a query ("?utm_source=...")
    parts = urllib.parse.urlparse(image_url).path.split("/")
    return urllib.parse.unquote(parts[-2] if "thumb" in parts else parts[-1])


def plain(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", "", html).split())


def file_info(name: str, lang: str = "en") -> dict[str, str] | None:
    """ The file's thumbnail URL (WIDTH wide), its page, license and author. """
    query = urllib.parse.urlencode({
        "action": "query", "titles": f"File:{name}", "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": WIDTH, "format": "json",
    })
    pages = json.loads(get(f"{API.format(lang=lang)}?{query}"))["query"]["pages"]
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


# a file Wikipedia may show but nobody may reuse
NON_FREE = re.compile(r"fair use|non-free", re.IGNORECASE)


def free(found: dict[str, Any] | None, chosen: str | None) -> bool:
    """ Whether the file is there and free to reuse (not a fair-use file of one Wikipedia). """
    if found is None or chosen is None:
        return False
    info = file_info(chosen, found.get("lang", "en"))
    return info is not None and not NON_FREE.search(info["license"])


def musical(title: str, lang: str = "en") -> dict[str, Any] | None:
    """ The article of that title when it is about music (a band, a musician), else None. """
    found = summary(title, lang)
    if found is None or found.get("type") != "standard":
        return None
    return found if MUSIC.search(found.get("description", "") + " " + found.get("extract", "")[:300]) else None


def named(overrides: dict[str, tuple[str, str]], kind: str, name: str) -> dict[str, Any] | None:
    """ The article --title points kind:name at, if any. """
    if f"{kind}:{name}" not in overrides:
        return None
    lang, title = overrides[f"{kind}:{name}"]
    return summary(title, lang)


def group_picture(group: Group, overrides: dict[str, tuple[str, str]]) -> tuple[dict[str, Any], str, str] | None:
    """
    (article, file, whose photo when not the group's) for a group: its own
    article's picture, else its leader's, else another member's.
    """
    own = named(overrides, "group", group.name) or musical(group.name) or musical(f"{group.name} (band)")
    chosen = picture(own, False) if own else None
    if own and chosen and free(own, chosen):
        return own, chosen, ""
    leader = ENSEMBLE.sub("", group.name)
    members = sorted(group.members, key=lambda p: p.name != leader)
    for member in members:
        found = named(overrides, "person", member.name) or musical(member.name)
        chosen = picture(found, False) if found else None
        if found and chosen and free(found, chosen):
            return found, chosen, member.name
    return None


def search(query: str, lang: str = "en", limit: int = 5) -> list[str]:
    """ The titles Wikipedia's search finds for query, best first. """
    params = urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": query, "srlimit": limit, "format": "json"})
    return [hit["title"] for hit in json.loads(get(f"{API.format(lang=lang)}?{params}"))["query"]["search"]]


def device_picture(device: Device, overrides: dict[str, tuple[str, str]]) -> tuple[dict[str, Any], str] | None:
    """ (article, file) for a device: --title's article, else the first about a device its name is or search finds, with a free photo. """
    pointed = named(overrides, "device", device.name)
    if pointed is not None:
        chosen = picture(pointed, False)
        return (pointed, chosen) if chosen and free(pointed, chosen) else None
    for title in dict.fromkeys([device.name, *search(device.name)]):
        found = summary(title)
        if found is None or found.get("type") != "standard":
            continue
        if not DEVICE.search(found.get("description", "") + " " + found.get("extract", "")[:300]):
            continue
        chosen = picture(found, False)
        if chosen and free(found, chosen):
            return found, chosen
    return None


def profession_picture(kind: PersonType, overrides: dict[str, tuple[str, str]]) -> tuple[dict[str, Any], str] | None:
    """
    (article, file) for a profession: --title's article, else the article its
    name or its last word is ("Author" for "Book Author"), else the first
    about a role a person has that Wikipedia's search finds, with a free photo.
    """
    pointed = named(overrides, "profession", kind.name)
    if pointed is not None:
        chosen = picture(pointed, False)
        return (pointed, chosen) if chosen and free(pointed, chosen) else None
    words = kind.name.split()
    candidates = [(title, False) for title in dict.fromkeys([kind.name, words[-1].capitalize()] if words else [kind.name])]
    candidates += [(title, True) for title in search(kind.name)]
    for title, searched in candidates:
        found = summary(title)
        if found is None or found.get("type") != "standard":
            continue
        if searched and not ROLE.search(found.get("description", "").strip()):
            continue
        chosen = picture(found, False)
        if chosen and free(found, chosen):
            return found, chosen
    return None


def is_human(item: str) -> bool:
    """ Whether a Wikidata item is a human being (instance of Q5), not a band, a character or a list of namesakes. """
    entity = json.loads(get(f"{WIKIDATA}{item}.json"))["entities"][item]
    kinds = [claim.get("mainsnak", {}).get("datavalue", {}).get("value", {}) for claim in entity.get("claims", {}).get("P31", [])]
    return any(isinstance(kind, dict) and kind.get("id") == "Q5" for kind in kinds)


def person_picture(person: Person, overrides: dict[str, tuple[str, str]]) -> tuple[dict[str, Any], str] | None:
    """
    (article, file) for a person with a profession: --title's article, else
    the article their name is the title of (English, then Hebrew by their
    Hebrew name) when it is about a human who performs, writes or lectures,
    with a free photo.
    """
    pointed = named(overrides, "person", person.name)
    if pointed is not None:
        chosen = picture(pointed, False)
        return (pointed, chosen) if chosen and free(pointed, chosen) else None
    english = " ".join(part for part in (person.first_name, person.middle_name, person.surname) if part)
    titles = [("en", english), *(("he", other.name) for other in person.names if other.locale == "he")]
    for lang, title in titles:
        if len(title.split()) < 2:
            # one word names too many people
            continue
        found = summary(title, lang)
        if found is None or found.get("type") != "standard" or not found.get("wikibase_item"):
            continue
        if not PUBLIC.search(found.get("description", "") + " " + found.get("extract", "")[:400]) or not is_human(found["wikibase_item"]):
            continue
        chosen = picture(found, False)
        if chosen and free(found, chosen):
            return found, chosen
    return None


def kind_of(row: Country | City | Group | Device | PersonType | Person) -> str:
    """ What --title and --file call a row's kind: "city", "device", "profession". """
    return "profession" if isinstance(row, PersonType) else type(row).__name__.lower()


def city_titles(city: City) -> list[str]:
    country = city.country.name if city.country else ""
    titles = [f"{city.name}, {city.region}"] if city.region else []
    return [*titles, *([f"{city.name}, {SHORT.get(country, country)}"] if country else []), city.name]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1] if __doc__ else None)
    parser.add_argument("--dry-run", action="store_true", help="only print what it would take")
    parser.add_argument("--all", action="store_true", help="replace the pictures there are too")
    parser.add_argument("--only", choices=["countries", "cities", "groups", "devices", "professions", "people"], help="only these")
    parser.add_argument("--title", action="append", default=[], metavar="KIND:NAME=LANG:TITLE",
                        help='the article for a group, a person, a device or a profession, e.g. "group:The Witches=he:המכשפות"')
    parser.add_argument("--file", action="append", default=[], metavar="KIND:NAME=FILE",
                        help='the Commons file to take, e.g. "device:Sansa Clip 2=Sansa clip plus 8gb black.jpg"')
    args = parser.parse_args()
    files: dict[str, str] = {}
    for item in args.file:
        who, _, chosen_file = item.partition("=")
        if not (who and chosen_file):
            parser.error(f"--file {item!r}: expected KIND:NAME=FILE")
        files[who] = chosen_file.removeprefix("File:")
    overrides: dict[str, tuple[str, str]] = {}
    for item in args.title:
        who, _, where = item.partition("=")
        lang, _, title = where.partition(":")
        if not (who and lang and title):
            parser.error(f"--title {item!r}: expected KIND:NAME=LANG:TITLE")
        overrides[who] = (lang, title)
    engine = make_engine()
    print(engine.url.render_as_string(hide_password=True))
    missed = 0
    with Session(engine) as session:
        rows: list[Country | City | Group | Device | PersonType | Person] = [
            *(session.scalars(select(Country).order_by(Country.id)) if args.only in (None, "countries") else []),
            *(session.scalars(select(City).order_by(City.id).options(selectinload(City.country))) if args.only in (None, "cities") else []),
            *(session.scalars(select(Group).order_by(Group.id).options(selectinload(Group.members))) if args.only in (None, "groups") else []),
            *(session.scalars(select(Device).order_by(Device.id)) if args.only in (None, "devices") else []),
            *(session.scalars(select(PersonType).order_by(PersonType.id)) if args.only in (None, "professions") else []),
            # only those with a profession: a friend or a relative is not looked up
            *(session.scalars(select(Person).where(Person.types.any()).order_by(Person.id).options(selectinload(Person.names))) if args.only in (None, "people") else []),
        ]
        for row in rows:
            if (bool(row.photos) if isinstance(row, Person) else row.image_id is not None) and not args.all:
                continue
            what = f"{kind_of(row)} {row.id}, {row.name}"
            whose = ""
            if f"{kind_of(row)}:{row.name}" in files:
                chosen = files[f"{kind_of(row)}:{row.name}"]
                found = {"title": f"File:{chosen}", "lang": "en"}
            elif isinstance(row, Group):
                picked = group_picture(row, overrides)
                found, chosen, whose = picked if picked else (None, None, "")
            elif isinstance(row, Device):
                found, chosen = device_picture(row, overrides) or (None, None)
            elif isinstance(row, PersonType):
                found, chosen = profession_picture(row, overrides) or (None, None)
            elif isinstance(row, Person):
                found, chosen = person_picture(row, overrides) or (None, None)
            else:
                found = article(city_titles(row), row.country.name if row.country else "", row.region) if isinstance(row, City) else article([row.name], "")
                chosen = picture(found, isinstance(row, Country)) if found else None
            info = file_info(chosen, found.get("lang", "en")) if found and chosen else None
            if info is not None and NON_FREE.search(info["license"]):
                info = None
            if found is None or info is None:
                missed += 1
                print(f"MISS  {what}: {'no article' if found is None else 'no picture for ' + found['title']}")
                continue
            print(f"ok    {what}: {found['title']}{' (a member)' if whose else ''} -> {chosen} ({info['license'] or 'no license given'}; {info['author'][:60]})")
            if args.dry_run:
                continue
            data = get(info["thumb"])
            content_type = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg" if data[:3] == b"\xff\xd8\xff" else ""
            if content_type not in EXTENSIONS:
                missed += 1
                print(f"MISS  {what}: {info['thumb']} is not a JPEG or PNG")
                continue
            sha256 = hashlib.sha256(data).hexdigest()
            filename = f"{kind_of(row)}-{row.id}-{sha256[:16]}.{EXTENSIONS[content_type]}"
            image = session.scalars(select(Image).where(Image.owner_id == row.owner_id, Image.filename == filename)).first()
            if image is None:
                image = Image(owner_id=row.owner_id, filename=filename, content_type=content_type, sha256=sha256, data=data)
                session.add(image)
                session.flush()
            if isinstance(row, Person):
                # their first photo, the default one: those they had follow it
                rest = [photo for photo in row.photos if photo.image_id != image.id]
                first = PersonPhoto(image_id=image.id, image_source=info["page"], image_license=info["license"], image_author=info["author"][:300])
                row.photos = [first, *rest]
                for position, photo in enumerate(row.photos):
                    photo.position = position
                session.commit()
                continue
            row.image_id = image.id
            # a member's photo says whose it is, so the card does not pass it off as the group's
            author = f"{whose} (photo by {info['author'] or 'unknown'})" if whose else info["author"]
            row.image_source, row.image_license, row.image_author = info["page"], info["license"], author[:300]
            session.commit()
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
