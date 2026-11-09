"""
Database schema.

Works (books, films, ...) are shared rows; what a user thinks about a work
(status, rating, dates, notes) lives in the per-user UserWork join row.
Adding a new kind of work is a matter of adding it to KINDS.

Concerts, museum visits, the people they were shared with and the
organizations those people work at are a second, separate part: each row
belongs to one user (owner_id) and is never shared. A person may be linked
to several organizations (person_organizations).
Their photos live in the images table, so the database alone holds all of it.
They are loaded by scripts/import_world.py.
"""

import datetime
import os
from typing import Any

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
    Integer,
    LargeBinary,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    false,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# kind -> (display name, plural, what the "creator" column is called for that kind)
KINDS: dict[str, tuple[str, str, str]] = {
    "book": ("Book", "Books", "Author"),
    "film": ("Film", "Films", "Director"),
    "series": ("Video series", "Video series", "Creator"),
    "album": ("Album", "Albums", "Artist"),
    "game": ("Game", "Games", "Studio"),
}

STATUSES: dict[str, str] = {
    "wishlist": "Want to",
    "in_progress": "In progress",
    "done": "Done",
    "abandoned": "Abandoned",
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
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # The stable identity the user signed in with, qualified by how they did
    # it: a bare Google "sub" claim for Google (the original and still the
    # main method), "github:<id>", "email:<address>" or
    # "dev:<address>" for the others. Kept under its historical column name;
    # emails can change so they are never the key for third-party sign-in.
    google_sub: Mapped[str] = mapped_column(String(400), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    picture: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    # only for accounts created with "sign in with email"; werkzeug hash
    password_hash: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # what the account may do on the site, one of ROLES: an admin can also see
    # every account and change its role (the Users page) and run checks over
    # the whole database. The first admin is made by scripts/migrate.sh.
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=ROLE_USER, server_default=ROLE_USER)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    works: Mapped[list[UserWork]] = relationship(  # pylint: disable=used-before-assignment
        back_populates="user", cascade="all, delete-orphan",
    )

    @property
    def provider(self) -> str:
        """ How the account signs in: google, github, email or dev, from its subject. """
        prefix, colon, _ = self.google_sub.partition(":")
        return prefix if colon else "google"

    @property
    def provider_id(self) -> str:
        """ Who the provider says the account is: the Google sub, the GitHub user id, the email address. """
        prefix, colon, rest = self.google_sub.partition(":")
        return rest if colon else prefix


class Work(Base):
    __tablename__ = "works"
    __table_args__ = (
        UniqueConstraint("kind", "title", "creator", "year", name="uq_work_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    creator: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # ISBN and the like, for future enrichment from public catalogs
    external_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    # films: filled from The Movie Database when the work is added through the search (see movies.py)
    imdb_id: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rotten_tomatoes_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    users: Mapped[list[UserWork]] = relationship(back_populates="work")  # pylint: disable=used-before-assignment


class UserWork(Base):
    __tablename__ = "user_works"
    __table_args__ = (
        CheckConstraint(f"rating IS NULL OR (rating >= {RATING_MIN} AND rating <= {RATING_MAX})", name="ck_rating_range"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="done")
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_on: Mapped[datetime.date | None] = mapped_column(nullable=True)
    finished_on: Mapped[datetime.date | None] = mapped_column(nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="works")
    work: Mapped[Work] = relationship(back_populates="users", lazy="joined")


# ─── concerts, museums, people ───────────────────────────────────────────────

concert_people = Table(
    "concert_people",
    Base.metadata,
    Column("concert_id", ForeignKey("concerts.id", ondelete="CASCADE"), primary_key=True),
    Column("person_id", ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
)

museum_people = Table(
    "museum_people",
    Base.metadata,
    Column("museum_id", ForeignKey("museums.id", ondelete="CASCADE"), primary_key=True),
    Column("person_id", ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
)

# who was on stage, as people (with: concert_people is who the user went with)
concert_performers = Table(
    "concert_performers",
    Base.metadata,
    Column("concert_id", ForeignKey("concerts.id", ondelete="CASCADE"), primary_key=True),
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
person_person_types = Table(
    "person_person_types",
    Base.metadata,
    Column("person_id", ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
    Column("type_id", ForeignKey("person_types.id", ondelete="CASCADE"), primary_key=True),
)

person_organizations = Table(
    "person_organizations",
    Base.metadata,
    Column("person_id", ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
    Column("organization_id", ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
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


class PersonType(Base):
    """ What a person is to the user: family, co-worker, ... (the sidebar's Types, Person). """
    __tablename__ = "person_types"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_person_type_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    people: Mapped[list[Person]] = relationship(secondary=person_person_types, back_populates="types")


class Person(Base):
    """
    Someone the user knows or saw. Names are not unique: two people may share
    one, and they stay two rows. A name that is not a first name and a
    surname (a band, "Oded from MAFAT") is all in first_name. Either part,
    or both, may be empty: a person known only by a description ("the
    guide at the Louvre") goes by that description.
    """
    __tablename__ = "people"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    first_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    surname: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # family, co-worker, ...: any number of the user's own person types
    types: Mapped[list[PersonType]] = relationship(secondary=person_person_types, back_populates="people")

    organizations: Mapped[list[Organization]] = relationship(
        secondary=person_organizations, back_populates="people",
    )
    concerts: Mapped[list[Concert]] = relationship(
        secondary=concert_people, back_populates="people",
    )
    performed: Mapped[list[Concert]] = relationship(
        secondary=concert_performers, back_populates="performers",
    )

    @property
    def name(self) -> str:
        """ The whole name, as shown; the description for someone with no name. """
        return f"{self.first_name} {self.surname}".strip() or self.description
    museums: Mapped[list[Museum]] = relationship(
        secondary=museum_people, back_populates="people",
    )
    lectured: Mapped[list[AudioCourse]] = relationship(
        secondary=audio_course_lecturers, back_populates="lecturers",
    )


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


class Organization(_Located, Base):
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
    location: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    address: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    what_happened: Mapped[str] = mapped_column(Text, nullable=False, default="")
    remark: Mapped[str] = mapped_column(Text, nullable=False, default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id", ondelete="SET NULL"), nullable=True)
    image: Mapped[Image | None] = relationship()

    people: Mapped[list[Person]] = relationship(secondary=person_organizations, back_populates="organizations")
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


class Concert(_Dated, Base):
    __tablename__ = "concerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    event: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    genre: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    venue: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    city: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    country: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    tickets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # seen on TV rather than in the hall
    broadcast: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review: Mapped[str] = mapped_column(Text, nullable=False, default="")
    remark: Mapped[str] = mapped_column(Text, nullable=False, default="")
    image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id", ondelete="SET NULL"), nullable=True)
    image: Mapped[Image | None] = relationship()
    # the credit the image license asks for
    image_source: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    image_license: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    image_author: Mapped[str] = mapped_column(String(300), nullable=False, default="")

    # who the user went with
    people: Mapped[list[Person]] = relationship(secondary=concert_people, back_populates="concerts")
    # who was on stage
    performers: Mapped[list[Person]] = relationship(secondary=concert_performers, back_populates="performed")


class Museum(_Dated, _Located, Base):
    """ One visit to a museum; a museum visited twice is two rows. """
    __tablename__ = "museums"
    __table_args__ = (
        CheckConstraint(f"rating IS NULL OR (rating >= {RATING_MIN} AND rating <= {RATING_MAX})", name="ck_museum_rating_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    # the street address of the museum, as for an organization
    address: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review: Mapped[str] = mapped_column(Text, nullable=False, default="")
    remark: Mapped[str] = mapped_column(Text, nullable=False, default="")
    url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    tickets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # went alone: no one is missing from people, there was no one; never true with people
    alone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id", ondelete="SET NULL"), nullable=True)
    image: Mapped[Image | None] = relationship()

    people: Mapped[list[Person]] = relationship(secondary=museum_people, back_populates="museums")


class Device(Base):
    """
    What something was played on: "Samsung S10", "Sansa Clip 2", "Desktop".
    An enumeration the user keeps themselves (the Devices page); an audio
    course or a YouTube video points to one.
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
    Base.metadata.create_all(engine)
    return engine
