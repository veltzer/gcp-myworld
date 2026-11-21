"""
The Locale importer: the countries, currencies, languages and cities of the
world, into the shared data (everyone's: only admins see and run it).

- Currencies: every currency some country pays in today (ISO 4217, by
  pycountry; names, symbols and digits by CLDR, through Babel).
- Languages: every language CLDR has a two-letter code for, with its name in
  English and in itself; its script is the one its own name is written in.
- Countries: every ISO 3166 country, named as CLDR names it in English, with
  its codes, the currencies it pays in and its official languages.
- Cities: every city GeoNames counts at least so many people in (cities15000,
  downloaded as the run goes), with its region (GeoNames' first-level
  division), position and population; a country not on the map yet is put
  where its capital is. Cities need countries: choosing them runs Countries
  too.

It may be run again and again: a row is known again by its code (a
country's ISO code, a currency's, a language's, a region's GeoNames code, a
city's GeoNames id), and a row first met by its name (one there before it)
is given its code then. A row is never deleted or made again, so its id,
and whatever points at it (an account's concerts, organizations, visits),
stays; of a row there already only what is empty is filled (and a city's
population, which is GeoNames' to say), and a name is never changed. So a
second run right after the first adds nothing and changes nothing.
"""

import csv
import io
import unicodedata
import zipfile
from collections.abc import Iterator
from typing import Any

import babel
import babel.languages
import babel.localedata
import babel.numbers
import pycountry
import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from myworld import languages
from myworld.importers.core import Importer, Param, ParamError, Report, register
from myworld.models import City, Country, Currency, Locale, Region, User

# what may be imported, in the order it is done
WHAT = (("currencies", "Currencies"), ("languages", "Languages"), ("countries", "Countries"), ("cities", "Cities"))
# the least population a city brought has (cities15000 has them all down to 15,000)
SIZES = (1_000_000, 500_000, 100_000, 50_000, 15_000)

GEONAMES = "https://download.geonames.org/export/dump/"
CITIES_FILE = "cities15000"
REGIONS_FILE = "admin1CodesASCII.txt"
DOWNLOAD_SECONDS = 120

# names a country may have here that neither ISO nor CLDR give it
COUNTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "US": ("USA", "United States of America", "America"),
    "GB": ("UK", "Great Britain", "Britain"),
    "KR": ("Korea",),
    "CZ": ("Czech Republic",),
    "NL": ("Holland",),
}

# words a region's name may have or not have and still be the same region ("Tel Aviv" and "Tel Aviv District")
REGION_WORDS = frozenset({"district", "region", "province", "state", "county", "oblast", "governorate", "prefecture", "area"})


def key(name: str) -> str:
    """ A name as it is compared: whatever its case, accents, spaces and punctuation ("Ra'anana" is "raanana"). """
    letters = unicodedata.normalize("NFKD", name.casefold())
    return "".join(char for char in letters if char.isalnum())


def _region_words(name: str) -> str:
    return key(" ".join(word for word in name.split() if word.casefold() not in REGION_WORDS))


def region_like(here: str, there: str) -> bool:
    """ Whether two names of a region are the same region ("Haifa District", "Haifa"). """
    return key(here) == key(there) or _region_words(here) == _region_words(there) != ""


def fetch(name: str) -> bytes:
    """ A file of GeoNames' dump. """
    response = requests.get(GEONAMES + name, timeout=DOWNLOAD_SECONDS)
    response.raise_for_status()
    return response.content


def geonames_cities() -> Iterator[list[str]]:
    """ The rows of cities15000: id, name, ascii name, other names, latitude, longitude, ..., country, region, ..., population. """
    with zipfile.ZipFile(io.BytesIO(fetch(f"{CITIES_FILE}.zip"))) as archive:
        text = archive.read(f"{CITIES_FILE}.txt").decode()
    yield from csv.reader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)


def geonames_regions() -> dict[str, str]:
    """ The regions (first-level divisions) by their codes ("IL.05": "Tel Aviv"). """
    rows = csv.reader(io.StringIO(fetch(REGIONS_FILE).decode()), delimiter="\t", quoting=csv.QUOTE_NONE)
    return {row[0]: row[1] for row in rows if len(row) >= 2}


def _tender() -> set[str]:
    """ The currencies some country pays in today. """
    return {code for country in pycountry.countries for code in babel.numbers.get_territory_currencies(country.alpha_2, tender=True)}


def import_currencies(session: Session, report: Report) -> None:
    have = {currency.code: currency for currency in session.scalars(select(Currency))}
    tender = _tender()
    for iso in sorted(pycountry.currencies, key=lambda c: c.alpha_3):
        code = iso.alpha_3
        if code not in tender:
            continue
        name = babel.numbers.get_currency_name(code, locale="en") or iso.name
        symbol = babel.numbers.get_currency_symbol(code, locale="en")
        symbol = "" if symbol == code else symbol
        digits = babel.numbers.get_currency_precision(code)
        currency = have.get(code)
        if currency is None:
            session.add(Currency(code=code, name=name, symbol=symbol, digits=digits))
            report.count("currencies added")
            continue
        filled = False
        if not currency.name:
            currency.name, filled = name, True
        if not currency.symbol and symbol:
            currency.symbol, filled = symbol, True
        if currency.digits is None:
            currency.digits, filled = digits, True
        report.count("currencies filled in" if filled else "currencies already there")


def import_languages(session: Session, report: Report) -> None:
    have = {locale.code: locale for locale in session.scalars(select(Locale))}
    names = {key(locale.name): locale.code for locale in have.values()}
    position = (session.scalar(select(func.max(Locale.position))) or 0) + 1
    found = []
    for code in babel.localedata.locale_identifiers():
        if "_" in code or len(code) != 2:
            continue
        if code in have:
            report.count("languages already there")
            continue
        language = babel.Locale(code)
        name, native = language.get_display_name("en") or "", language.get_display_name(code) or ""
        native = native[:1].upper() + native[1:]
        script = languages.script_of(native)
        if not name or not script:
            report.count("languages skipped")
            continue
        found.append((name, code, native, script))
    for name, code, native, script in sorted(found):
        if key(name) in names:
            report.count("languages skipped")
            report.say(f"Language {code} ({name}): {names[key(name)]} is called so already")
            continue
        session.add(Locale(code=code, name=name[:100], script=script, position=position, native=native[:100]))
        names[key(name)] = code
        position += 1
        report.count("languages added")


def import_countries(session: Session, report: Report) -> dict[str, Country]:
    """ Every ISO 3166 country, known again by its code or else its name, with its currencies and languages: the countries by code. """
    english = babel.Locale("en").territories
    rows = list(session.scalars(select(Country).options(selectinload(Country.currencies), selectinload(Country.languages))))
    by_code = {country.code: country for country in rows if country.code}
    unknown = {key(country.name): country for country in rows if not country.code}
    taken = {key(country.name) for country in rows}
    currencies = {currency.code: currency for currency in session.scalars(select(Currency))}
    locales = {locale.code: locale for locale in session.scalars(select(Locale))}
    countries: dict[str, Country] = {}
    for iso in sorted(pycountry.countries, key=lambda c: c.alpha_2):
        code = iso.alpha_2
        country = by_code.get(code)
        if country is None:
            names = [english.get(code), iso.name, getattr(iso, "common_name", None), getattr(iso, "official_name", None), *COUNTRY_ALIASES.get(code, ())]
            country = next((unknown.pop(key(name)) for name in names if name and key(name) in unknown), None)
            if country is not None:
                country.code = code
                report.count("countries matched")
            else:
                name = english.get(code) or iso.name
                if key(name) in taken:
                    report.count("countries skipped")
                    report.say(f"Country {code} ({name}): another country is called so already")
                    continue
                country = Country(name=name[:100], code=code)
                session.add(country)
                taken.add(key(name))
                report.count("countries added")
        else:
            report.count("countries already there")
        if not country.code3:
            country.code3 = iso.alpha_3
        for currency_code in babel.numbers.get_territory_currencies(code, tender=True):
            currency = currencies.get(currency_code)
            if currency is not None and currency not in country.currencies:
                country.currencies.append(currency)
                report.count("currencies of countries added")
        for language in babel.languages.get_official_languages(code):
            locale = locales.get(language.partition("_")[0])
            if locale is not None and locale not in country.languages:
                country.languages.append(locale)
                report.count("languages of countries added")
        countries[code] = country
    return countries


class _Regions:
    """ The regions, found by GeoNames' code, or by name in their country (and then given the code), or made. """

    def __init__(self, session: Session, report: Report) -> None:
        self.session = session
        self.report = report
        rows = list(session.scalars(select(Region)))
        self.by_code = {region.code: region for region in rows if region.code}
        self.of_country: dict[int, list[Region]] = {}
        for region in rows:
            if region.country is not None:
                self.of_country.setdefault(id(region.country), []).append(region)

    def get(self, country: Country, code: str, name: str) -> Region | None:
        if not name:
            return None
        region = self.by_code.get(code)
        if region is not None:
            return region
        here = self.of_country.setdefault(id(country), [])
        region = next((r for r in here if r.name == name), None) or next((r for r in here if r.code is None and region_like(r.name, name)), None)
        if region is None:
            region = Region(name=name[:100], country=country)
            self.session.add(region)
            here.append(region)
            self.report.count("regions added")
        if region.code is None:
            region.code = code
        self.by_code[code] = region
        return region


def _float(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def import_cities(session: Session, countries: dict[str, Country], least: int, report: Report) -> None:
    """ Every city GeoNames has with at least least people, biggest first, known again by its GeoNames id or else its name. """
    names = geonames_regions()
    found = []
    for row in geonames_cities():
        if len(row) < 15 or not row[0].isdigit() or not row[14].isdigit() or int(row[14]) < least:
            continue
        found.append(row)
    found.sort(key=lambda row: -int(row[14]))
    report.say(f"{len(found)} cities of at least {least:,} people")
    rows = list(session.scalars(select(City).options(selectinload(City.region_row), selectinload(City.country))))
    by_id = {city.geonames_id: city for city in rows if city.geonames_id is not None}
    # the cities not known by GeoNames' id yet, by their countries: a city met by its name is given its id
    loose: dict[int, list[City]] = {}
    for city in rows:
        if city.geonames_id is None and city.country is not None:
            loose.setdefault(id(city.country), []).append(city)
    taken = {(city.name, id(city.region_row) if city.region_row else None, id(city.country) if city.country else None) for city in rows}
    regions = _Regions(session, report)
    for row in found:
        geonames_id, name, ascii_name, others = int(row[0]), row[1].strip(), row[2], row[3]
        latitude, longitude, country_code, region_code, population = _float(row[4]), _float(row[5]), row[8], f"{row[8]}.{row[10]}", int(row[14])
        country = countries.get(country_code)
        if country is None or not name:
            report.count("cities skipped")
            continue
        city = by_id.get(geonames_id)
        if city is None:
            region_name = names.get(region_code, "")
            near = [c for c in loose.get(id(country), []) if c.region_row is None or not region_name or region_like(c.region_row.name, region_name)]
            first = {key(name), key(ascii_name)}
            city = next((c for c in near if key(c.name) in first), None)
            if city is None:
                more = {key(other) for other in others.split(",") if other}
                city = next((c for c in near if key(c.name) in more), None)
            if city is not None:
                loose[id(country)].remove(city)
                city.geonames_id = geonames_id
                by_id[geonames_id] = city
                report.count("cities matched")
                # a region it lacks is filled in, unless that makes it another city's double
                region = regions.get(country, region_code, region_name) if city.region_row is None else None
                if region is not None and (city.name, id(region), id(country)) not in taken:
                    taken.discard((city.name, None, id(country)))
                    taken.add((city.name, id(region), id(country)))
                    city.region_row = region
            else:
                region = regions.get(country, region_code, region_name)
                identity = (name[:100], id(region) if region else None, id(country))
                if identity in taken:
                    report.count("cities skipped")
                    continue
                taken.add(identity)
                city = City(name=name[:100], region_row=region, country=country, geonames_id=geonames_id)
                session.add(city)
                by_id[geonames_id] = city
                report.count("cities added")
        else:
            report.count("cities already there")
        if city.latitude is None or city.longitude is None:
            city.latitude, city.longitude = latitude, longitude
        # a country not on the map yet is put where its capital is
        if row[7] == "PPLC" and (country.latitude is None or country.longitude is None):
            country.latitude, country.longitude = latitude, longitude
            report.count("countries put on the map")
        if city.population != population:
            city.population = population


def run(session: Session, _owner: User, params: dict[str, Any], report: Report) -> None:
    what = set(params.get("what") or [])
    sizes = params.get("cities_over") or []
    if "cities" in what and not sizes:
        raise ParamError("Cities over: choose how big a city must be to be brought")
    if "currencies" in what:
        report.say("Currencies")
        import_currencies(session, report)
        session.flush()
    if "languages" in what:
        report.say("Languages")
        import_languages(session, report)
        session.flush()
    if "countries" in what or "cities" in what:
        report.say("Countries" if "countries" in what else "Countries (the cities need them)")
        countries = import_countries(session, report)
        session.flush()
        if "cities" in what:
            report.say("Cities")
            import_cities(session, countries, int(sizes[0]), report)
            session.flush()


IMPORTER = register(Importer(
    name="locale",
    title="Locale: countries, currencies, languages and cities",
    description=(
        "Brings the world into the shared data, everyone's: every country (ISO 3166, with its currencies and official "
        "languages), every currency in use, every language with a two-letter code, and every city over the size you "
        "choose (GeoNames). A row there already is known again and keeps its id and its name; only what it lacks is "
        "filled in. Nothing is deleted. Safe to run again."
    ),
    dataset="countries",
    params=(
        Param(
            name="what", title="What", kind="choices", required=True,
            description="What to bring (cities bring their countries too)",
            choices=lambda _session, _user: list(WHAT),
        ),
        Param(
            name="cities_over", title="Cities over", kind="choices", single=True,
            description="How many people a city must have to be brought",
            choices=lambda _session, _user: [(str(size), f"{size:,} people") for size in SIZES],
        ),
    ),
    run=run,
    shared=True,
))
