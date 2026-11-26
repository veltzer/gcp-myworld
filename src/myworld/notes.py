"""
What the notes of a book say that the book says elsewhere: the language it
was written in ("Written in French") and a name it once had ("was named:
Ulysees") that is one of its titles told a little differently.
scripts/tidy_book_notes.py takes these out of the notes, and the check
book-notes (checks/library.py) finds the notes that still say them.
"""

import difflib
import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myworld.models import UserWork

WRITTEN = re.compile(r"Written in (\w+)(?:\. |\.?$)")
# the name the book once had: the last thing its notes say, after a sentence or a clause
NAMED = re.compile(r"(?:^|; |\. )was named: (.+)$")
# how alike a name and a title are for one to be the other misspelt ("Silmarilion")
ALIKE = 0.85


def _plain(text: str) -> str:
    """ A title as it is compared: its letters and digits, lowercase and unaccented, "&" an "and", no leading article. """
    text = unicodedata.normalize("NFKD", text.casefold().replace("&", " and "))
    words: list[str] = re.findall(r"\w+", "".join(char for char in text if not unicodedata.combining(char)).replace("'", "").replace("\u2019", ""))
    return " ".join(words[1:] if words and words[0] in ("the", "a", "an") else words)


def same_title(name: str, titles: list[str]) -> bool:
    """
    Whether name is one of titles told a little differently: a part of it
    (words in a row, of two or more words or a whole part before or after
    its colon), or it or such a part but for the spelling.
    """
    said = _plain(name)
    if not said:
        return False
    for title in titles:
        whole = _plain(title)
        parts = [whole, *(_plain(part) for part in re.split(r":| or, |, or | - ", title))]
        if said in parts or (" " in said and f" {said} " in f" {whole} "):
            return True
        if any(difflib.SequenceMatcher(None, said, part).ratio() >= ALIKE for part in parts if part):
            return True
    return False


def without_said_twice(entry: UserWork, codes: dict[str, str]) -> str:
    """ The entry's notes without the language it was written in and the name it once had, where the book says them elsewhere. """
    notes = entry.notes
    work = entry.work
    written = WRITTEN.match(notes)
    if written:
        known = {work.original_locale, work.title_locale, *(t.locale for t in work.titles), *(read.locale for read in entry.reads), *entry.owned}
        if codes.get(written.group(1).lower()) in known - {None}:
            notes = notes[written.end():]
    named = NAMED.search(notes)
    if named and same_title(named.group(1).rstrip("."), [work.title, *(t.title for t in work.titles)]):
        notes = notes[:named.start()]
    return notes.strip()
