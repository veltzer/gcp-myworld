"""
Database schema.

Works (books, films, ...) are rows of the account that has them, as
everything is: nothing is shared between accounts. What a user thinks about a
work (status, rating, dates, notes) lives in its UserWork row, apart from what
the work is, so that works can be shared later.
Adding a new kind of work is a matter of adding it to KINDS.

Concerts, visits (to museums, ...), the people they were shared with and
the organizations those people work at are a second, separate part: each
row belongs to one user (owner_id) and is never shared.

Some data is shared instead: the same rows for every account, which
everyone sees and only admins change, with nothing personal on them (no
remark, no rating). A shared table has no owner_id (is_shared): the
languages (locales), currencies, countries, regions, cities, places and
their kinds (place_kinds), and the types of visit (visit_types). An admin
changes them by hand only with Edit shared data turned on (may_edit_shared),
and the Locale importer brings the countries, currencies, languages and
cities of the world into them. A user's rows point
into them: a concert to its place, a visit to the place visited, an
organization to its city. A person may be linked
to several organizations, each link of a kind ("Worked at", "Studied at":
person_organizations, PersonOrganization).
Their photos live in the images table, so the database alone holds all of it.
They are loaded by scripts/import_world.py.
"""

import datetime
import os
from collections.abc import Callable
from typing import Any, cast

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    false,
    insert,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from myworld.addresses import compose

# kind -> (display name, plural, what the "creator" column is called for that kind)
KINDS: dict[str, tuple[str, str, str]] = {
    "book": ("Book", "Books", "Author"),
}

STATUSES: dict[str, str] = {
    "wishlist": "Want to",
    "in_progress": "In progress",
    "done": "Done",
    "abandoned": "Abandoned",
}

# the languages a name, a title or a reading can be in, as the locales table
# starts out (code, name, the script it is written in, named as Unicode names
# its letters: "HEBREW LETTER ALEF"), in the order the forms offer them. The
# table is what counts: make_engine adds the ones missing from it. A person's
# own name parts are their English name ("en"); a book is shown in the
# language it was read in, with its authors' names in it
SEED_LOCALES: list[tuple[str, str, str]] = [
    ("en", "English", "Latin"),
    ("he", "Hebrew", "Hebrew"),
    ("ar", "Arabic", "Arabic"),
    ("yi", "Yiddish", "Hebrew"),
    ("fr", "French", "Latin"),
    ("de", "German", "Latin"),
    ("es", "Spanish", "Latin"),
    ("it", "Italian", "Latin"),
    ("pt", "Portuguese", "Latin"),
    ("ru", "Russian", "Cyrillic"),
    ("cs", "Czech", "Latin"),
    ("el", "Greek", "Greek"),
]
DEFAULT_LOCALE = "en"
# what each of them is called in itself, written in its own script: what its picture shows
LOCALE_NATIVE: dict[str, str] = {
    "en": "English", "he": "עברית", "ar": "العربية", "yi": "ייִדיש", "fr": "Français", "de": "Deutsch",
    "es": "Español", "it": "Italiano", "pt": "Português", "ru": "Русский", "cs": "Čeština", "el": "Ελληνικά",
}

RATING_MIN = 1
RATING_MAX = 10


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class Base(DeclarativeBase):
    pass


# how the pages look, each user's own (Settings): "system" follows the device
THEMES = ("system", "light", "dark")
DEFAULT_THEME = "system"

ROLE_USER = "user"
ROLE_ADMIN = "admin"
ROLES = (ROLE_USER, ROLE_ADMIN)


# a username: 3 to 30 of lowercase letters, digits, ".", "-" and "_", starting with a letter
USERNAME_MIN = 3
USERNAME_MAX = 30
USERNAME_PATTERN = rf"[a-z][a-z0-9._-]{{{USERNAME_MIN - 1},{USERNAME_MAX - 1}}}"
# names no one may take: they would read as the site's own
USERNAMES_RESERVED = frozenset({"admin", "administrator", "root", "system", "support", "help", "api", "app", "www", "myworld", "anonymous", "null", "none"})


class User(Base):
    """
    A person with an account, one per email, who owns the data. They sign
    in through any number of logins (Login): with Google, with GitHub, with
    a password. Only a proven email gets an account: one Google or GitHub
    vouches for (email_verified, the verified primary address), or one whose
    mailed verification link was followed (EmailVerification). So a login
    joins the user of its email and the same person signing in any way
    reaches the same data; an address merely typed into a form gets nothing.
    """
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username", name="uq_user_username"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # proven to be this person's by the provider of the login that made the account
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    # the name the account is known by, chosen by its user (USERNAME_PATTERN, lowercase): one account's
    # alone; None until chosen (the app asks for it before anything else)
    username: Mapped[str | None] = mapped_column(String(USERNAME_MAX), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    picture: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    # what the account may do on the site, one of ROLES: an admin can also see
    # every account and change its role (the Users page) and run checks over
    # the whole database. The first admin is made by scripts/migrate.sh.
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=ROLE_USER, server_default=ROLE_USER)
    # the language they prefer (Settings): a book with titles in several languages is
    # shown by its title in this one, and its authors by their names in it
    locale: Mapped[str] = mapped_column(ForeignKey("locales.code"), nullable=False, default=DEFAULT_LOCALE, server_default=DEFAULT_LOCALE)
    # light, dark, or the device's (THEMES)
    theme: Mapped[str] = mapped_column(String(10), nullable=False, default=DEFAULT_THEME, server_default=DEFAULT_THEME)
    # an admin's own lock on the shared data (may_edit_shared): off, even an admin cannot change it by
    # hand, so it is not changed by accident; Settings turns it on. A regular user never may.
    edit_shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    last_login: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    works: Mapped[list[UserWork]] = relationship(  # pylint: disable=used-before-assignment
        back_populates="user", cascade="all, delete-orphan",
    )
    # every way this person signs in
    logins: Mapped[list[Login]] = relationship(
        back_populates="user", cascade="all, delete-orphan", order_by=lambda: Login.id,  # pylint: disable=used-before-assignment
    )


class Login(Base):
    """
    One way of signing in, keyed by the provider-qualified subject: the
    stable identity the provider vouches for, never the email, which can
    change and be given to someone else.

        google:<sub>      Sign in with Google (the ID token's "sub")
        github:<id>       GitHub (the numeric user id)
        email:<address>   email and password, made once the mailed link was followed
        dev:<address>     the local development login (never on Cloud Run)

    A login joins a user once and stays: should the provider's address change
    later, the login keeps its user rather than moving to another.
    """
    __tablename__ = "logins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject: Mapped[str] = mapped_column(String(400), unique=True, nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # what the provider last reported
    email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    picture: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    # only for an email login; werkzeug hash
    password_hash: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    last_login: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="logins")

    @property
    def method(self) -> str:
        """ How it signs in: google, github, email or dev. """
        return self.subject.partition(":")[0]

    @property
    def provider_id(self) -> str:
        """ Who the provider says it is: the Google sub, the GitHub user id, the email address. """
        return self.subject.partition(":")[2]


class EmailVerification(Base):
    """
    An email address someone asked to sign up (or to set a new password)
    with, waiting for its mailed link to be followed. The link carries a
    secret token that only the mail holds; here is its SHA-256, so the
    table alone lets no one in. Whoever brings the token back reads that
    mailbox: only then do they choose a password and get an email login
    (see auth). Until then the address can be used for nothing.
    """
    __tablename__ = "email_verifications"

    email: Mapped[str] = mapped_column(String(320), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    sent_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Locale(Base):
    """
    A language a title, a name or a reading can be in: every locale column
    points here (library_works.title_locale, library_work_titles.locale,
    library_entries.locale, person_names.locale). The same for every
    account, as the works are.
    """
    __tablename__ = "locales"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    # the script it is written in ("Hebrew"): a text in other letters is not in this language
    script: Mapped[str] = mapped_column(String(50), nullable=False)
    # where the forms list it; the first of a script is the one its letters suggest
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # what it is called in itself, in its own script ("עברית"): its picture is this, written out
    native: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")


@event.listens_for(Locale.__table__, "after_create")
def _fill_locales(target: Table, connection: Connection, **_: Any) -> None:
    """ A locales table just made starts with the languages of SEED_LOCALES. """
    connection.execute(insert(target), [
        {"code": code, "name": name, "script": script, "position": position, "native": LOCALE_NATIVE.get(code, "")}
        for position, (code, name, script) in enumerate(SEED_LOCALES)
    ])


def is_shared(model: Any) -> bool:
    """ Whether model's rows are everyone's (no owner_id): seen by every account, changed by admins only. """
    return "owner_id" not in model.__table__.c


def may_edit_shared(user: User) -> bool:
    """ Whether user may change the shared rows by hand: an admin who has turned on Edit shared data (Settings). """
    return user.role == ROLE_ADMIN and user.edit_shared


class Work(Base):
    __tablename__ = "library_works"
    __table_args__ = (
        UniqueConstraint("owner_id", "kind", "title", "creator", "year", name="uq_work_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # the account whose work it is: another account that has the same book has a row of its own
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    creator: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # books: the ISBN (of the edition read, when it is known which) and the Open
    # Library work ("OL27482W"); scripts/fetch_book_details.py fills them and the year
    isbn: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    openlibrary_id: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    # films: filled from The Movie Database when the work is added through the search (see movies.py)
    imdb_id: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rotten_tomatoes_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # books: Goodreads, and Simania (a Hebrew catalog) for a book read in Hebrew
    goodreads_id: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    simania_id: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    # the language the title is in; the work's titles in other languages are in titles
    title_locale: Mapped[str] = mapped_column(ForeignKey("locales.code"), nullable=False, default=DEFAULT_LOCALE, server_default=DEFAULT_LOCALE)
    # the language it was first written in (Dune: English, whatever it was read in); empty while not known
    original_locale: Mapped[str | None] = mapped_column(ForeignKey("locales.code"), nullable=True)

    users: Mapped[list[UserWork]] = relationship(back_populates="work")  # pylint: disable=used-before-assignment
    titles: Mapped[list[WorkTitle]] = relationship(
        back_populates="work", cascade="all, delete-orphan", order_by=lambda: WorkTitle.id,  # pylint: disable=used-before-assignment
    )

    def locale_for(self, preferred: str) -> str:
        """ The language the work is shown in to someone who prefers one: that one when it has a title in it, else its main title's. """
        if preferred == self.title_locale or any(other.locale == preferred for other in self.titles):
            return preferred
        return self.title_locale

    def title_in(self, locale: str | None) -> str:
        """ The title in locale: the main one when it is in it, else the other title in it, else the main one. """
        if locale and locale != self.title_locale:
            for other in self.titles:
                if other.locale == locale:
                    return other.title
        return self.title


class WorkTitle(Base):
    """
    The title of a work in another language than its main title's:
    "אינטליגנציה מלאכותית" (he) of "Artificial Intelligence". One per
    language: a work's titles are told apart by their language.
    """
    __tablename__ = "library_work_titles"
    __table_args__ = (UniqueConstraint("work_id", "locale", name="uq_work_title_locale"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("library_works.id", ondelete="CASCADE"), nullable=False, index=True)
    locale: Mapped[str] = mapped_column(ForeignKey("locales.code"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)

    work: Mapped[Work] = relationship(back_populates="titles")


class DisabledCheck(Base):
    """
    A database check (checks/) an admin turned off for themselves, one
    they cannot pass yet: Run all skips it, on the Checks page and on its
    data's page, and so does scripts/check.py --email. Turned back on, the
    row goes.
    """
    __tablename__ = "disabled_checks"

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    check_name: Mapped[str] = mapped_column(String(100), primary_key=True)


class UserWork(Base):
    __tablename__ = "library_entries"

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("library_works.id", ondelete="CASCADE"), primary_key=True)
    # anything worth keeping about it (where they have it, ...); where the user is with it, their
    # rating and what they thought of it belong to each reading (reads)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # the cover: an image of the user's own. An entry
    # may have several: this is the first, the one its card shows, and the
    # others are in more_covers
    image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="works")
    work: Mapped[Work] = relationship(back_populates="users", lazy="joined")
    # who wrote it (a book's authors): the user's own people
    authors: Mapped[list[Person]] = relationship(
        secondary=lambda: library_entry_authors, back_populates="wrote", order_by=lambda: Person.id,
    )
    # the times the user read it (or means to), each with its status, rating, review, days and language, in the order they were added
    reads: Mapped[list[Read]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", order_by=lambda: Read.id, lazy="selectin",
    )

    # its covers after the first (image_id), in the order they were added
    more_covers: Mapped[list[Cover]] = relationship(cascade="all, delete-orphan", order_by=lambda: Cover.id, lazy="selectin")

    # the languages the user owns it in, one row each, in the order they were added
    ownings: Mapped[list[Owning]] = relationship(cascade="all, delete-orphan", order_by=lambda: Owning.id, lazy="selectin")

    @property
    def owned(self) -> list[str]:
        """ The languages the user owns it in (locale codes). """
        return [owning.locale for owning in self.ownings]

    @owned.setter
    def owned(self, locales: list[str]) -> None:
        """ The user owns it in these languages, each once, in this order: rows of languages kept are kept. """
        kept = {owning.locale: owning for owning in self.ownings}
        self.ownings = [kept.get(locale) or Owning(locale=locale) for locale in dict.fromkeys(locales)]

    @property
    def cover_ids(self) -> list[int]:
        """ The images of all its covers: the first (image_id), then the others. """
        return ([self.image_id] if self.image_id is not None else []) + [cover.image_id for cover in self.more_covers]

    @cover_ids.setter
    def cover_ids(self, image_ids: list[int]) -> None:
        """ Its covers become these images, in this order: rows of images kept are kept. """
        self.image_id = image_ids[0] if image_ids else None
        kept = {cover.image_id: cover for cover in self.more_covers}
        self.more_covers = [kept.get(image_id) or Cover(image_id=image_id) for image_id in image_ids[1:]]

    @property
    def last_read(self) -> Read | None:
        """
        The reading the entry goes by: the last one still open (no day, and not
        done: wanted, in progress), else the latest that has a day, else the
        last one added; none when it has no reading.
        """
        still_open = [read for read in self.reads if read.read_on is None and read.status in ("wishlist", "in_progress")]
        if still_open:
            return still_open[-1]
        dated = [read for read in self.reads if read.read_on is not None]
        if dated:
            return max(dated, key=lambda read: read.read_on or datetime.date.min)
        return self.reads[-1] if self.reads else None

    @property
    def locale(self) -> str | None:
        """ The language the user read it in, last (none when not known). """
        read = self.last_read
        return read.locale if read else None

    @property
    def finished_on(self) -> datetime.date | None:
        """ The day the user finished it, last. """
        read = self.last_read
        return read.read_on if read else None

    @property
    def started_on(self) -> datetime.date | None:
        """ The day the user started it, last. """
        read = self.last_read
        return read.started_on if read else None

    @property
    def status(self) -> str:
        """ Where the user is with it: the status of the reading it goes by; never read, it is wanted. """
        read = self.last_read
        return read.status if read else "wishlist"

    def _latest(self, said: Callable[[Read], bool]) -> Read | None:
        """ The reading it goes by when it says something, else the latest one that does. """
        read = self.last_read
        if read is not None and said(read):
            return read
        saying = [read for read in self.reads if said(read)]
        return max(saying, key=lambda read: (read.read_on or datetime.date.min, read.id or 0)) if saying else None

    @property
    def rating(self) -> int | None:
        """ The user's rating of it: that of the reading it goes by, else of the latest reading rated. """
        read = self._latest(lambda read: read.rating is not None)
        return read.rating if read else None

    @property
    def review(self) -> str:
        """ What the user thought of it: the review of the reading it goes by, else of the latest reading reviewed. """
        read = self._latest(lambda read: bool(read.review.strip()))
        return read.review if read else ""


class Read(Base):
    """
    One time a user read a book of their library (an entry), or means to:
    where they are with it (status), the day it was started and the day it was
    finished, the language it was read in, their rating and what they thought
    of it, each empty when not known. An entry read twice has two, each with
    its own.
    """
    __tablename__ = "library_reads"
    __table_args__ = (
        CheckConstraint(f"rating IS NULL OR (rating >= {RATING_MIN} AND rating <= {RATING_MAX})", name="ck_read_rating_range"),
        ForeignKeyConstraint(
            ["owner_id", "work_id"], ["library_entries.owner_id", "library_entries.work_id"],
            ondelete="CASCADE", name="fk_library_reads_entry",
        ),
        Index("ix_library_reads_entry", "owner_id", "work_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False)
    work_id: Mapped[int] = mapped_column(Integer, nullable=False)
    read_on: Mapped[datetime.date | None] = mapped_column(nullable=True)
    locale: Mapped[str | None] = mapped_column(ForeignKey("locales.code"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="done", server_default="done")
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_on: Mapped[datetime.date | None] = mapped_column(nullable=True)
    review: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    entry: Mapped[UserWork] = relationship(back_populates="reads")


class Cover(Base):
    """
    A cover of a library entry after its first (library_entries.image_id): a
    book read in two editions has the cover of each.
    """
    __tablename__ = "library_covers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "work_id"], ["library_entries.owner_id", "library_entries.work_id"],
            ondelete="CASCADE", name="fk_library_covers_entry",
        ),
        Index("ix_library_covers_entry", "owner_id", "work_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False)
    work_id: Mapped[int] = mapped_column(Integer, nullable=False)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), nullable=False)


class Owning(Base):
    """
    A language the user owns a book of their library in: one who has it in
    Hebrew and in English has two.
    """
    __tablename__ = "library_ownings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "work_id"], ["library_entries.owner_id", "library_entries.work_id"],
            ondelete="CASCADE", name="fk_library_ownings_entry",
        ),
        UniqueConstraint("owner_id", "work_id", "locale", name="uq_library_owning_locale"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False)
    work_id: Mapped[int] = mapped_column(Integer, nullable=False)
    locale: Mapped[str] = mapped_column(ForeignKey("locales.code"), nullable=False)


# ─── concerts, museums, people ───────────────────────────────────────────────

# a library entry's authors: the user's people who wrote it, one row each
library_entry_authors = Table(
    "library_entry_authors",
    Base.metadata,
    Column("owner_id", Integer, primary_key=True),
    Column("work_id", Integer, primary_key=True),
    Column("person_id", ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
    ForeignKeyConstraint(
        ["owner_id", "work_id"], ["library_entries.owner_id", "library_entries.work_id"],
        ondelete="CASCADE", name="fk_library_entry_authors_entry",
    ),
)

concert_companions = Table(
    "concert_companions",
    Base.metadata,
    Column("concert_id", ForeignKey("concert_visits.id", ondelete="CASCADE"), primary_key=True),
    Column("person_id", ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
)

# who the user went with, on one visit (of any type: a museum visit, ...)
visit_companions = Table(
    "visit_companions",
    Base.metadata,
    Column("visit_id", ForeignKey("visits.id", ondelete="CASCADE"), primary_key=True),
    Column("person_id", ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
)

# the kinds of a place (a museum, a concert venue, ...): any number of them
# the currencies a country uses (a country may use several, a currency be of several countries)
country_currencies = Table(
    "country_currencies",
    Base.metadata,
    Column("country_id", ForeignKey("countries.id", ondelete="CASCADE"), primary_key=True),
    Column("currency_id", ForeignKey("currencies.id", ondelete="CASCADE"), primary_key=True),
)

# the official languages of a country (locales, by code)
country_languages = Table(
    "country_languages",
    Base.metadata,
    Column("country_id", ForeignKey("countries.id", ondelete="CASCADE"), primary_key=True),
    Column("locale_code", ForeignKey("locales.code", ondelete="CASCADE"), primary_key=True),
)

place_kind_links = Table(
    "place_kind_links",
    Base.metadata,
    Column("place_id", ForeignKey("places.id", ondelete="CASCADE"), primary_key=True),
    Column("kind_id", ForeignKey("place_kinds.id", ondelete="CASCADE"), primary_key=True),
)

# who was on stage, as people (with: concert_companions is who the user went with)
concert_performers = Table(
    "concert_performers",
    Base.metadata,
    Column("concert_id", ForeignKey("concert_visits.id", ondelete="CASCADE"), primary_key=True),
    Column("person_id", ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
)

# the groups (bands) that performed at a concert
concert_groups = Table(
    "concert_groups",
    Base.metadata,
    Column("concert_id", ForeignKey("concert_visits.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
)

# the people a group is made of
group_members = Table(
    "group_members",
    Base.metadata,
    Column("group_id", ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
    Column("person_id", ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
)

# who taught an audio course, as people
audio_course_lecturers = Table(
    "audio_course_lecturers",
    Base.metadata,
    Column("audio_course_id", ForeignKey("audio_courses.id", ondelete="CASCADE"), primary_key=True),
    Column("person_id", ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
)

# who a film was watched with: each one of the user's own people
film_watch_companions = Table(
    "film_watch_companions",
    Base.metadata,
    Column("film_watch_id", ForeignKey("film_watches.id", ondelete="CASCADE", name="fk_film_watch_companions_film_watch_id"), primary_key=True),
    Column("person_id", ForeignKey("people.id", ondelete="CASCADE", name="fk_film_watch_companions_person_id"), primary_key=True),
)

# what a person is to the user: any number of their person types (a neighbor and a friend)
person_type_links = Table(
    "person_type_links",
    Base.metadata,
    Column("person_id", ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
    Column("person_type_id", ForeignKey("person_types.id", ondelete="CASCADE"), primary_key=True),
)



class Image(Base):
    """ A photo, stored in the database itself; several rows may point at one. """
    __tablename__ = "images"
    __table_args__ = (UniqueConstraint("owner_id", "filename", name="uq_image_filename"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class _Credited:
    """ The credit the license of a picture asks for: where it is from, its license and who made it. """
    image_source: Mapped[str] = mapped_column(String(1000), nullable=False, default="", server_default="")
    image_license: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    image_author: Mapped[str] = mapped_column(String(300), nullable=False, default="", server_default="")


class _Pictured(_Credited):
    """ A photo (or a flag) and the credit its license asks for. """
    image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id", ondelete="SET NULL"), nullable=True)


class PersonType(_Pictured, Base):
    """
    A profession: "Programmer", "Book Author", "Performer" (the sidebar's
    Types, Professions). Its photo shows someone at that work
    (scripts/fetch_pictures.py --only professions takes Wikipedia's).
    """
    __tablename__ = "person_types"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_person_type_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    people: Mapped[list[Person]] = relationship(secondary=person_type_links, back_populates="types")


class Person(Base):
    """
    Someone the user knows or saw. Names are not unique: two people may share
    one, and they stay two rows. The honorific ("Dr.", "Sir"), the first name and the surname are one word
    each (a surname of two words is hyphenated, "Di-Meola"); the middle name
    is everything between them and may be several words (see myworld.names).
    Any part may be empty: a person known only by a description ("the guide
    at the Louvre") goes by that description.
    """
    __tablename__ = "people"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # the account owner themselves: the person other people are friends,
    # co-workers or girlfriends of (one per account, made by the import)
    is_self: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    # "Dr.", "Sir": one word, before the first name; usually empty
    honorific: Mapped[str] = mapped_column(String(50), nullable=False, default="", server_default="")
    first_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    middle_name: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    surname: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # family, co-worker, ...: any number of the user's own person types
    types: Mapped[list[PersonType]] = relationship(secondary=person_type_links, back_populates="people")

    # how this person is linked to organizations ("Worked at" Schema); organizations is each of those organizations, once
    organization_links: Mapped[list[PersonOrganization]] = relationship(
        back_populates="person", cascade="all, delete-orphan", order_by=lambda: (PersonOrganization.organization_id, PersonOrganization.relation_type_id),
    )
    organizations: Mapped[list[Organization]] = relationship(secondary=lambda: person_organizations, viewonly=True, order_by=lambda: Organization.name)
    concerts: Mapped[list[Concert]] = relationship(
        secondary=concert_companions, back_populates="people",
    )
    performed: Mapped[list[Concert]] = relationship(
        secondary=concert_performers, back_populates="performers",
    )
    groups: Mapped[list[Group]] = relationship(secondary=group_members, back_populates="members")
    # how this person is related to other people ("Mother of" Dana), and how others are related to them
    relations: Mapped[list[PersonRelation]] = relationship(
        foreign_keys=lambda: PersonRelation.person_id, back_populates="person", cascade="all, delete-orphan", order_by=lambda: PersonRelation.id,
    )
    related: Mapped[list[PersonRelation]] = relationship(
        foreign_keys=lambda: PersonRelation.other_id, back_populates="other", cascade="all, delete-orphan", order_by=lambda: PersonRelation.id,
    )
    # their name in other languages than English, one per language
    names: Mapped[list[PersonName]] = relationship(
        back_populates="person", cascade="all, delete-orphan", order_by=lambda: PersonName.locale,
    )
    # their photos, in order: the first is the default, the one their card shows
    photos: Mapped[list[PersonPhoto]] = relationship(
        cascade="all, delete-orphan", order_by=lambda: (PersonPhoto.position, PersonPhoto.id), lazy="selectin",
    )

    @property
    def name(self) -> str:
        """ The whole name, as shown (the English one); the description for someone with no name. """
        return " ".join(part for part in (self.honorific, self.first_name, self.middle_name, self.surname) if part) or self.description

    def name_in(self, locale: str | None) -> str:
        """ The whole name in locale, when they have one in it; else their English name. """
        for other in self.names:
            if other.locale == locale:
                return other.name
        return self.name
    visits: Mapped[list[Visit]] = relationship(
        secondary=visit_companions, back_populates="people",
    )
    lectured: Mapped[list[AudioCourse]] = relationship(
        secondary=audio_course_lecturers, back_populates="lecturers",
    )
    # the films watched with them, and those they recommended
    film_watches: Mapped[list[FilmWatch]] = relationship(
        secondary=film_watch_companions, back_populates="people",
    )
    recommended: Mapped[list[FilmWatch]] = relationship(back_populates="recommended_by")
    # the library entries (books) they wrote
    wrote: Mapped[list[UserWork]] = relationship(
        secondary=library_entry_authors, back_populates="authors",
    )


class PersonName(Base):
    """
    A person's name in a language other than English: "חיים שפירא" (he) of
    Haim Shapira, in its parts as the English one is (honorific, first name,
    middle name, surname; name is the parts together). One per language; the
    person's own name parts are their English name.
    """
    __tablename__ = "person_names"
    __table_args__ = (UniqueConstraint("person_id", "locale", name="uq_person_name_locale"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), nullable=False, index=True)
    locale: Mapped[str] = mapped_column(ForeignKey("locales.code"), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    honorific: Mapped[str] = mapped_column(String(50), nullable=False, default="", server_default="")
    first_name: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    middle_name: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    surname: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")

    person: Mapped[Person] = relationship(back_populates="names")

    def set_parts(self, honorific: str, first_name: str, middle_name: str, surname: str) -> None:
        """ The name in its parts; name is them together. """
        self.honorific, self.first_name, self.middle_name, self.surname = honorific, first_name, middle_name, surname
        self.name = " ".join(part for part in (honorific, first_name, middle_name, surname) if part)

    def set_whole(self, name: str) -> None:
        """ The name as one text, split into parts: the first word, the last, and what is between (one word is a first name). """
        words = name.split()
        self.set_parts("", words[0] if words else "", " ".join(words[1:-1]), words[-1] if len(words) > 1 else "")


class PersonPhoto(_Credited, Base):
    """ A photo of a person, with the credit its license asks for; the first (by position) is their default one, which their card shows. """
    __tablename__ = "person_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), nullable=False, index=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class OrganizationType(Base):
    """
    What an organization is: company, university, ... An enumeration the
    user keeps themselves (the sidebar's Types, Org), so new values need no code.
    """
    __tablename__ = "organization_types"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_organization_type_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    organizations: Mapped[list[Organization]] = relationship(back_populates="type")


organization_relation_types = Table(
    "organization_relation_types",
    Base.metadata,
    Column("organization_id", ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
    Column("relation_type_id", ForeignKey("relation_types.id", ondelete="CASCADE"), primary_key=True),
)


class PersonRelationType(Base):
    """
    How one person is related to another: "Mother of", "Brother of", "Wife
    of". An enumeration the user keeps themselves (the Person relations
    page). The inverse is how it reads from the other person's side ("Child
    of"); empty when it reads the same both ways ("Friend of").
    """
    __tablename__ = "person_relation_types"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_person_relation_type_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    inverse: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    @property
    def inverse_name(self) -> str:
        """ How the relation reads from the other side. """
        return self.inverse or self.name


class PersonOrganizationType(Base):
    """
    How a person is linked to an organization: "Worked at", "Studied at",
    "Founded". An enumeration the user keeps themselves (the Person-org
    relations page).
    """
    __tablename__ = "person_organization_types"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_person_organization_type_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")


class PersonOrganization(Base):
    """ One link of a person to an organization: person is relation_type organization ("Dana" "Worked at" "Schema"). """
    # the same two may be linked by several kinds ("Studied at", then "Worked at")
    __tablename__ = "person_organizations"

    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    relation_type_id: Mapped[int] = mapped_column(ForeignKey("person_organization_types.id", ondelete="CASCADE"), primary_key=True)
    person: Mapped[Person] = relationship(back_populates="organization_links")
    organization: Mapped[Organization] = relationship(back_populates="person_links")
    relation_type: Mapped[PersonOrganizationType] = relationship()


# the link table itself, for queries and deletes that need no objects
person_organizations = cast(Table, PersonOrganization.__table__)


class PersonRelation(Base):
    """ One person's relation to another: person is relation_type of other ("Ruth" is "Mother of" "Dana"). """
    __tablename__ = "person_relations"
    __table_args__ = (UniqueConstraint("person_id", "relation_type_id", "other_id", name="uq_person_relation"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), nullable=False, index=True)
    relation_type_id: Mapped[int] = mapped_column(ForeignKey("person_relation_types.id", ondelete="CASCADE"), nullable=False, index=True)
    other_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), nullable=False, index=True)

    person: Mapped[Person] = relationship(foreign_keys=[person_id], back_populates="relations")
    relation_type: Mapped[PersonRelationType] = relationship()
    other: Mapped[Person] = relationship(foreign_keys=[other_id], back_populates="related")


class RelationType(Base):
    """
    How an organization is related to the user: taught there, consulted,
    studied there, ... An enumeration the user keeps themselves (the
    Relation types page); an organization has any number of them.
    """
    __tablename__ = "relation_types"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_relation_type_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    organizations: Mapped[list[Organization]] = relationship(secondary=organization_relation_types, back_populates="relations")


class _Located:
    """
    Where it is on a map, in WGS 84 degrees: both or neither. Found from the
    address by scripts/geocode.py, or typed in the dialog.
    """
    latitude: Mapped[float | None] = mapped_column(Double, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Double, nullable=True)


class _Addressed:
    """
    An address in three parts beside the row's city (which carries the
    region and country; see myworld.addresses): the street line in local
    order, the neighbourhood and the postcode; any may be empty.
    """
    street: Mapped[str] = mapped_column(String(300), nullable=False, default="", server_default="")
    neighbourhood: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    postcode: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")

    @property
    def address(self) -> str:
        """ The address in one line: "Ibn Gabirol 30, Sarona, Tel Aviv 6473424, Israel". """
        city = getattr(self, "city", None)
        return compose(self.street, self.neighbourhood, city.name if city else "", self.postcode, city.country.name if city and city.country else "")


class Currency(Base):
    """
    A currency, as ISO 4217 names it: its code ("ILS"), name ("Israeli New
    Shekel"), symbol ("₪") and how many digits it has after the point.
    Countries point to the ones they use. Shared, kept by admins (SHARED);
    the Locale importer brings them all.
    """
    __tablename__ = "currencies"
    __table_args__ = (UniqueConstraint("code", name="uq_currency_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(3), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    digits: Mapped[int | None] = mapped_column(Integer, nullable=True)

    countries: Mapped[list[Country]] = relationship(secondary=country_currencies, back_populates="currencies")


class Country(_Pictured, _Located, Base):
    """
    A country; cities point to the one they are in. A name is a country
    once, and so is a code: its ISO 3166 code ("IL"), by which the Locale
    importer knows it again whatever it is called here. Shared: the same
    for every account, kept by admins (SHARED).
    """
    __tablename__ = "countries"
    __table_args__ = (UniqueConstraint("name", name="uq_country_name"), UniqueConstraint("code", name="uq_country_code"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # ISO 3166-1 alpha-2 ("IL") and alpha-3 ("ISR"); None and "" for a country no code is known for
    code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    code3: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")

    cities: Mapped[list[City]] = relationship(back_populates="country")
    currencies: Mapped[list[Currency]] = relationship(secondary=country_currencies, back_populates="countries", order_by=lambda: Currency.code)
    languages: Mapped[list[Locale]] = relationship(secondary=country_languages, order_by=lambda: Locale.position)


class Region(Base):
    """
    A region of a country: a state, a province, a district ("California",
    "Ontario", "Tel Aviv District"). The cities in it point to it; it is a
    name once in a country, made when a city first says it and gone with
    the last city that does. Shared, as cities are.
    """
    __tablename__ = "regions"
    __table_args__ = (UniqueConstraint("name", "country_id", name="uq_region_name"), UniqueConstraint("code", name="uq_region_code"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    country_id: Mapped[int | None] = mapped_column(ForeignKey("countries.id", ondelete="SET NULL"), nullable=True, index=True)
    country: Mapped[Country | None] = relationship()
    # GeoNames' code of it ("IL.05"), by which the Locale importer knows it again; None for one it did not bring
    code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cities: Mapped[list[City]] = relationship(back_populates="region_row")


def region_for(session: Session, name: str, country: Country | None) -> Region | None:
    """ The region of that name in that country, made (and added to the session) when there is none yet; None for no name. """
    name = name.strip()
    if not name:
        return None
    for region in session.scalars(select(Region).where(Region.name == name)):
        if region.country is country:
            return region
    region = Region(name=name, country=country)
    session.add(region)
    return region


class City(_Pictured, _Located, Base):
    """
    A city (or a town, a village, a kibbutz): name, region (a state or
    province, where addresses name one: a row of regions) and the country
    it is in (the Countries page). Places and organizations point to the
    city they are in. A name is a city once in each region of a country.
    Shared: the same for every account, kept by admins (SHARED).
    """
    __tablename__ = "cities"
    __table_args__ = (UniqueConstraint("name", "region_id", "country_id", name="uq_city_name"), UniqueConstraint("geonames_id", name="uq_city_geonames_id"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id", ondelete="SET NULL"), nullable=True, index=True)
    region_row: Mapped[Region | None] = relationship(back_populates="cities")
    country_id: Mapped[int | None] = mapped_column(ForeignKey("countries.id", ondelete="SET NULL"), nullable=True, index=True)
    country: Mapped[Country | None] = relationship(back_populates="cities")
    # how many live there, as GeoNames says; None when not known
    population: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # GeoNames' id of it, by which the Locale importer knows it again; None for one it never matched
    geonames_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    @property
    def region(self) -> str:
        """ The name of its region, "" when it says none. """
        return self.region_row.name if self.region_row is not None else ""

    # its photos after the first (image_id and its credit), in the order they were added
    more_photos: Mapped[list[CityPhoto]] = relationship(cascade="all, delete-orphan", order_by=lambda: CityPhoto.id)  # pylint: disable=used-before-assignment

    places: Mapped[list[Place]] = relationship(back_populates="city")
    organizations: Mapped[list[Organization]] = relationship(back_populates="city", foreign_keys=lambda: Organization.city_id)
    # the organizations whose headquarters are here
    headquarters_of: Mapped[list[Organization]] = relationship(back_populates="headquarters", foreign_keys=lambda: Organization.headquarters_id)


class CityPhoto(_Credited, Base):
    """ A photo of a city after its first (cities.image_id), with the credit its license asks for. """
    __tablename__ = "city_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"), nullable=False, index=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), nullable=False)


class Organization(_Addressed, _Located, Base):
    """
    An organization: one a person works at, or one the user taught at,
    consulted for, studied at, was certified by or bought media from
    (relations, the user's own relation types). Fields that are only kept, never shown or edited one by one
    (old websites, the geo points, where the logo came from, ...), are in
    details, so an import loses nothing.
    """
    __tablename__ = "organizations"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_organization_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # what it is (company, university, ...): one of the user's own organization types
    type_id: Mapped[int | None] = mapped_column(ForeignKey("organization_types.id", ondelete="SET NULL"), nullable=True)
    type: Mapped[OrganizationType | None] = relationship(back_populates="organizations")
    # active, acquired, defunct, ...
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    website: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    # where its headquarters are, as written ("Santa Clara, California, USA (Nvidia)"), and the city that is
    location: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    headquarters_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id", ondelete="SET NULL"), nullable=True, index=True)
    headquarters: Mapped[City | None] = relationship(back_populates="headquarters_of", foreign_keys=[headquarters_id])
    # the city of its address: the office the user knew
    city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id", ondelete="SET NULL"), nullable=True, index=True)
    city: Mapped[City | None] = relationship(back_populates="organizations", foreign_keys=[city_id])
    what_happened: Mapped[str] = mapped_column(Text, nullable=False, default="")
    remark: Mapped[str] = mapped_column(Text, nullable=False, default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id", ondelete="SET NULL"), nullable=True)
    image: Mapped[Image | None] = relationship()

    # the people linked to it, each by a kind ("Worked at"); people is each of those people, once
    person_links: Mapped[list[PersonOrganization]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    people: Mapped[list[Person]] = relationship(secondary=lambda: person_organizations, viewonly=True, order_by=lambda: Person.id)
    relations: Mapped[list[RelationType]] = relationship(secondary=organization_relation_types, back_populates="organizations")


class _Dated:
    """
    When it happened, as precisely as it is known: exactly one of the date_*
    columns is set. date_utcz is a full timestamp in UTC, date_ymd a day,
    date_my a month ("MM-YYYY"), date_y a year. date_timezone is where it was.
    """
    date_utcz: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    date_ymd: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    date_my: Mapped[str] = mapped_column(String(7), nullable=False, default="")
    date_y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date_timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="")


class PlaceKind(Base):
    """
    What a place is: "Museum", "Concert venue", ... A place is of any
    number of them. Shared, kept by admins (SHARED).
    """
    __tablename__ = "place_kinds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    places: Mapped[list[Place]] = relationship(secondary=place_kind_links, back_populates="kinds")


# the kinds of place and the types of visit there always are: the Museum visits page lists the visits of
# MUSEUM_VISIT, each to a place of MUSEUM_KIND; a concert's place is of CONCERT_VENUE_KIND
MUSEUM_KIND = "Museum"
CONCERT_VENUE_KIND = "Concert venue"
MUSEUM_VISIT = "Museum visit"
SEED_PLACE_KINDS = (MUSEUM_KIND, CONCERT_VENUE_KIND)
SEED_VISIT_TYPES = (MUSEUM_VISIT,)


@event.listens_for(PlaceKind.__table__, "after_create")
def _fill_place_kinds(target: Table, connection: Connection, **_: Any) -> None:
    connection.execute(insert(target), [{"name": name} for name in SEED_PLACE_KINDS])


class Place(_Pictured, _Addressed, _Located, Base):
    """
    A place: a museum, a hall, a club, a park ("Tmuna Theater", in the city
    Tel Aviv), of its kinds (place_kinds). A concert points to the place it
    was at, and a visit to the place visited. The same name may be a place
    in two cities, but only once in each. It may have a photo, with its
    credit. Shared: the same for every account, kept by admins (SHARED);
    what a user thinks of it is in their visits.
    """
    __tablename__ = "places"
    __table_args__ = (UniqueConstraint("name", "city_id", name="uq_place_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    # the city it is in (the Cities page)
    city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id", ondelete="SET NULL"), nullable=True, index=True)
    city: Mapped[City | None] = relationship(back_populates="places")
    website: Mapped[str] = mapped_column(String(1000), nullable=False, default="")

    kinds: Mapped[list[PlaceKind]] = relationship(secondary=place_kind_links, back_populates="places", order_by=lambda: PlaceKind.name)
    concerts: Mapped[list[Concert]] = relationship(back_populates="place")
    visits: Mapped[list[Visit]] = relationship(back_populates="place")


class VisitType(Base):
    """
    What a visit was: "Museum visit", ... more with time. Shared, kept by
    admins (SHARED).
    """
    __tablename__ = "visit_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    visits: Mapped[list[Visit]] = relationship(back_populates="type")


@event.listens_for(VisitType.__table__, "after_create")
def _fill_visit_types(target: Table, connection: Connection, **_: Any) -> None:
    connection.execute(insert(target), [{"name": name} for name in SEED_VISIT_TYPES])


class Visit(_Dated, Base):
    """
    A user's visit to a place, of a type (a museum visit, ...): when, what
    they thought of it, and who they went with. The user's own, of a place
    that is everyone's.
    """
    __tablename__ = "visits"
    __table_args__ = (
        CheckConstraint(f"rating IS NULL OR (rating >= {RATING_MIN} AND rating <= {RATING_MAX})", name="ck_visit_rating_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # the place visited (the Places page); a place an admin deleted leaves its visits with none
    place_id: Mapped[int | None] = mapped_column(ForeignKey("places.id", ondelete="SET NULL"), nullable=True, index=True)
    place: Mapped[Place | None] = relationship(back_populates="visits")
    type_id: Mapped[int] = mapped_column(ForeignKey("visit_types.id", ondelete="RESTRICT"), nullable=False, index=True)
    type: Mapped[VisitType] = relationship(back_populates="visits")
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review: Mapped[str] = mapped_column(Text, nullable=False, default="")
    remark: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tickets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # went alone: no one is missing from people, there was no one; never true with people
    alone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    people: Mapped[list[Person]] = relationship(secondary=visit_companions, back_populates="visits")


class Concert(_Pictured, _Dated, Base):
    __tablename__ = "concert_visits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    event: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    genre: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    # where it was (the Places page); none when not known
    place_id: Mapped[int | None] = mapped_column(ForeignKey("places.id", ondelete="SET NULL"), nullable=True, index=True)
    place: Mapped[Place | None] = relationship(back_populates="concerts")
    tickets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # seen on TV rather than in the hall
    broadcast: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # went alone: no one is missing from people, there was no one; never true with people
    alone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    review: Mapped[str] = mapped_column(Text, nullable=False, default="")
    remark: Mapped[str] = mapped_column(Text, nullable=False, default="")
    image: Mapped[Image | None] = relationship()

    # who the user went with
    people: Mapped[list[Person]] = relationship(secondary=concert_companions, back_populates="concerts")
    # who was on stage
    performers: Mapped[list[Person]] = relationship(secondary=concert_performers, back_populates="performed")
    # the groups that performed, each a collection of people
    groups: Mapped[list[Group]] = relationship(secondary=concert_groups, back_populates="concerts")


class Group(_Pictured, Base):
    """
    A group of people known by its own name: a band ("Pink Floyd"), a trio,
    a choir. Its members are the user's people; a concert points to the
    groups that performed at it.
    """
    __tablename__ = "groups"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_group_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    website: Mapped[str] = mapped_column(String(1000), nullable=False, default="")

    members: Mapped[list[Person]] = relationship(secondary=group_members, back_populates="groups", order_by=lambda: Person.id)
    concerts: Mapped[list[Concert]] = relationship(secondary=concert_groups, back_populates="groups")


class Device(_Pictured, Base):
    """
    What something was played on: "Samsung S10", "Sansa Clip 2", "Desktop".
    An enumeration the user keeps themselves (the Devices page); an audio
    course, an audio book, a podcast episode or a YouTube video points to one. Its photo is the device's own
    (scripts/fetch_pictures.py --only devices takes Wikipedia's).
    """
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_device_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    audio_courses: Mapped[list[AudioCourse]] = relationship(back_populates="device")
    audio_book_listens: Mapped[list[AudioBookListen]] = relationship(back_populates="device")
    youtube_videos: Mapped[list[YouTubeVideo]] = relationship(back_populates="device")
    episodes_heard: Mapped[list[EpisodeHeard]] = relationship(back_populates="device")
    film_watches: Mapped[list[FilmWatch]] = relationship(back_populates="device")


class AudioCourse(_Dated, Base):
    """
    An audio course listened to (The Great Courses, Audible, ...). The date
    (_Dated) is when it was finished; one still in progress has none, only
    started_utcz and progress. Imported from veltzer.github.io's
    audio_courses.yaml, which it keeps field for field.
    """
    __tablename__ = "audio_courses"
    __table_args__ = (
        CheckConstraint(f"rating IS NULL OR (rating >= {RATING_MIN} AND rating <= {RATING_MAX})", name="ck_audio_course_rating_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # what it was played on: one of the user's own devices
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    device: Mapped[Device | None] = relationship(back_populates="audio_courses")
    # where it was listened to ("Night Walks", "Car")
    listened_at: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    # still in progress: when it was started, and how far it got ("4/24" lectures)
    started_utcz: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    ended_utcz: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    progress: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    # where it is sold: The Great Courses (id and URL slug) or Audible (ASIN)
    great_courses_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    great_courses_slug: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    audible_asin: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    # any other page about the course, for one that is no longer sold
    link: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id", ondelete="SET NULL"), nullable=True)
    image: Mapped[Image | None] = relationship()

    lecturers: Mapped[list[Person]] = relationship(secondary=audio_course_lecturers, back_populates="lectured")


# what an audio book version is -> its name: a book in the user's Audible
# library (found again there by its ASIN), or MP3 files
AUDIO_BOOK_KINDS: dict[str, str] = {
    "audible": "Audible",
    "mp3": "MP3",
}


class AudioBook(Base):
    """
    An audio book: its title, subtitle, authors and series. Shared:
    the same for every account, kept by admins (SHARED). It comes in versions
    (AudioBookVersion: an Audible one, MP3 files, ...), each with what is
    its own; what a user thinks of the book is their AudioBookHeard, and each
    version they heard is their AudioBookListen. A book is in My World once
    by its title, subtitle and authors.
    """
    __tablename__ = "audio_books"
    __table_args__ = (UniqueConstraint("name", "subtitle", "authors", name="uq_audio_book_identity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # the title
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # as the source writes them: "Sam Harris, David Chalmers"
    authors: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    series: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # its place in the series: "2", "0.5"
    series_sequence: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    # the book in catalogs (the Audio book ids importer fills them from Open
    # Library): its Open Library work ("OL27482W"), a Goodreads book of it, its
    # Wikidata item ("Q190192")
    openlibrary_id: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    goodreads_id: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    wikidata_id: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    versions: Mapped[list[AudioBookVersion]] = relationship(back_populates="book", cascade="all, delete-orphan", order_by="AudioBookVersion.id")
    heard: Mapped[list[AudioBookHeard]] = relationship(back_populates="book")


class AudioBookVersion(Base):
    """
    One version of an audio book (shared, as the book is): the Audible one,
    or MP3 files. Each has its own cover, and says who reads it and how long
    it is; an Audible one
    also what Audible says of it (its ASIN, genres, rating there, when it
    came out, its cover's address), MP3 files how many parts they are. An
    Audible book is in My World once by its ASIN.
    """
    __tablename__ = "audio_book_versions"
    __table_args__ = (
        # NULLs never clash: an MP3 version has no ASIN
        UniqueConstraint("asin", name="uq_audio_book_version_asin"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("audio_books.id", ondelete="CASCADE", name="fk_audio_book_versions_book_id"), nullable=False, index=True)
    book: Mapped[AudioBook] = relationship(back_populates="versions")
    # one of AUDIO_BOOK_KINDS
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # as the source writes them: "Jordan Bridges"
    narrators: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Audible's: the book's id there, and what it says of it
    asin: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # as Audible lists them: each genre's path from its top genre down, one
    # after another, so a top genre comes again for each path
    genres: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # its rating at Audible (of 5) and by how many
    source_rating: Mapped[float | None] = mapped_column(Double, nullable=True)
    source_ratings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    released: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    # the address of its cover at Audible (the cover itself is image)
    cover_url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    # MP3's: how many files (parts, discs) it comes in
    parts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # its cover: an Audible one's is Audible's, MP3 files' a print edition's
    image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id", ondelete="SET NULL", name="fk_audio_book_versions_image_id"), nullable=True)
    image: Mapped[Image | None] = relationship()
    listens: Mapped[list[AudioBookListen]] = relationship(back_populates="version")


class AudioBookHeard(Base):
    """
    An audio book (a shared one) the user heard, and what they think of it:
    their rating and review. The user's own; the versions of it they heard
    are their AudioBookListen rows. A book is in a user's once.
    """
    __tablename__ = "audio_books_heard"
    __table_args__ = (
        UniqueConstraint("owner_id", "book_id", name="uq_audio_book_heard"),
        CheckConstraint(f"rating IS NULL OR (rating >= {RATING_MIN} AND rating <= {RATING_MAX})", name="ck_audio_book_heard_rating_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # a book someone heard is not deleted (RESTRICT)
    book_id: Mapped[int] = mapped_column(ForeignKey("audio_books.id", ondelete="RESTRICT", name="fk_audio_books_heard_book_id"), nullable=False, index=True)
    book: Mapped[AudioBook] = relationship(back_populates="heard")
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review: Mapped[str] = mapped_column(Text, nullable=False, default="")


class AudioBookListen(_Dated, Base):
    """
    A version of an audio book (a shared one) the user heard: whether they
    finished it and when (the date, _Dated), how much of it they heard
    (Audible says), when they started and how far they got ("did part03"),
    where they heard it and on what device; of an Audible one, when it came
    into their library there and when they bought it. A version is in a
    user's once.
    """
    __tablename__ = "audio_book_listens"
    __table_args__ = (UniqueConstraint("owner_id", "version_id", name="uq_audio_book_listen"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # a version someone heard is not deleted (RESTRICT)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("audio_book_versions.id", ondelete="RESTRICT", name="fk_audio_book_listens_version_id"), nullable=False, index=True,
    )
    version: Mapped[AudioBookVersion] = relationship(back_populates="listens")
    finished: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    # how much of it was heard, 0 to 100, as Audible says
    percent_heard: Mapped[float | None] = mapped_column(Double, nullable=True)
    # not finished: when it was started, and how far it got ("did part03")
    started_utcz: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    progress: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    # where it was heard ("Night Walks"), and on what: one of the user's own devices
    listened_at: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL", name="fk_audio_book_listens_device_id"), nullable=True)
    device: Mapped[Device | None] = relationship(back_populates="audio_book_listens")
    # Audible's: when it came into the user's library there, and when they bought it
    added_utcz: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    purchased_utcz: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)


class Podcast(Base):
    """
    A podcast: its name, its page, its RSS feed and its cover. Shared: the
    same for every account, kept by admins (SHARED), its episodes brought
    from its feed by the Podcast feeds importer (an admin's). What a user
    thinks of it is their PodcastHeard; a podcast someone heard is not
    deleted.
    """
    __tablename__ = "podcasts"
    __table_args__ = (UniqueConstraint("name", name="uq_podcast_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    # its page ("https://therestishistory.com/club"), and its feed, which says its episodes
    url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    rss_feed: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id", ondelete="SET NULL"), nullable=True)
    image: Mapped[Image | None] = relationship()
    episodes: Mapped[list[PodcastEpisode]] = relationship(back_populates="podcast", cascade="all, delete-orphan", passive_deletes=True)
    heard: Mapped[list[PodcastHeard]] = relationship(back_populates="podcast", passive_deletes=True)


class PodcastEpisode(Base):
    """
    An episode of a podcast, every field as its feed gives it (title,
    description, when published, its number, length, type, explicit, the
    audio's and the image's addresses, author, guid). Shared, kept by admins
    (SHARED): who heard it, when, where and what they thought is their
    EpisodeHeard. An episode is in a podcast once, by its feed's guid.
    """
    __tablename__ = "podcast_episodes"
    __table_args__ = (
        # an episode typed in by hand may have no guid (NULLs never clash)
        UniqueConstraint("podcast_id", "guid", name="uq_podcast_episode_guid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    podcast_id: Mapped[int] = mapped_column(ForeignKey("podcasts.id", ondelete="CASCADE", name="fk_podcast_episodes_podcast_id"), nullable=False, index=True)
    podcast: Mapped[Podcast] = relationship(back_populates="episodes")
    # the feed's: title, description, pubDate (in UTC), episode (its number), duration
    # (in seconds), episodeType ("full", "trailer"), explicit ("yes", "no", "false": as
    # the feed says it), the audio (enclosure_url) and the episode's image, author, guid
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    published_utcz: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode_type: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    explicit: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    enclosure_url: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    image_url: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    author: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    guid: Mapped[str | None] = mapped_column(String(500), nullable=True)
    heard: Mapped[list[EpisodeHeard]] = relationship(back_populates="episode", passive_deletes=True)


class PodcastHeard(Base):
    """
    A podcast (a shared one) the user listens to, and what they think of it:
    their rating and review. The user's own; the episodes of it they heard
    are their EpisodeHeard rows. A podcast is in a user's once.
    """
    __tablename__ = "podcasts_heard"
    __table_args__ = (
        UniqueConstraint("owner_id", "podcast_id", name="uq_podcast_heard"),
        CheckConstraint(f"rating IS NULL OR (rating >= {RATING_MIN} AND rating <= {RATING_MAX})", name="ck_podcast_heard_rating_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # a podcast someone heard is not deleted (RESTRICT)
    podcast_id: Mapped[int] = mapped_column(ForeignKey("podcasts.id", ondelete="RESTRICT", name="fk_podcasts_heard_podcast_id"), nullable=False, index=True)
    podcast: Mapped[Podcast] = relationship(back_populates="heard")
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review: Mapped[str] = mapped_column(Text, nullable=False, default="")


class EpisodeHeard(_Dated, Base):
    """
    An episode (a shared one) the user heard; the date (_Dated) is when.
    Where it was heard and on what device, as an audio course has them, and
    the user's own rating and review. An episode is in a user's once.
    """
    __tablename__ = "episodes_heard"
    __table_args__ = (
        UniqueConstraint("owner_id", "episode_id", name="uq_episode_heard"),
        CheckConstraint(f"rating IS NULL OR (rating >= {RATING_MIN} AND rating <= {RATING_MAX})", name="ck_episode_heard_rating_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # an episode someone heard is not deleted (RESTRICT)
    episode_id: Mapped[int] = mapped_column(ForeignKey("podcast_episodes.id", ondelete="RESTRICT", name="fk_episodes_heard_episode_id"), nullable=False, index=True)
    episode: Mapped[PodcastEpisode] = relationship(back_populates="heard")
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # where it was heard ("Night Walks"), and on what: one of the user's own devices
    listened_at: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL", name="fk_episodes_heard_device_id"), nullable=True)
    device: Mapped[Device | None] = relationship(back_populates="episodes_heard")


# a YouTube video id: 11 characters of the URL-safe base64 alphabet
YOUTUBE_ID_LENGTH = 11


class YouTubeVideo(_Dated, Base):
    """
    A YouTube video watched; the date (_Dated) is when. Imported from
    veltzer.github.io's video_youtube.yaml (and its watch history), which it
    keeps field for field; My World keeps them now.
    The page and the thumbnail are YouTube's own, found by youtube_id.
    """
    __tablename__ = "youtube_videos"
    __table_args__ = (
        UniqueConstraint("owner_id", "youtube_id", name="uq_youtube_video_id"),
        CheckConstraint(f"rating IS NULL OR (rating >= {RATING_MIN} AND rating <= {RATING_MAX})", name="ck_youtube_video_rating_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    youtube_id: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # what it was watched on: one of the user's own devices
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    device: Mapped[Device | None] = relationship(back_populates="youtube_videos")
    # where it was watched ("Home")
    watched_at: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    # what YouTube says about it (from the watch history): channel, category,
    # length in seconds, the day it was uploaded and how many views it had
    channel: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # YouTube no longer has it (deleted or private): only its id is known
    unavailable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


# what a film is -> its name: a film, or a series (of seasons)
FILM_KINDS: dict[str, str] = {
    "film": "Film",
    "series": "Series",
}

# where the user is with a film watch -> its name: watched, or one they mean to see
FILM_WATCH_STATUSES: dict[str, str] = {
    "done": "Watched",
    "wishlist": "Want to see",
}


class Film(Base):
    """
    A film, or a series (kind, FILM_KINDS): its title, the year it came out
    (a series, the year it started), who directed it, its genres,
    its poster and its ids on IMDb ("tt0816692"), The Movie Database,
    Wikidata ("Q13417189") and Rotten Tomatoes ("m/interstellar_2014").
    Shared: the same for every account, kept by admins (SHARED); each time a
    user watched it, or means to, is their FilmWatch. A film is in My World
    once by its IMDb id.
    """
    __tablename__ = "films"
    __table_args__ = (
        # NULLs never clash: a film typed in without its IMDb id
        UniqueConstraint("imdb_id", name="uq_film_imdb_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # one of FILM_KINDS: the Films page lists the films, the Series page the series
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="film", server_default="film")
    # the title
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # as the source writes them: "Joel Coen, Ethan Coen"
    directors: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    genres: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    imdb_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wikidata_id: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    rotten_tomatoes_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # its poster
    image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id", ondelete="SET NULL", name="fk_films_image_id"), nullable=True)
    image: Mapped[Image | None] = relationship()
    watches: Mapped[list[FilmWatch]] = relationship(back_populates="film")


class FilmWatch(_Dated, Base):
    """
    A time the user watched a film (a shared one), or one they mean to see
    (status): when (the date, _Dated), where, on what (a device or a service:
    "Netflix") and with whom, their rating and what they thought of it, and
    who recommended it to them; of a series, the seasons they saw and those
    they know they did not. A film watched twice has two, each with its own
    rating and review.
    """
    __tablename__ = "film_watches"
    __table_args__ = (
        CheckConstraint(f"rating IS NULL OR (rating >= {RATING_MIN} AND rating <= {RATING_MAX})", name="ck_film_watch_rating_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE", name="fk_film_watches_owner_id"), nullable=False, index=True)
    # a film someone watched is not deleted (RESTRICT)
    film_id: Mapped[int] = mapped_column(ForeignKey("films.id", ondelete="RESTRICT", name="fk_film_watches_film_id"), nullable=False, index=True)
    film: Mapped[Film] = relationship(back_populates="watches")
    # one of FILM_WATCH_STATUSES
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="done", server_default="done")
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # where it was watched ("Home", "Cinemateque, Holon"), and on what: one of the user's own devices
    watched_at: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL", name="fk_film_watches_device_id"), nullable=True)
    device: Mapped[Device | None] = relationship(back_populates="film_watches")
    # who told the user to see it: one of their own people
    recommended_by_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL", name="fk_film_watches_recommended_by_id"), nullable=True)
    recommended_by: Mapped[Person | None] = relationship(back_populates="recommended")
    # a series: the seasons seen ([1, 2, 3]), and those there are that were not ([4, 5])
    seasons_seen: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    seasons_not_seen: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    # who the user watched it with
    people: Mapped[list[Person]] = relationship(secondary=film_watch_companions, back_populates="film_watches")


class ChessGame(_Dated, Base):
    """
    A game of chess the user played; the date (_Dated) is when. Imported by
    scripts/import_chess.py from PGN files, or added by pasting one game's
    PGN. pgn is the game as it was written, tags and moves, so nothing a
    file said is lost; the other columns are what is listed, sorted and
    searched by, read out of it (myworld.pgn). A game is told from every
    other by source_key (its address at the site it was played on, else a
    hash of its players, day and moves), so one imported twice is one.

    A game may be recorded without its moves: only whom the user played and
    how it ended (scripts/import_chess_xml.py, the games played over the
    board). Such a game has no pgn, no plies and no final position, and the
    side the user played may not be known (color ""): then white and black
    are empty, and opponent and outcome are what it says.
    """
    __tablename__ = "chess_games"
    __table_args__ = (
        UniqueConstraint("owner_id", "source_key", name="uq_chess_game_source"),
        CheckConstraint("color IN ('white', 'black', '')", name="ck_chess_game_color"),
        CheckConstraint("result IN ('1-0', '0-1', '1/2-1/2', '*')", name="ck_chess_game_result"),
        CheckConstraint("outcome IN ('won', 'lost', 'drawn', '')", name="ck_chess_game_outcome"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    source_key: Mapped[str] = mapped_column(String(100), nullable=False)
    # the side the user played; "" where it is not known
    color: Mapped[str] = mapped_column(String(5), nullable=False)
    # whom the user played, and how it ended for them ("won", "lost", "drawn"; "" where not known):
    # for a game with both sides, read out of them (myworld.pgn); for one without, as it was recorded
    opponent: Mapped[str] = mapped_column(String(300), nullable=False, default="", server_default="")
    outcome: Mapped[str] = mapped_column(String(5), nullable=False, default="", server_default="")
    # the players, by the names they went by where it was played, and their ratings then
    white: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    black: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    white_elo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    black_elo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # "1-0" (White won), "0-1", "1/2-1/2", or "*" for a game with no result
    result: Mapped[str] = mapped_column(String(7), nullable=False, default="*")
    # how it ended, in the words of where it was played ("veltzer resigns", "nfloz84 won on time")
    termination: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    time_control: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    eco: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    opening: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    event: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    site: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    # its page at the site it was played on, when it has one
    link: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # how many moves were made, counting each side's
    plies: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # where the pieces stood when it ended (the first field of a FEN): the picture of its card
    final_position: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    remark: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # read only when one game is opened: the list never needs it
    pgn: Mapped[str] = mapped_column(Text, nullable=False, deferred=True)


class YouTubeConnection(Base):
    """
    The user's YouTube account, connected from the Imports page so its
    importers can read it (myworld.youtube): Google's refresh token for the
    youtube.readonly scope, encrypted with a key derived from SECRET_KEY (a
    new SECRET_KEY makes it unreadable, and the user connects again), and
    the name of the channel it is, to show which account is connected.
    """
    __tablename__ = "youtube_connections"

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    connected_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class AudibleConnection(Base):
    """
    The user's Audible account, connected from the Imports page so its
    importer can read the library (myworld.audible): My World is a device of
    the account, and this is what it signs with (the ADP token and the
    device's private key) and the refresh token kept to deregister it, each
    encrypted with a key derived from SECRET_KEY (a new SECRET_KEY makes
    them unreadable, and the user connects again); the Audible store, and
    the account's name, to show which account is connected.
    """
    __tablename__ = "audible_connections"

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    marketplace: Mapped[str] = mapped_column(String(10), nullable=False, default="us")
    adp_token: Mapped[str] = mapped_column(Text, nullable=False)
    private_key: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    connected_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


# queued: waiting for its job to start (on Cloud Run, a Cloud Run Jobs execution);
# running: its job is at it; done, failed: it ended
IMPORT_STATUSES = ("queued", "running", "done", "failed")
IMPORT_ENDED = ("done", "failed")


class ImportRun(Base):
    """
    One run of an importer (myworld.importers) by a user: which one, with
    what parameters, whether it was a dry run (done and rolled back), where
    it is (queued, running) or how it ended, what it counted ({"YouTube
    videos added": 3, ...}) and what it said, written as it goes. A run is
    done by a job of its own (myworld.importers.worker), which says it is
    alive (heartbeat_at) while it runs. The Imports page lists a user's runs.
    """
    __tablename__ = "import_runs"
    __table_args__ = (
        CheckConstraint(f"status IN ({', '.join(repr(s) for s in IMPORT_STATUSES)})", name="ck_import_run_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    importer: Mapped[str] = mapped_column(String(100), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    counts: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False, default=dict)
    log: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # when it was asked for (queued), when its job last said it is alive, when it ended
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    heartbeat_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    # the Cloud Run Jobs execution doing it ("projects/.../executions/..."), "" when run in the app itself
    execution: Mapped[str] = mapped_column(String(300), nullable=False, default="", server_default="")


class ImportUsage(Base):
    """
    How many import runs a user started in a calendar month (UTC), whatever
    became of them: what the month's limit is counted against. Kept apart
    from the runs, so deleting runs (the Imports page's Clear) gives back
    none of the month's runs.
    """
    __tablename__ = "import_usage"

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # the first day of the month
    month: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# a view's name, the last part of its address (/view/<username>/<name>)
VIEW_NAME_MAX = 60
VIEW_NAME_PATTERN = rf"[a-z0-9][a-z0-9._-]{{0,{VIEW_NAME_MAX - 1}}}"
VIEW_ACCESS_PUBLIC = "public"
VIEW_ACCESSES = (VIEW_ACCESS_PUBLIC,)


class SharedView(Base):
    """
    A view: a named selection of a user's own data sets that anyone may open
    at /view/<username>/<name>, read only (doc/views.md).
    """
    __tablename__ = "shared_views"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_shared_view_owner_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(VIEW_NAME_MAX), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # the data sets it shows: library kinds ("book") and views ("concerts"), as the page names them
    datasets: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # who may open it: "public" (anyone with the address); private views are still to come
    access: Mapped[str] = mapped_column(String(20), nullable=False, default=VIEW_ACCESS_PUBLIC, server_default=VIEW_ACCESS_PUBLIC)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    owner: Mapped[User] = relationship()


def database_url() -> str:
    """
    Where the data lives.

    On Cloud Run the deploy script sets INSTANCE_CONNECTION_NAME and the
    Cloud SQL proxy exposes the instance as a unix socket under /cloudsql.
    Anywhere else DATABASE_URL wins, defaulting to a local sqlite file in the
    git-ignored db.gi/ directory.
    """
    instance = os.environ.get("INSTANCE_CONNECTION_NAME")
    if instance:
        user = os.environ["DB_USER"]
        password = os.environ["DB_PASS"]
        name = os.environ["DB_NAME"]
        socket = f"/cloudsql/{instance}/.s.PGSQL.5432"
        return f"postgresql+pg8000://{user}:{password}@/{name}?unix_sock={socket}"
    return os.environ.get("DATABASE_URL", "sqlite:///db.gi/myworld.sqlite")


def make_engine(url: str | None = None) -> Engine:
    url = url or database_url()
    if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
        os.makedirs(os.path.dirname(url.removeprefix("sqlite:///")) or ".", exist_ok=True)
    engine = create_engine(url, pool_pre_ping=True)
    prepare_schema(engine)
    seed_locales(engine)
    return engine


# The migration (scripts/migrations/versions/) these models are at: a database made
# from them is marked as being there, so scripts/migrate.sh has nothing to do to it.
# A change to the tables is a new migration, and its number goes here.
SCHEMA_REVISION = "0032"


def prepare_schema(engine: Engine) -> None:
    """
    An empty database gets every table, and is marked as being at
    SCHEMA_REVISION. One the migrations keep (it has alembic_version) is
    left alone: only scripts/migrate.sh changes it. One from before the
    migrations kept count gets the tables it lacks, as it always did.
    """
    tables = set(inspect(engine).get_table_names())
    if "alembic_version" in tables:
        return
    Base.metadata.create_all(engine)
    if not tables:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"))
            connection.execute(text("INSERT INTO alembic_version (version_num) VALUES (:revision)"), {"revision": SCHEMA_REVISION})


def seed_locales(engine: Engine) -> None:
    """ A locales table that was there already gets the languages of SEED_LOCALES it lacks; the others are left as they are. """
    with Session(engine) as session:
        have = set(session.scalars(select(Locale.code)))
        session.add_all(
            Locale(code=code, name=name, script=script, position=position, native=LOCALE_NATIVE.get(code, ""))
            for position, (code, name, script) in enumerate(SEED_LOCALES)
            if code not in have
        )
        session.commit()
