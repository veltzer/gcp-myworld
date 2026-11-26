"""
The languages (the locales table) and the script each is written in, and so
the languages a text can be in: "שיחות על תורת המשחקים" is not English,
whatever the form said when it was added. A title or a name is only ever
kept with a language of its own script; the script cannot tell English from
French, or Hebrew from Yiddish, so that much is still the person's to say.
"""

import collections
import functools
import sys
import unicodedata
from typing import TYPE_CHECKING

from sqlalchemy import select

from myworld.models import Locale

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def known(session: Session) -> dict[str, Locale]:
    """ The languages there are, by code, in the order the forms offer them. """
    return {locale.code: locale for locale in session.scalars(select(Locale).order_by(Locale.position, Locale.code))}


def script_of(text: str) -> str:
    """ The script most of the text's letters are in ("Hebrew", as Unicode names its letters); "" when it has no letters. """
    scripts = collections.Counter(unicodedata.name(char, "").partition(" ")[0].title() for char in text if char.isalpha())
    scripts.pop("", None)
    return scripts.most_common(1)[0][0] if scripts else ""


def fits(locale: Locale, text: str) -> bool:
    """ Whether the text can be in the language: it is in its script, or has no letters to tell by ("1984"). """
    return script_of(text) in ("", locale.script)


def locale_of(locales: dict[str, Locale], text: str) -> str:
    """ The first language of the text's script: Hebrew for Hebrew letters; "" when no language here is written in it. """
    script = script_of(text)
    return next((code for code, locale in locales.items() if locale.script == script), "")


@functools.cache
def scripts() -> frozenset[str]:
    """ The scripts letters are written in, as Unicode names them ("Latin", "Hebrew", "Cyrillic"): what a language's script can be. """
    return frozenset(
        unicodedata.name(char, "").partition(" ")[0].title()
        for char in map(chr, range(sys.maxunicode + 1)) if char.isalpha()
    ) - {""}
