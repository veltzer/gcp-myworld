"""
Database schema.

Works (books, films, ...) are shared rows; what a user thinks about a work
(status, rating, dates, notes) lives in the per-user UserWork join row.
Adding a new kind of work is a matter of adding it to KINDS.
"""

import datetime
import os

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
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
