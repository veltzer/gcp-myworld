"""
The Stats page: how many of everything the signed-in user has, and a few breakdowns.
"""

import collections
from typing import Any

import flask
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from myworld import auth
from myworld.models import (
    KINDS,
    MUSEUM_VISIT,
    STATUSES,
    AudioBook,
    AudioBookListen,
    AudioBookVersion,
    AudioCourse,
    Certification,
    ChessGame,
    City,
    Concert,
    Country,
    Course,
    Currency,
    Device,
    EpisodeHeard,
    Film,
    FilmWatch,
    Group,
    Image,
    Lecture,
    Loan,
    Locale,
    Organization,
    OrganizationType,
    Person,
    PersonOrganizationType,
    PersonRelationType,
    PersonType,
    Place,
    PlaceKind,
    Podcast,
    PodcastEpisode,
    Rally,
    RelationType,
    Trip,
    UserWork,
    Visit,
    VisitType,
    Website,
    YouTubeVideo,
    concert_performers,
    is_shared,
)
from myworld.world import date_json

bp = flask.Blueprint("stats", __name__)


def _per_year(rows: Any) -> list[dict[str, int]]:
    """ How many rows fall in each year that has any, oldest first; undated rows are left out. """
    years: dict[int, int] = {}
    for row in rows:
        key = date_json(row)["date_sort"][:4]
        if key:
            years[int(key)] = years.get(int(key), 0) + 1
    return [{"year": year, "count": years[year]} for year in sorted(years)]


def _by_type(counts: dict[str, int]) -> list[dict[str, Any]]:
    return [{"name": name, "count": count} for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


# the YouTube channels on the Stats page: the ones watched most
TOP_CHANNELS = 15


def _youtube_by(column: Any, limit: int | None = None) -> list[dict[str, Any]]:
    """ The user's YouTube videos counted by column (channel, category), most first; those without one are left out. """
    rows = flask.g.db.execute(
        select(column, func.count()).where(YouTubeVideo.owner_id == flask.g.user.id, column != "")
        .group_by(column).order_by(func.count().desc(), column).limit(limit),
    ).all()
    return [{"name": name, "count": count} for name, count in rows]


# how a game ended for the one who played it, as the page says it
CHESS_OUTCOMES = {"won": "Won", "lost": "Lost", "drawn": "Drawn", "": "No result"}


def _chess_by_outcome() -> list[dict[str, Any]]:
    """ The user's games counted by how they ended for them: won, lost, drawn, or with no result. """
    rows = flask.g.db.execute(
        select(ChessGame.outcome, func.count()).where(ChessGame.owner_id == flask.g.user.id).group_by(ChessGame.outcome),
    ).all()
    return _by_type({CHESS_OUTCOMES[outcome]: count for outcome, count in rows})


@bp.route("/api/stats", methods=["GET"])
@auth.login_required
def api_stats() -> flask.Response:
    """ How many of everything the user has, and a few breakdowns. """
    db = flask.g.db
    me = flask.g.user.id

    def count(model: Any) -> int:
        """ The user's rows of model; every row of a shared one (everyone's). """
        query = select(func.count()).select_from(model)
        return db.scalar(query if is_shared(model) else query.where(model.owner_id == me)) or 0

    library = []
    # where the user is with each: the status of the reading it goes by
    entries = db.scalars(select(UserWork).where(UserWork.owner_id == me)).all()
    for kind, (_, plural, _) in KINDS.items():
        counts = collections.Counter(entry.status for entry in entries if entry.work.kind == kind)
        by_status = {label: counts[status] for status, label in STATUSES.items() if counts[status]}
        library.append({"kind": kind, "label": plural, "total": sum(by_status.values()), "by_status": by_status})
    concerts = db.execute(select(Concert).where(Concert.owner_id == me)).scalars().all()
    visits = db.execute(
        select(Visit).join(VisitType).where(Visit.owner_id == me, VisitType.name == MUSEUM_VISIT)
    ).scalars().all()
    museums = {visit.place_id for visit in visits if visit.place_id is not None}
    people = db.execute(select(Person).where(Person.owner_id == me).options(selectinload(Person.types))).scalars().all()
    organizations = db.execute(
        select(Organization).where(Organization.owner_id == me).options(selectinload(Organization.types), selectinload(Organization.relations))
    ).scalars().all()
    people_by_type: dict[str, int] = {}
    for person in people:
        for kind in person.types or [None]:
            name = kind.name if kind else "No profession"
            people_by_type[name] = people_by_type.get(name, 0) + 1
    organizations_by_relation: dict[str, int] = {}
    for organization in organizations:
        for relation in organization.relations or [None]:
            name = relation.name if relation else "No relation"
            organizations_by_relation[name] = organizations_by_relation.get(name, 0) + 1
    organizations_by_type: dict[str, int] = {}
    for organization in organizations:
        for kind in organization.types or [None]:
            name = kind.name if kind else "No type"
            organizations_by_type[name] = organizations_by_type.get(name, 0) + 1
    performers = db.scalar(
        select(func.count(func.distinct(concert_performers.c.person_id)))
        .join(Concert, Concert.id == concert_performers.c.concert_id)
        .where(Concert.owner_id == me)
    ) or 0
    # only when each was played: 60,000 games are counted by year without being read
    chess_dates = db.execute(
        select(ChessGame.date_utcz, ChessGame.date_ymd, ChessGame.date_my, ChessGame.date_y).where(ChessGame.owner_id == me),
    ).all()
    return flask.jsonify({
        "library": library,
        "concerts": len(concerts),
        "performers": performers,
        "museum_visits": len(visits),
        "museums": len(museums),
        "audio_courses": count(AudioCourse),
        # Your audio books: those the user heard a version of; and the shared ones
        "audio_books_heard": db.scalar(select(func.count(func.distinct(AudioBookVersion.book_id))).join(AudioBookListen).where(AudioBookListen.owner_id == me)) or 0,
        "audio_book_listens": count(AudioBookListen),
        "audio_books": count(AudioBook),
        "audio_book_versions": count(AudioBookVersion),
        "podcasts": count(Podcast),
        "podcast_episodes": count(PodcastEpisode),
        # Your podcasts: those the user heard an episode of
        "podcasts_heard": db.scalar(select(func.count(func.distinct(PodcastEpisode.podcast_id))).join(EpisodeHeard).where(EpisodeHeard.owner_id == me)) or 0,
        "episodes_heard": count(EpisodeHeard),
        # the films and the series (a film of another kind); those the user watched (each once, however many
        # times), and every watch of them, those still to see too
        **{plural: db.scalar(select(func.count()).select_from(Film).where(Film.kind == kind)) or 0 for kind, plural in (("film", "films"), ("series", "series"))},
        **{f"{plural}_watched": db.scalar(
            select(func.count(func.distinct(FilmWatch.film_id))).join(Film).where(FilmWatch.owner_id == me, FilmWatch.status == "done", Film.kind == kind),
        ) or 0 for kind, plural in (("film", "films"), ("series", "series"))},
        **{f"{kind}_watches": db.scalar(
            select(func.count()).select_from(FilmWatch).join(Film).where(FilmWatch.owner_id == me, Film.kind == kind),
        ) or 0 for kind in ("film", "series")},
        "youtube_videos": count(YouTubeVideo),
        "chess_games": len(chess_dates),
        "certifications": count(Certification),
        "courses": count(Course),
        "trips": count(Trip),
        "lectures": count(Lecture),
        "rallies": count(Rally),
        "loans": count(Loan),
        "websites": count(Website),
        "people": len(people),
        "organizations": len(organizations),
        "places": count(Place),
        "place_kinds": count(PlaceKind),
        "visit_types": count(VisitType),
        "cities": count(City),
        "countries": count(Country),
        "currencies": count(Currency),
        "groups": count(Group),
        "organization_types": count(OrganizationType),
        "person_types": count(PersonType),
        "relation_types": count(RelationType),
        "person_relation_types": count(PersonRelationType),
        "person_organization_types": count(PersonOrganizationType),
        "devices": count(Device),
        "locales": db.scalar(select(func.count()).select_from(Locale)) or 0,
        "images": count(Image),
        "people_by_type": _by_type(people_by_type),
        "organizations_by_type": _by_type(organizations_by_type),
        "organizations_by_relation": _by_type(organizations_by_relation),
        "concerts_by_year": _per_year(list(concerts)),
        "museums_by_year": _per_year(visits),
        "youtube_by_channel": _youtube_by(YouTubeVideo.channel, TOP_CHANNELS),
        "youtube_by_category": _youtube_by(YouTubeVideo.category),
        "chess_by_outcome": _chess_by_outcome(),
        "chess_by_year": _per_year(chess_dates),
    })
