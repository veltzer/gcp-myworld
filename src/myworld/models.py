"""
Database schema.

Works (books, films, ...) are rows of the account that has them, as
everything is: nothing is shared between accounts. What a user thinks about a
work (status, rating, dates, notes) lives in its UserWork row, apart from what
the work is, so that works can be shared later.
Adding a new kind of work is a matter of adding it to KINDS.

Concerts, museum visits, the people they were shared with and the
organizations those people work at are a second, separate part: each row
belongs to one user (owner_id) and is never shared. A person may be linked
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


ROLE_USER = "user"
ROLE_ADMIN = "admin"
ROLES = (ROLE_USER, ROLE_ADMIN)


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

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # proven to be this person's by the provider of the login that made the account
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    picture: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    # what the account may do on the site, one of ROLES: an admin can also see
    # every account and change its role (the Users page) and run checks over
    # the whole database. The first admin is made by scripts/migrate.sh.
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=ROLE_USER, server_default=ROLE_USER)
    # the language they prefer (Settings): a book with titles in several languages is
    # shown by its title in this one, and its authors by their names in it
    locale: Mapped[str] = mapped_column(ForeignKey("locales.code"), nullable=False, default=DEFAULT_LOCALE, server_default=DEFAULT_LOCALE)
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

# who the user went to a museum with, on one visit (museum_id is the visit's id: the column keeps its old name)
museum_companions = Table(
    "museum_companions",
    Base.metadata,
    Column("museum_id", ForeignKey("museum_visits.id", ondelete="CASCADE"), primary_key=True),
    Column("person_id", ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
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
    museum_visits: Mapped[list[MuseumVisit]] = relationship(
        secondary=museum_companions, back_populates="people",
    )
    lectured: Mapped[list[AudioCourse]] = relationship(
        secondary=audio_course_lecturers, back_populates="lecturers",
    )
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


class Country(_Pictured, _Located, Base):
    """ A country; cities point to the one they are in. A name is a country once. """
    __tablename__ = "countries"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_country_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    remark: Mapped[str] = mapped_column(Text, nullable=False, default="")

    cities: Mapped[list[City]] = relationship(back_populates="country")


class Region(Base):
    """
    A region of a country: a state, a province, a district ("California",
    "Ontario", "Tel Aviv District"). The cities in it point to it; it is a
    name once in a country, made when a city first says it and gone with
    the last city that does.
    """
    __tablename__ = "regions"
    __table_args__ = (UniqueConstraint("owner_id", "name", "country_id", name="uq_region_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    country_id: Mapped[int | None] = mapped_column(ForeignKey("countries.id", ondelete="SET NULL"), nullable=True, index=True)
    country: Mapped[Country | None] = relationship()
    cities: Mapped[list[City]] = relationship(back_populates="region_row")


def region_for(session: Session, owner_id: int, name: str, country: Country | None) -> Region | None:
    """ The owner's region of that name in that country, made (and added to the session) when there is none yet; None for no name. """
    name = name.strip()
    if not name:
        return None
    for region in session.scalars(select(Region).where(Region.owner_id == owner_id, Region.name == name)):
        if region.country is country:
            return region
    region = Region(owner_id=owner_id, name=name, country=country)
    session.add(region)
    return region


class City(_Pictured, _Located, Base):
    """
    A city (or a town, a village, a kibbutz): name, region (a state or
    province, where addresses name one: a row of regions) and the country
    it is in (the Countries page). Places, museum visits and organizations
    point to the city they are in. A name is a city once in each region of
    a country.
    """
    __tablename__ = "cities"
    __table_args__ = (UniqueConstraint("owner_id", "name", "region_id", "country_id", name="uq_city_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id", ondelete="SET NULL"), nullable=True, index=True)
    region_row: Mapped[Region | None] = relationship(back_populates="cities")
    country_id: Mapped[int | None] = mapped_column(ForeignKey("countries.id", ondelete="SET NULL"), nullable=True, index=True)
    country: Mapped[Country | None] = relationship(back_populates="cities")

    @property
    def region(self) -> str:
        """ The name of its region, "" when it says none. """
        return self.region_row.name if self.region_row is not None else ""
    remark: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # its photos after the first (image_id and its credit), in the order they were added
    more_photos: Mapped[list[CityPhoto]] = relationship(cascade="all, delete-orphan", order_by=lambda: CityPhoto.id)  # pylint: disable=used-before-assignment

    places: Mapped[list[Place]] = relationship(back_populates="city")
    museums: Mapped[list[Museum]] = relationship(back_populates="city")
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


class Place(_Pictured, _Addressed, Base):
    """
    Where something happened: a hall, a club, a park ("Tmuna Theater", in
    the city Tel Aviv). A concert points to the place it was at. The same
    name may be a place in two cities, but only once in each. It may have
    a photo, with its credit.
    """
    __tablename__ = "places"
    __table_args__ = (UniqueConstraint("owner_id", "name", "city_id", name="uq_place_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    # the city it is in (the Cities page)
    city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id", ondelete="SET NULL"), nullable=True, index=True)
    city: Mapped[City | None] = relationship(back_populates="places")
    latitude: Mapped[float | None] = mapped_column(Double, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Double, nullable=True)
    website: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    remark: Mapped[str] = mapped_column(Text, nullable=False, default="")

    concerts: Mapped[list[Concert]] = relationship(back_populates="place")


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


class Museum(_Addressed, _Located, Base):
    """
    A museum: its name, where it is, its website and its photo. A name is a
    museum once in each city. The times the user went there are its visits
    (museum_visits), any number of them, none for one not visited yet.
    """
    __tablename__ = "museum_sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    # the city it is in (the Cities page)
    city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id", ondelete="SET NULL"), nullable=True, index=True)
    city: Mapped[City | None] = relationship(back_populates="museums")
    url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id", ondelete="SET NULL"), nullable=True)
    image: Mapped[Image | None] = relationship()

    # in the order they were added
    visits: Mapped[list[MuseumVisit]] = relationship(
        back_populates="museum", cascade="all, delete-orphan", order_by=lambda: MuseumVisit.id,  # pylint: disable=used-before-assignment
    )


class MuseumVisit(_Dated, Base):
    """ One visit to a museum: when, what the user thought of it, and who they went with. """
    __tablename__ = "museum_visits"
    __table_args__ = (
        CheckConstraint(f"rating IS NULL OR (rating >= {RATING_MIN} AND rating <= {RATING_MAX})", name="ck_museum_rating_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    museum_id: Mapped[int] = mapped_column(ForeignKey("museum_sites.id", ondelete="CASCADE"), nullable=False, index=True)
    museum: Mapped[Museum] = relationship(back_populates="visits")
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review: Mapped[str] = mapped_column(Text, nullable=False, default="")
    remark: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tickets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # went alone: no one is missing from people, there was no one; never true with people
    alone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    people: Mapped[list[Person]] = relationship(secondary=museum_companions, back_populates="museum_visits")


class Device(_Pictured, Base):
    """
    What something was played on: "Samsung S10", "Sansa Clip 2", "Desktop".
    An enumeration the user keeps themselves (the Devices page); an audio
    course or a YouTube video points to one. Its photo is the device's own
    (scripts/fetch_pictures.py --only devices takes Wikipedia's).
    """
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_device_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    audio_courses: Mapped[list[AudioCourse]] = relationship(back_populates="device")
    youtube_videos: Mapped[list[YouTubeVideo]] = relationship(back_populates="device")


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


# a YouTube video id: 11 characters of the URL-safe base64 alphabet
YOUTUBE_ID_LENGTH = 11


class YouTubeVideo(_Dated, Base):
    """
    A YouTube video watched; the date (_Dated) is when. Imported from
    veltzer.github.io's video_youtube.yaml, which it keeps field for field.
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


class ChessGame(_Dated, Base):
    """
    A game of chess the user played; the date (_Dated) is when. Imported by
    scripts/import_chess.py from PGN files, or added by pasting one game's
    PGN. pgn is the game as it was written, tags and moves, so nothing a
    file said is lost; the other columns are what is listed, sorted and
    searched by, read out of it (myworld.pgn). A game is told from every
    other by source_key (its address at the site it was played on, else a
    hash of its players, day and moves), so one imported twice is one.
    """
    __tablename__ = "chess_games"
    __table_args__ = (
        UniqueConstraint("owner_id", "source_key", name="uq_chess_game_source"),
        CheckConstraint("color IN ('white', 'black')", name="ck_chess_game_color"),
        CheckConstraint("result IN ('1-0', '0-1', '1/2-1/2', '*')", name="ck_chess_game_result"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    source_key: Mapped[str] = mapped_column(String(100), nullable=False)
    # the side the user played
    color: Mapped[str] = mapped_column(String(5), nullable=False)
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
SCHEMA_REVISION = "0006"


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
