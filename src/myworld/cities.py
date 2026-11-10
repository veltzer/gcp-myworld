"""
Cities from the free text they used to be: "Tel-Aviv" on a place,
"Santa Clara, California, USA (Nvidia)" on an organization. A city is a
name, a region (a state or province, for countries that have them in
addresses) and a country; one city written two ways ("Tel-Aviv", "Tel Aviv";
"Ramat Hasharon", "Ramat HaSharon"; "USA", "United States of America") is
one city, under the better of its spellings.
"""

import re

# countries as written in addresses -> as a city carries them
COUNTRY_NAMES = {
    "usa": "United States of America",
    "us": "United States of America",
    "united states": "United States of America",
    "uk": "United Kingdom",
    "england": "United Kingdom",
}
# countries whose addresses name a region (state, province) between the city and the country
REGIONED = {"United States of America", "Canada", "Australia"}
# what follows a city's name and is not part of it: "Beersheba area"
SUFFIX = re.compile(r"\s+area$", re.IGNORECASE)


def country_name(text: str) -> str:
    text = " ".join(text.split())
    return COUNTRY_NAMES.get(text.casefold(), text)


def city_key(name: str, country: str) -> tuple[str, str]:
    """ The same however it is spaced, hyphenated, capitalized or transliterated: "Tel-Aviv" is "Tel Aviv". """
    def norm(text: str) -> str:
        # transliterations differ in apostrophes and doubled letters: "Ra'anana" / "Raanana", "Yokneam Illit" / "Yokneam Ilit"
        text = " ".join(text.replace("-", " ").replace("'", "").replace("\u2019", "").split()).casefold()
        return re.sub(r"(.)\1", r"\1", text)
    return norm(name), norm(country_name(country))


def better(one: str, other: str) -> str:
    """ Of two spellings of a name, the one with more capitals ("HaSharon"), then without hyphens ("Tel Aviv"). """
    def score(text: str) -> tuple[int, int]:
        return sum(c.isupper() for c in text), -text.count("-")
    return max(one, other, key=score)


def parse_location(text: str) -> tuple[str, str, str] | None:
    """
    (city, region, country) of an organization's location, or None when
    it names none. Remarks in brackets and after a ";" are left out;
    "City, Region, Country" for countries with regions, "Place, City,
    Country" (the city second) for others.
    """
    # a remark in brackets goes, an unclosed one ("(Nexxen; also ...)" cut at the ";") to the end
    text = re.sub(r"\([^)]*(\)|$)", "", text.split(";")[0])
    parts = [" ".join(part.split()) for part in text.split(",")]
    parts = [part for part in parts if part]
    if not parts:
        return None
    if len(parts) == 1:
        # "Gibraltar": a city that is its own country
        return parts[0], "", country_name(parts[0])
    country = country_name(parts[-1])
    if len(parts) == 2:
        return SUFFIX.sub("", parts[0]), "", country
    if country in REGIONED:
        return SUFFIX.sub("", parts[0]), parts[1], country
    return SUFFIX.sub("", parts[-2]), "", country
