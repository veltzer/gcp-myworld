"""
The script each language is written in, and so the languages a text can be
in: "שיחות על תורת המשחקים" is not English, whatever the form said when it
was added. A title or a name is only ever kept with a language of its own
script; the script cannot tell English from French, or Hebrew from Yiddish,
so that much is still the person's to say.
"""

import collections
import unicodedata

from myworld.models import LOCALES

# language -> its script, named as Unicode names its letters ("HEBREW LETTER ALEF"),
# which is also what a regular expression calls it (\\p{Script=Hebrew}, in app.js)
SCRIPTS: dict[str, str] = {
    "en": "Latin",
    "he": "Hebrew",
    "ar": "Arabic",
    "yi": "Hebrew",
    "fr": "Latin",
    "de": "Latin",
    "es": "Latin",
    "it": "Latin",
    "pt": "Latin",
    "ru": "Cyrillic",
    "cs": "Latin",
    "el": "Greek",
}
assert SCRIPTS.keys() == LOCALES.keys()


def script_of(text: str) -> str:
    """ The script most of the text's letters are in ("Hebrew"); "" when it has no letters. """
    scripts = collections.Counter(unicodedata.name(char, "").partition(" ")[0].title() for char in text if char.isalpha())
    scripts.pop("", None)
    return scripts.most_common(1)[0][0] if scripts else ""


def fits(locale: str, text: str) -> bool:
    """ Whether the text can be in the language: it is in its script, or has no letters to tell by ("1984"). """
    return script_of(text) in ("", SCRIPTS[locale])


def locale_of(text: str) -> str:
    """ The first language (in LOCALES' order) of the text's script: Hebrew for Hebrew letters; "" when no language here is written in it. """
    script = script_of(text)
    return next((locale for locale in LOCALES if SCRIPTS[locale] == script), "")
