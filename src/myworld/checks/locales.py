"""
Checks of the languages.
"""


from typing import TYPE_CHECKING

from myworld import languages
from myworld.checks.core import (
    Problem,
    Result,
    check,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@check("locale-scripts", "Every language is written in a script there is", "languages", "locales")
def check_locale_scripts(session: Session) -> Result:
    """
    Every language (the locales table) names the script it is written in as
    Unicode names it ("Latin", "Hebrew", "Cyrillic"): a title or a name is
    told to be in a language by its letters, so a script misspelt fits nothing.
    """
    locales = languages.known(session).values()
    return Result(checked=len(locales), problems=[
        Problem(f"{locale.name} ({locale.code})", f"is written in {locale.script or 'no script'}, which is not a script letters are in", f"locales/{locale.position}")
        for locale in locales if locale.script not in languages.scripts()
    ])


@check("locale-native-names", "Every language has its own name, in its own script", "languages", "locales")
def check_locale_native_names(session: Session) -> Result:
    """
    Every language (the locales table) says what it is called in itself,
    written in its own script ("עברית", "Русский"): its picture is that
    name, written out, so the page shows what the script looks like.
    """
    locales = languages.known(session).values()
    problems = []
    for locale in locales:
        if not locale.native.strip():
            problems.append(Problem(f"{locale.name} ({locale.code})", "does not say what it is called in itself", f"locales/{locale.position}"))
        elif not languages.fits(locale, locale.native):
            problems.append(Problem(f"{locale.name} ({locale.code})", f"is called {locale.native} in itself, which is not written in {locale.script} letters", f"locales/{locale.position}"))
    return Result(checked=len(locales), problems=problems)
