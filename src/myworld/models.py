"""
Database schema.

Works (books, films, ...) are shared rows; what a user thinks about a work
(status, rating, dates, notes) lives in the per-user UserWork join row.
Adding a new kind of work is a matter of adding it to KINDS.

Concerts, museum visits, the people they were shared with and the companies
those people work at are a second, separate part: each row belongs to one
user (owner_id) and is never shared. A person may be linked to several
companies (person_companies).
Their photos live in the images table, so the database alone holds all of it.
They are loaded by scripts/import_world.py.
"""

import datetime
import os
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# kind -> (display name, plural, what the "creator" column is called for that kind)
KINDS: dict[str, tuple[str, str, str]] = {
    "book": ("Book", "Books", "Author"),
    "film": ("Film", "Films", "Director"),
    "series": ("Series", "Series", "Creator"),
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
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    works: Mapped[list[UserWork]] = relationship(  # pylint: disable=used-before-assignment
        back_populates="user", cascade="all, delete-orphan",
    )


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

person_companies = Table(
    "person_companies",
    Base.metadata,
    Column("person_id", ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
    Column("company_id", ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True),
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


class Person(Base):
    __tablename__ = "people"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_person_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    companies: Mapped[list[Company]] = relationship(
        secondary=person_companies, back_populates="people",
    )
    concerts: Mapped[list[Concert]] = relationship(
        secondary=concert_people, back_populates="people",
    )
    museums: Mapped[list[Museum]] = relationship(
        secondary=museum_people, back_populates="people",
    )


class Company(Base):
    """
    An organization: one a person works at, or one the user taught at,
    consulted for, studied at, was certified by or bought media from
    (functions). Fields that are only kept, never shown or edited one by one
    (old websites, the geo points, where the logo came from, ...), are in
    details, so an import loses nothing.
    """
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_company_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    functions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
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

    people: Mapped[list[Person]] = relationship(secondary=person_companies, back_populates="companies")


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
    # free text names of who was on stage
    performers: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
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

    people: Mapped[list[Person]] = relationship(secondary=concert_people, back_populates="concerts")


class Museum(_Dated, Base):
    """ One visit to a museum; a museum visited twice is two rows. """
    __tablename__ = "museums"
    __table_args__ = (
        CheckConstraint(f"rating IS NULL OR (rating >= {RATING_MIN} AND rating <= {RATING_MAX})", name="ck_museum_rating_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review: Mapped[str] = mapped_column(Text, nullable=False, default="")
    remark: Mapped[str] = mapped_column(Text, nullable=False, default="")
    url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    tickets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id", ondelete="SET NULL"), nullable=True)
    image: Mapped[Image | None] = relationship()

    people: Mapped[list[Person]] = relationship(secondary=museum_people, back_populates="museums")


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
