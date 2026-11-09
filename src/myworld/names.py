"""
People's names: a first name and a surname are one word each (a surname of
two words is hyphenated, "Di-Meola"); everything between them is the middle
name, which may be several words ("Ronald Reuel"). A name that is not a
person's (a band, "Open stage") is not split: it stays whole in the first
name, and the people-names check lists it to be fixed by hand.
"""

import re

# a word a surname of two words starts with: "Al Di Meola", "Marcus du Sautoy", "Nitzan Ein Habar"
PARTICLES = frozenset({"bar", "bat", "ben", "da", "de", "del", "der", "di", "du", "ein", "la", "le", "van", "von"})
# words that make a name a group's, not a person's
GROUP_WORDS = frozenset({"band", "ensemble", "jazz", "machine", "messengers", "orchestra", "quartet", "quintet", "the", "trio"})
TITLES = frozenset({"dr", "dr.", "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "prof", "prof.", "sir"})
# a word of a person's name: capitalized ("Kasser", "L.", "R.O.B"), lower then upper ("akLaff"), or a quoted nickname
NAME_WORD = re.compile(r"[A-Z][\w.'-]*|[a-z]+[A-Z][\w.'-]*|\"[^\"]+\"")
INITIAL = re.compile(r"[A-Z]\.")
SPACE = re.compile(r"\s")


def has_space(value: str) -> bool:
    return SPACE.search(value) is not None


def key(name: str) -> str:
    """ A name to match people by, the same however it is spaced or hyphenated: "Al Di Meola" finds "Al Di-Meola". """
    return " ".join(name.replace("-", " ").split()).casefold()


def _surname(words: list[str]) -> tuple[list[str], str]:
    """ The words before the surname, and the surname: a particle joins the last word, hyphenated. """
    if len(words) >= 3 and words[-2].lower() in PARTICLES:
        return words[:-2], f"{words[-2]}-{words[-1]}"
    return words[:-1], words[-1]


def split_name(name: str) -> tuple[str, str, str] | None:
    """
    A whole person's name as (first, middle, surname): "Jeffrey L. Kasser" is
    ("Jeffrey", "L.", "Kasser"), "Al Di Meola" ("Al", "", "Di-Meola"), "Prince"
    ("Prince", "", ""). None when it is not plainly a person's name: a band,
    a description, a title ("Sir Arthur Conan Doyle"), anything in brackets.
    """
    words = name.split()
    if not words:
        return None
    if len(words) == 1:
        return words[0], "", ""
    lowered = [w.lower() for w in words]
    if lowered[0] in TITLES or GROUP_WORDS.intersection(lowered):
        return None
    if not all(NAME_WORD.fullmatch(w) or w.lower() in PARTICLES for w in words) or not NAME_WORD.fullmatch(words[0]):
        return None
    before, surname = _surname(words)
    return before[0], " ".join(before[1:]), surname


def tidy(first: str, middle: str, surname: str) -> tuple[str, str, str]:
    """
    The parts of a name made to follow the rules where it is plain how:
    a whole name in the first name is split, more words in the first name go
    to the middle name, an initial leading the surname ("R. Hofstaddter")
    goes to the middle name and the rest of the surname is hyphenated. What
    is not plainly a person's name is left as it is.
    """
    if not surname and not middle and has_space(first):
        split = split_name(first)
        return split if split is not None else (first, middle, surname)
    middles = [middle] if middle else []
    if has_space(first):
        words = first.split()
        first, middles = words[0], [*words[1:], *middles]
    if has_space(surname):
        words = surname.split()
        while len(words) > 1 and INITIAL.fullmatch(words[0]):
            middles.append(words.pop(0))
        surname = "-".join(words)
    return first, " ".join(middles), surname
