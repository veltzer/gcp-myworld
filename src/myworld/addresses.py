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


def split_text(text: str, city: str, region: str, country: str) -> tuple[str, str, str, bool]:
    """
    (street, neighbourhood, postcode, whole) from an address typed as one line,
    "23 Kaplan St., HaKirya, Tel Aviv 6473424, Israel": the parts that are the
    city, its region or its country are left out (the city carries them), a
    postcode is found anywhere, the first part left is the street and the
    next the neighbourhood. whole is False when more was written than fits
    (a third part, a remark in brackets), so the caller can keep the text.
    """
    whole = True
    if re.search(r"\([^)]*\)", text):
        whole = False
        text = re.sub(r"\([^)]*\)", "", text)
    postcode = ""
    found = POSTCODE.search(text)
    if found:
        postcode = found.group(1)
        text = text[:found.start()] + text[found.end():]
    known = {city_key(name, "")[0] for name in (city, region, country, country_name(country)) if name}

    def kept(part: str) -> bool:
        # the city, its region, its country however written ("USA"), or a state's code ("NY") is the city's to carry
        if city_key(part, "")[0] in known or city_key(country_name(part), "")[0] in known:
            return False
        return not (country_name(country) in REGIONED and re.fullmatch(r"[A-Z]{2}", part))

    parts = [" ".join(part.split()) for part in text.split(",")]
    parts = [part for part in parts if part and kept(part)]
    if len(parts) > 2:
        whole = False
    return (parts[0] if parts else ""), (parts[1] if len(parts) > 1 else ""), postcode, whole


def compose(street: str, neighbourhood: str, city: str, postcode: str, country: str) -> str:
    """ The address in one line, the same order everywhere: "Ibn Gabirol 30, Sarona, Tel Aviv 6473424, Israel". """
    town = " ".join(part for part in (city, postcode) if part)
    return ", ".join(part for part in (street, neighbourhood, town, country) if part)
