"""
Addresses in three parts beside the row's city (which carries the region and
the country): street (one line in local order: "Ibn Gabirol 30", "88 7th
Avenue South", "1-2-3 Ginza", or directions where there is no street),
neighbourhood ("Sarona", a ward, a district) and postcode. They are shown in
one order everywhere: "Street, Neighbourhood, City Postcode, Country".
"""

import re

from myworld.cities import REGIONED, city_key, country_name

# where a house number comes before the street ("88 7th Avenue South"); elsewhere after it ("Ibn Gabirol 30")
NUMBER_FIRST = {
    "United States of America", "United Kingdom", "Canada", "Australia", "New Zealand", "Ireland", "France",
    "Gibraltar", "Cyprus", "Singapore", "Hong Kong", "India", "South Africa",
}
# postcodes as addresses write them: 5-7 digits (US ZIP+4 too), or British/Canadian letters and digits
POSTCODE = re.compile(r"\b(\d{5,7}(?:-\d{4})?|[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}|[A-Z]\d[A-Z] ?\d[A-Z]\d)\b")
# OpenStreetMap's names for the level between a street and a city, most local first
NEIGHBOURHOOD_KEYS = ("neighbourhood", "quarter", "suburb", "city_district", "borough", "hamlet")
# OpenStreetMap's names for what a street line is made of when there is no road
PLACE_KEYS = ("road", "pedestrian", "footway", "square", "place")


def street_line(road: str, number: str, country: str) -> str:
    """ A street and its house number, in the country's order. """
    if not number:
        return road
    if not road:
        return number
    return f"{number} {road}" if country_name(country) in NUMBER_FIRST else f"{road} {number}"


def from_osm(parts: dict[str, str], country: str) -> tuple[str, str, str]:
    """ (street, neighbourhood, postcode) from OpenStreetMap's address parts (Nominatim addressdetails). """
    road = next((parts[key] for key in PLACE_KEYS if parts.get(key)), "")
    street = street_line(road, parts.get("house_number", ""), country)
    neighbourhood = next((parts[key] for key in NEIGHBOURHOOD_KEYS if parts.get(key)), "")
    return street, neighbourhood, parts.get("postcode", "")


# a city part's postcode as written around the world ("753 20 Uppsala", "1012 AB Amsterdam"): the tokens with digits
CODE_TOKEN = re.compile(r"^[A-Z]{0,2}\d[\dA-Z-]*$")


def parse_address(text: str, cities: set[str] | frozenset[str] = frozenset(), country_hint: str = "") -> dict[str, str | bool]:
    """
    An address typed in one line, in its parts: street, neighbourhood,
    postcode, city, region, country, and whole (False when more was written
    than the parts hold, so the caller keeps the text). The country is the
    last part ("country_hint" when there is only one part); the region the
    next for countries with regions ("California", "Massachusetts"); the
    postcode anywhere; the city the last part that is one of cities (keys
    from myworld.cities.city_key), else the last part left; the street every
    part up to the last with a number in it ("Atrium Tower, 18th Floor, 2
    Jabotinsky St."), and the neighbourhood the part after it.
    """
    whole = True
    if "(" in text:
        whole = False
        text = re.sub(r"\([^)]*(\)|$)", "", text)
    postcode = ""
    found = POSTCODE.search(text)
    if found:
        postcode = found.group(1)
        text = text[:found.start()] + text[found.end():]
    parts = [" ".join(part.split()) for part in text.split(",")]
    parts = [part for part in parts if part]
    country = country_name(parts.pop()) if len(parts) > 1 else country_name(country_hint)
    region = ""
    if country in REGIONED and len(parts) > 1 and not re.search(r"\d", parts[-1]):
        region = parts.pop()
    # a state's code ("NY") is not a part of its own
    parts = [part for part in parts if not (country in REGIONED and re.fullmatch(r"[A-Z]{2}", part))]
    city = ""
    for index in range(len(parts) - 1, -1, -1):
        name = " ".join(token for token in parts[index].split() if not CODE_TOKEN.match(token))
        if city_key(name, "")[0] in cities:
            city = name
            # what follows the city (a county: "Surrey") is said but not kept in a part
            whole = whole and index == len(parts) - 1
            parts = parts[:index]
            break
    else:
        if city_key(country, "")[0] in cities:
            # a city that is its country (Hong Kong, Singapore, Gibraltar): every part left is the address
            city = country
        elif len(parts) > 1:
            last = parts.pop().split()
            codes = [token for token in last if CODE_TOKEN.match(token)]
            city = " ".join(token for token in last if not CODE_TOKEN.match(token))
            postcode = postcode or " ".join(codes)
            # a neighbourhood named with its city ("Herzliya Pituach", "South Netanya") is in that city
            words = city_key(city, "")[0].split()
            inside = [known for known in cities if known != city_key(city, "")[0] and _within(known.split(), words)]
            if inside:
                parts.append(city)
                city = max(inside, key=len)
    numbered = [index for index, part in enumerate(parts) if re.search(r"\d", part)]
    cut = numbered[-1] + 1 if numbered else min(1, len(parts))
    street, rest = ", ".join(parts[:cut]), parts[cut:]
    if len(rest) > 1:
        whole = False
    return {
        "street": street, "neighbourhood": rest[0] if rest else "", "postcode": postcode,
        "city": city, "region": region, "country": country, "whole": whole,
    }


def _within(short: list[str], long: list[str]) -> bool:
    """ Whether the words short are a run of the words long. """
    return any(long[i:i + len(short)] == short for i in range(len(long) - len(short) + 1))


def split_text(text: str, city: str, region: str, country: str) -> tuple[str, str, str, bool]:
    """
    (street, neighbourhood, postcode, whole) of an address typed in one line
    of a row in city (in region and country): see parse_address. whole is
    False when more was written than fits, so the caller can keep the text.
    """
    parsed = parse_address(text, {city_key(city, "")[0]} if city else set(), country)
    return str(parsed["street"]), str(parsed["neighbourhood"]), str(parsed["postcode"]), bool(parsed["whole"])


def compose(street: str, neighbourhood: str, city: str, postcode: str, country: str) -> str:
    """ The address in one line, the same order everywhere: "Ibn Gabirol 30, Sarona, Tel Aviv 6473424, Israel". """
    town = " ".join(part for part in (city, postcode) if part)
    return ", ".join(part for part in (street, neighbourhood, town, country) if part)
