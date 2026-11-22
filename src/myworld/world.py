"""
JSON API for what the signed-in user keeps: concerts, their museum visits,
audio courses, audio books, podcasts and their episodes, YouTube videos, chess games, people, organizations and
groups; and for what everyone shares: places (and their kinds), visit
types, cities and countries. For each: what a row looks like as JSON, how a
request body is applied to it, and the routes that list, add, edit and
delete it. A user's rows are filtered by owner_id, so a user only ever
sees, and only ever links to, their own rows and the shared ones; a shared
row is changed by admins only, and says nothing personal (what a user
thinks of a place is in their visits).
"""

import dataclasses
import datetime
import re
import zoneinfo
from collections.abc import Callable
from typing import Any

import flask
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from myworld import auth, languages, names, pgn
from myworld.api import (
    ApiError,
    coordinates,
    json_body,
    opt_int,
    owned,
    owned_list,
    owned_ref,
    require_edit_shared,
    text,
)
from myworld.models import (
    AUDIO_BOOK_KINDS,
    DEFAULT_LOCALE,
    FILM_KINDS,
    FILM_WATCH_STATUSES,
    MUSEUM_KIND,
    MUSEUM_VISIT,
    RATING_MAX,
    RATING_MIN,
    YOUTUBE_ID_LENGTH,
    AudioBook,
    AudioBookHeard,
    AudioBookListen,
    AudioBookVersion,
    AudioCourse,
    ChessGame,
    City,
    CityPhoto,
    Concert,
    Country,
    Currency,
    Device,
    EpisodeHeard,
    Film,
    FilmWatch,
    Group,
    Organization,
    OrganizationType,
    Person,
    PersonName,
    PersonOrganization,
    PersonOrganizationType,
    PersonPhoto,
    PersonRelation,
    PersonRelationType,
    PersonType,
    Place,
    PlaceKind,
    Podcast,
    PodcastEpisode,
    PodcastHeard,
    Region,
    RelationType,
    Visit,
    VisitType,
    YouTubeVideo,
    is_shared,
    region_for,
)
from myworld.pictures import (
    apply_image,
    apply_picture,
    drop_unused_images,
    image_url,
    photo_json,
    photo_rows,
    picture_json,
    sent_photos,
)

bp = flask.Blueprint("world", __name__)


def date_json(row: Any) -> dict[str, Any]:
    """ The date as precisely as it is known, and a sortable key for it. """
    if row.date_utcz is not None:
        utc = row.date_utcz.replace(tzinfo=datetime.UTC)
        return {"date": utc.isoformat().replace("+00:00", "Z"), "date_precision": "time", "date_sort": utc.date().isoformat()}
    if row.date_ymd is not None:
        return {"date": row.date_ymd.isoformat(), "date_precision": "day", "date_sort": row.date_ymd.isoformat()}
    if row.date_my:
        month, year = row.date_my.split("-")
        return {"date": f"{year}-{month}", "date_precision": "month", "date_sort": f"{year}-{month}"}
    if row.date_y is not None:
        return {"date": str(row.date_y), "date_precision": "year", "date_sort": f"{row.date_y:04d}"}
    return {"date": None, "date_precision": None, "date_sort": ""}




def shown_name(person: Person) -> str:
    """ What a person is called to the signed-in account: their name in the language it prefers (Settings) when they have one in it, else their English name. """
    return person.name_in(flask.g.user.locale)


def _name(row: Any) -> str:
    """ What a row is called: a person as shown_name says, anything else by its name. """
    name: str = shown_name(row) if isinstance(row, Person) else row.name
    return name


def _names(people: list[Person]) -> list[str]:
    return sorted(shown_name(p) for p in people)


def _refs(rows: list[Person] | list[Organization] | list[PersonType] | list[OrganizationType] | list[RelationType] | list[Group] | list[Concert] | list[Place] | list[City] | list[PlaceKind] | list[Country]) -> list[dict[str, Any]]:
    """ Names with the ids the People and Organizations views link to, each row once (a person may be linked to one organization twice). """
    unique = {row.id: row for row in rows}.values()
    return sorted(({"id": row.id, "name": _name(row)} for row in unique), key=lambda ref: ref["name"])


def concert_json(concert: Concert) -> dict[str, Any]:
    return {
        "id": concert.id,
        "name": concert.name,
        "performers": _refs(concert.performers),
        # the groups (bands) that performed
        "groups": _refs(concert.groups),
        "event": concert.event,
        "genre": concert.genre,
        **date_json(concert),
        "date_timezone": concert.date_timezone,
        # where it was, a row of the Places page
        "place": None if concert.place is None else _place_ref(concert.place),
        "tickets": concert.tickets,
        "broadcast": concert.broadcast,
        "alone": concert.alone,
        "review": concert.review,
        "remark": concert.remark,
        "with": _names(concert.people),
        "people": _refs(concert.people),
        **picture_json(concert),
    }


def country_ref(country: Country | None) -> dict[str, Any] | None:
    return None if country is None else {"id": country.id, "name": country.name}


def city_ref(city: City | None) -> dict[str, Any] | None:
    """ A city as other rows show it: its id, name, region and country; None for no city. """
    return None if city is None else {"id": city.id, "name": city.name, "region": city.region, "country": country_ref(city.country)}




def currency_ref(currency: Currency) -> dict[str, Any]:
    return {"id": currency.id, "name": currency.name or currency.code, "code": currency.code}


def currency_json(currency: Currency) -> dict[str, Any]:
    return {
        **currency_ref(currency),
        "symbol": currency.symbol,
        "digits": currency.digits,
        "countries": _refs(currency.countries),
    }


def country_json(country: Country) -> dict[str, Any]:
    return {
        "id": country.id,
        "name": country.name,
        "code": country.code or "",
        "code3": country.code3,
        "currencies": [currency_ref(currency) for currency in country.currencies],
        # its official languages, by name (the Languages page's rows are by their place in the list)
        "languages": [{"id": locale.position, "name": locale.name} for locale in country.languages],
        **picture_json(country),
        "latitude": country.latitude,
        "longitude": country.longitude,
        "cities": _refs(country.cities),
    }


def _mine[R](rows: list[R]) -> list[R]:
    """ Of a shared row's rows (a city's organizations, a place's concerts), the signed-in user's own. """
    return [row for row in rows if getattr(row, "owner_id", None) == flask.g.user.id]


def _of_kind(places: list[Place], kind: str) -> list[Place]:
    return [place for place in places if any(k.name == kind for k in place.kinds)]


def _address_parts(row: Place | Organization) -> dict[str, str]:
    return {"street": row.street, "neighbourhood": row.neighbourhood, "postcode": row.postcode}


def _apply_address(row: Place | Organization, body: dict[str, Any]) -> None:
    row.street = text(body, "street")
    row.neighbourhood = text(body, "neighbourhood")
    row.postcode = text(body, "postcode")


def _place_ref(place: Place) -> dict[str, Any]:
    return {"id": place.id, "name": place.name, "city": city_ref(place.city)}


def city_json(city: City) -> dict[str, Any]:
    return {
        **(city_ref(city) or {}),
        "population": city.population,
        # the photo its card shows, and all of its photos (that one first), each with its credit
        **picture_json(city),
        "photos": [photo_json(photo) for photo in ([city] if city.image_id is not None else []) + city.more_photos],
        "latitude": city.latitude,
        "longitude": city.longitude,
        "places": _refs(city.places),
        "museums": _refs(_of_kind(city.places, MUSEUM_KIND)),
        # the user's own organizations there: another account's are theirs
        "organizations": _refs(_mine(city.organizations)),
        "headquarters_of": _refs(_mine(city.headquarters_of)),
    }


def place_json(place: Place) -> dict[str, Any]:
    # the user's concerts that were there, newest first, and how many times they visited it
    concerts = _newest_first([{"id": c.id, "name": c.name, **date_json(c)} for c in _mine(place.concerts)])
    return {
        **_place_ref(place),
        # the address in one line, and its parts (the city carries region and country)
        "address": place.address,
        **_address_parts(place),
        "latitude": place.latitude,
        "longitude": place.longitude,
        "website": place.website,
        "kinds": _refs(place.kinds),
        **picture_json(place),
        "concerts": [{"id": c["id"], "name": c["name"]} for c in concerts],
        "visits": len(_mine(place.visits)),
    }


def group_json(group: Group) -> dict[str, Any]:
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "website": group.website,
        **picture_json(group),
        "members": _refs(group.members),
        # the concerts it performed at, newest first
        "concerts": [{"id": c["id"], "name": c["name"]} for c in _newest_first([{"id": c.id, "name": c.name, **date_json(c)} for c in group.concerts])],
    }


def _visit_json(visit: Visit) -> dict[str, Any]:
    return {
        "id": visit.id,
        **date_json(visit),
        "date_timezone": visit.date_timezone,
        "rating": visit.rating,
        "review": visit.review,
        "remark": visit.remark,
        "tickets": visit.tickets,
        "alone": visit.alone,
        "with": _names(visit.people),
        "people": _refs(visit.people),
    }


def museum_json(museum: Place, mine: list[Visit]) -> dict[str, Any]:
    """ A museum (a shared place) with the signed-in user's visits to it, as their Museum visits page shows it: its id is the place's. """
    # the visits, the latest first (one with no date last)
    visits = sorted((_visit_json(visit) for visit in mine), key=lambda visit: (visit["date_sort"], visit["id"]), reverse=True)
    rated = [visit["rating"] for visit in visits if visit["rating"] is not None]
    people = {person.id: person for visit in mine for person in visit.people}
    return {
        "id": museum.id,
        "name": museum.name,
        # the shared place it is: what the dialog's museum picker shows
        "place": _place_ref(museum),
        "city": city_ref(museum.city),
        # the address in one line, and its parts (the city carries region and country)
        "address": museum.address,
        **_address_parts(museum),
        "latitude": museum.latitude,
        "longitude": museum.longitude,
        "url": museum.website,
        "image": image_url(museum.image_id),
        "visits": visits,
        # what its card, the sorting and the filters go by: when it was last visited, the rating
        # it was last given, and everyone the user ever went there with
        "date": visits[0]["date"] if visits else None,
        "date_precision": visits[0]["date_precision"] if visits else None,
        "date_sort": visits[0]["date_sort"] if visits else "",
        "rating": rated[0] if rated else None,
        "people": _refs(sorted(people.values(), key=lambda person: person.name)),
    }


def _stamp_json(stamp: datetime.datetime | None) -> str:
    return "" if stamp is None else stamp.replace(tzinfo=datetime.UTC).isoformat().replace("+00:00", "Z")


def audio_course_json(course: AudioCourse) -> dict[str, Any]:
    return {
        "id": course.id,
        "name": course.name,
        **date_json(course),
        "date_timezone": course.date_timezone,
        # finished when it has a date, in progress when it was only started
        "status": "done" if date_json(course)["date"] else ("in_progress" if course.started_utcz else ""),
        "lecturers": _refs(course.lecturers),
        "rating": course.rating,
        "review": course.review,
        "device": None if course.device is None else {"id": course.device.id, "name": course.device.name},
        "listened_at": course.listened_at,
        "started": _stamp_json(course.started_utcz),
        "ended": _stamp_json(course.ended_utcz),
        "progress": course.progress,
        "great_courses_id": course.great_courses_id,
        "great_courses_slug": course.great_courses_slug,
        "audible_asin": course.audible_asin,
        "link": course.link,
        "url": _course_url(course),
        "image": image_url(course.image_id),
    }


def _course_url(course: AudioCourse) -> str:
    """ The course's page: where it is sold (The Great Courses, Audible), or else any page about it. """
    if course.great_courses_slug:
        return f"https://www.thegreatcourses.com/courses/{course.great_courses_slug}"
    if course.audible_asin:
        return f"https://www.audible.com/pd/{course.audible_asin}"
    return course.link


def audio_book_json(book: AudioBook) -> dict[str, Any]:
    """ An audio book, shared: the same for everyone, with its versions (what a user heard of it is in Your audio books). """
    return {
        "id": book.id,
        "name": book.name,
        "subtitle": book.subtitle,
        "authors": book.authors,
        "series": book.series,
        "series_sequence": book.series_sequence,
        "openlibrary_id": book.openlibrary_id,
        "goodreads_id": book.goodreads_id,
        "wikidata_id": book.wikidata_id,
        "versions": [{"id": v.id, "name": AUDIO_BOOK_KINDS.get(v.kind, v.kind)} for v in book.versions],
        "url": next((_version_url(v) for v in book.versions if _version_url(v)), ""),
        "image": _cover(book.versions),
    }


def _cover(versions: Any) -> str | None:
    """ What a book shows: the cover of the first of versions that has one (each version has its own). """
    return image_url(next((v.image_id for v in versions if v.image_id is not None), None))


# an audio book's ids in catalogs: (field, what a whole one is, an example)
BOOK_IDS = (
    ("openlibrary_id", re.compile(r"OL\d+W"), "OL27482W"),
    ("goodreads_id", re.compile(r"\d{1,12}"), "234225"),
    ("wikidata_id", re.compile(r"Q\d+"), "Q190192"),
)


def _version_url(version: AudioBookVersion) -> str:
    """ The version's page at its source: an Audible one's at Audible. """
    if version.kind == "audible" and version.asin:
        return f"https://www.audible.com/pd/{version.asin}"
    return ""


def version_name(version: AudioBookVersion) -> str:
    """ "Letter to a Christian Nation (MP3)": the book, and which version. """
    return f"{version.book.name} ({AUDIO_BOOK_KINDS.get(version.kind, version.kind)})"


def _version_fields(version: AudioBookVersion) -> dict[str, Any]:
    """ What a version is, as its card and a listen's show it. """
    book = version.book
    return {
        "book": _ref(book),
        "authors": book.authors,
        "subtitle": book.subtitle,
        "kind": version.kind,
        "kind_name": AUDIO_BOOK_KINDS.get(version.kind, version.kind),
        "narrators": version.narrators,
        "minutes": version.minutes,
        "asin": version.asin or "",
        "genres": version.genres,
        "source_rating": version.source_rating,
        "source_ratings": version.source_ratings,
        "released": version.released.isoformat() if version.released else "",
        "cover_url": version.cover_url,
        "parts": version.parts,
        "url": _version_url(version),
        "image": image_url(version.image_id),
    }


def audio_book_version_json(version: AudioBookVersion, mine: AudioBookListen | None = None) -> dict[str, Any]:
    """ A version, shared; the signed-in user's listen of it (mine), when said, or else looked for. """
    if mine is None:
        mine = next((listen for listen in version.listens if listen.owner_id == flask.g.user.id), None)
    return {
        "id": version.id,
        "name": version_name(version),
        **_version_fields(version),
        "listen": None if mine is None else {"id": mine.id, **date_json(mine)},
    }


def _listen_status(listen: AudioBookListen) -> str:
    """ Finished when it says so or has the day it was; in progress when heard some, or started. """
    if listen.finished or date_json(listen)["date"]:
        return "done"
    return "in_progress" if listen.percent_heard or listen.started_utcz else ""


def _listen_sort(listen: AudioBookListen) -> str:
    """ What the sorting goes by: when it was finished, else when it came into the library (one only started goes last). """
    return date_json(listen)["date_sort"] or _stamp_json(listen.added_utcz)


def audio_book_heard_json(row: AudioBookHeard) -> dict[str, Any]:
    """ An audio book the user heard: what they think of it, and the versions of it they heard, each a link to their listen. """
    book = row.book
    listens = sorted((listen for v in book.versions for listen in v.listens if listen.owner_id == row.owner_id), key=_listen_sort, reverse=True)
    statuses = {_listen_status(listen) for listen in listens}
    return {
        "id": row.id,
        "name": book.name,
        "book": _ref(book),
        "subtitle": book.subtitle,
        "authors": book.authors,
        "url": next((_version_url(listen.version) for listen in listens if _version_url(listen.version)), ""),
        # the cover of a version the user heard, the latest first, else of any
        "image": _cover([listen.version for listen in listens]) or _cover(book.versions),
        "rating": row.rating,
        "review": row.review,
        # finished when one of the versions is; in progress when one is
        "status": "done" if "done" in statuses else ("in_progress" if "in_progress" in statuses else ""),
        "listens": [{"id": listen.id, "name": AUDIO_BOOK_KINDS.get(listen.version.kind, listen.version.kind)} for listen in listens],
        "date_sort": _listen_sort(listens[0]) if listens else "",
    }


def audio_book_listen_json(listen: AudioBookListen) -> dict[str, Any]:
    version = listen.version
    return {
        "id": listen.id,
        "name": version.book.name,
        "version": {"id": version.id, "name": version_name(version)},
        **_version_fields(version),
        "finished": listen.finished,
        "status": _listen_status(listen),
        **date_json(listen),
        "date_timezone": listen.date_timezone,
        "started": _stamp_json(listen.started_utcz),
        "progress": listen.progress,
        "listened_at": listen.listened_at,
        "device": _ref(listen.device),
        "percent_heard": listen.percent_heard,
        "added": _stamp_json(listen.added_utcz),
        "purchased": _stamp_json(listen.purchased_utcz),
        "date_sort": _listen_sort(listen),
    }


def _ref(row: Any) -> dict[str, Any] | None:
    return None if row is None else {"id": row.id, "name": row.name}


def podcast_json(podcast: Podcast) -> dict[str, Any]:
    """ A podcast, shared: the same for everyone (what a user heard of it is in Your podcasts). """
    return {
        "id": podcast.id,
        "name": podcast.name,
        "url": podcast.url,
        "rss_feed": podcast.rss_feed,
        "image": image_url(podcast.image_id),
        # its episodes, as its feed has them: how many, the newest's publishing
        "episodes": len(podcast.episodes),
        "published": max((_stamp_json(e.published_utcz) for e in podcast.episodes), default=""),
    }


def _episode_fields(episode: PodcastEpisode) -> dict[str, Any]:
    """ What the feed says of an episode, as an episode's card and a heard one's show it. """
    return {
        "podcast": _ref(episode.podcast),
        "description": episode.description,
        "published": _stamp_json(episode.published_utcz),
        "number": episode.number,
        "duration": episode.duration,
        "episode_type": episode.episode_type,
        "explicit": episode.explicit,
        "enclosure_url": episode.enclosure_url,
        "image_url": episode.image_url,
        "author": episode.author,
        "guid": episode.guid or "",
        # the audio itself, and the podcast's cover
        "url": episode.enclosure_url,
        "image": image_url(episode.podcast.image_id) if episode.podcast else None,
    }


def podcast_episode_json(episode: PodcastEpisode, mine: EpisodeHeard | None = None) -> dict[str, Any]:
    """ An episode, shared; heard, the signed-in user's hearing of it (mine), when said, or else looked for. """
    if mine is None:
        mine = next((heard for heard in episode.heard if heard.owner_id == flask.g.user.id), None)
    return {
        "id": episode.id,
        "name": episode.name,
        **_episode_fields(episode),
        "heard": None if mine is None else {"id": mine.id, **date_json(mine)},
    }


def podcast_heard_json(row: PodcastHeard) -> dict[str, Any]:
    """ A podcast the user listens to: what they think of it, and the episodes of it they heard, the latest first. """
    podcast = row.podcast
    heard = sorted(
        (h for e in podcast.episodes for h in e.heard if h.owner_id == row.owner_id),
        key=lambda h: (date_json(h)["date_sort"], _stamp_json(h.episode.published_utcz)), reverse=True,
    )
    return {
        "id": row.id,
        "name": podcast.name,
        "podcast": _ref(podcast),
        "url": podcast.url,
        "image": image_url(podcast.image_id),
        "rating": row.rating,
        "review": row.review,
        # the episodes heard (each its hearing's id and the episode's name), how long all of them are (seconds), when the last was
        "episodes": [{"id": h.id, "name": h.episode.name} for h in heard],
        "duration": sum(h.episode.duration or 0 for h in heard),
        "date_sort": date_json(heard[0])["date_sort"] if heard else "",
    }


def episode_heard_json(row: EpisodeHeard) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.episode.name,
        "episode": _ref(row.episode),
        **_episode_fields(row.episode),
        **date_json(row),
        "date_timezone": row.date_timezone,
        "rating": row.rating,
        "review": row.review,
        "listened_at": row.listened_at,
        "device": _ref(row.device),
    }


def youtube_video_json(video: YouTubeVideo) -> dict[str, Any]:
    return {
        "id": video.id,
        "name": video.name,
        **date_json(video),
        "date_timezone": video.date_timezone,
        "youtube_id": video.youtube_id,
        "rating": video.rating,
        "review": video.review,
        "device": None if video.device is None else {"id": video.device.id, "name": video.device.name},
        "watched_at": video.watched_at,
        "channel": video.channel,
        "category": video.category,
        "duration": video.duration,
        "uploaded": video.uploaded.isoformat() if video.uploaded else "",
        "views": video.views,
        "unavailable": video.unavailable,
        # the page and the thumbnail are YouTube's, by youtube_id: the page
        # builds their URLs itself, which keeps 30,000 rows a quarter shorter
    }


# a film's ids: (field, what a whole one is, an example)
FILM_IDS = (
    ("wikidata_id", re.compile(r"Q\d+"), "Q13417189"),
    ("rotten_tomatoes_id", re.compile(r"(m|tv)/[A-Za-z0-9_-]+"), "m/interstellar_2014"),
)
IMDB_ID = re.compile(r"tt\d{7,9}")
# the id inside what was typed: tt0816692, 0816692, or a link to the film at IMDb
IMDB_TYPED = re.compile(r"(?:tt)?(\d{7,9})")


def imdb_id(value: str) -> str:
    """ A film's IMDb id ("tt0816692") from what was typed: the id, its number, or a link to the film at IMDb; "" for nothing. """
    if not value:
        return ""
    found = IMDB_TYPED.search(value.rsplit("/title/", 1)[-1])
    if found is None:
        raise ApiError(400, "imdb_id: expected an id like tt0816692, or a link to the film at IMDb")
    return f"tt{found.group(1)}"


def _film_fields(film: Film) -> dict[str, Any]:
    """ What a film is, as its card and a watch of it show it. """
    return {
        "film": _ref(film),
        "kind": film.kind,
        "kind_name": FILM_KINDS.get(film.kind, film.kind),
        "year": film.year,
        "directors": film.directors,
        "genres": film.genres,
        "imdb_id": film.imdb_id or "",
        "tmdb_id": film.tmdb_id,
        "wikidata_id": film.wikidata_id,
        "rotten_tomatoes_id": film.rotten_tomatoes_id,
        # its page at IMDb, and its poster
        "url": f"https://www.imdb.com/title/{film.imdb_id}/" if film.imdb_id else "",
        "image": image_url(film.image_id),
    }


def _watch_name(watch: FilmWatch) -> str:
    """ What a watch is called in a list of a film's: the day it was watched, else its status. """
    return _shown_date(watch) or FILM_WATCH_STATUSES.get(watch.status, watch.status)


def _shown_date(row: Any) -> str:
    """ The date as a card shows it: the day (of a timestamp too), the month or the year; "" for none. """
    date = date_json(row)["date"]
    return date[:10] if date else ""


def film_json(film: Film, mine: list[FilmWatch] | None = None) -> dict[str, Any]:
    """ A film, shared; the signed-in user's watches of it (mine), when said, or else looked for. """
    if mine is None:
        mine = [watch for watch in film.watches if watch.owner_id == flask.g.user.id]
    return {
        "id": film.id,
        "name": film.name,
        **_film_fields(film),
        "watches": [{"id": w.id, "name": _watch_name(w)} for w in sorted(mine, key=lambda w: date_json(w)["date_sort"], reverse=True)],
    }


def film_watch_json(watch: FilmWatch) -> dict[str, Any]:
    return {
        "id": watch.id,
        "name": watch.film.name,
        **_film_fields(watch.film),
        "status": watch.status,
        "status_name": FILM_WATCH_STATUSES.get(watch.status, watch.status),
        **date_json(watch),
        "date_timezone": watch.date_timezone,
        "rating": watch.rating,
        "review": watch.review,
        "watched_at": watch.watched_at,
        "device": _ref(watch.device),
        "recommended_by": None if watch.recommended_by is None else {"id": watch.recommended_by.id, "name": shown_name(watch.recommended_by)},
        "seasons_seen": watch.seasons_seen,
        "seasons_not_seen": watch.seasons_not_seen,
        "with": _names(watch.people),
        "people": _refs(watch.people),
    }


# what the list of games says of each: every column but the game's text, which only one game opened needs
CHESS_LISTED = (
    ChessGame.id, ChessGame.date_utcz, ChessGame.date_ymd, ChessGame.date_my, ChessGame.date_y, ChessGame.date_timezone,
    ChessGame.color, ChessGame.white, ChessGame.black, ChessGame.opponent, ChessGame.outcome, ChessGame.white_elo, ChessGame.black_elo, ChessGame.result,
    ChessGame.termination, ChessGame.time_control, ChessGame.eco, ChessGame.opening, ChessGame.event, ChessGame.site,
    ChessGame.link, ChessGame.plies, ChessGame.final_position, ChessGame.remark,
)


def chess_game_json(game: Any) -> dict[str, Any]:
    """ A game as the list has it: of a ChessGame, or of a row of CHESS_LISTED (60,000 games are read as rows, not as objects). """
    return {
        "id": game.id,
        "name": pgn.name(game.white, game.black, game.opponent),
        **date_json(game),
        "date_timezone": game.date_timezone,
        # the side the user played ("" where it is not known)
        "color": game.color,
        "white": game.white,
        "black": game.black,
        # whom they played, and how it ended for them ("won", "lost", "drawn"; "" where not known)
        "opponent": game.opponent,
        "outcome": game.outcome,
        "white_elo": game.white_elo,
        "black_elo": game.black_elo,
        "result": game.result,
        "termination": game.termination,
        "time_control": game.time_control,
        "eco": game.eco,
        "opening": game.opening,
        "event": game.event,
        "site": game.site,
        "link": game.link,
        "plies": game.plies,
        # where the pieces stood at the end: the page draws its card's picture from it
        "position": game.final_position,
        "remark": game.remark,
    }


def person_json(person: Person) -> dict[str, Any]:
    return {
        "id": person.id,
        # what they are shown by: their name in the language the account prefers, else the English one
        "name": shown_name(person),
        "english_name": person.name,
        # the account owner themselves
        "is_self": person.is_self,
        "honorific": person.honorific,
        "first_name": person.first_name,
        "middle_name": person.middle_name,
        "surname": person.surname,
        # their name in other languages ("he": "חיים שפירא"), each in its parts; the English one is the name parts above
        "names": [
            {"locale": n.locale, "name": n.name, "honorific": n.honorific, "first_name": n.first_name, "middle_name": n.middle_name, "surname": n.surname}
            for n in person.names
        ],
        # their photos, each with its credit: the first is the default, the one their card shows
        "image": image_url(person.photos[0].image_id) if person.photos else None,
        "photos": [photo_json(photo) for photo in person.photos],
        "types": _refs(person.types),
        # each organization they are linked to, once; and the links, each of a kind ("Worked at Schema")
        "organizations": _refs(person.organizations),
        "organization_links": [
            {"type_id": link.relation_type.id, "type": link.relation_type.name, "organization": {"id": link.organization.id, "name": link.organization.name},
             "name": f"{link.relation_type.name} {link.organization.name}"}
            for link in person.organization_links
        ],
        # how they are related to other people, each read from their side:
        # "Mother of Dana" (their own relations) and "Child of Ruth" (Ruth's)
        "relations": [_relation_json(r.relation_type.id, r.relation_type.name, r.other) for r in person.relations],
        "related": [_relation_json(r.relation_type.id, r.relation_type.inverse_name, r.person) for r in person.related],
        "description": person.description,
    }


def _relation_json(type_id: int, phrase: str, other: Person) -> dict[str, Any]:
    return {"type_id": type_id, "type": phrase, "person": {"id": other.id, "name": shown_name(other)}, "name": f"{phrase} {shown_name(other)}"}


def organization_json(organization: Organization) -> dict[str, Any]:
    return {
        "id": organization.id,
        "name": organization.name,
        # what it is: any number of the user's own organization types
        "types": _refs(organization.types),
        # how it is related to the user: any number of their own relation types
        "relations": _refs(organization.relations),
        "status": organization.status,
        "website": organization.website,
        "location": organization.location,
        "city": city_ref(organization.city),
        "headquarters": city_ref(organization.headquarters),
        # the address in one line, and its parts (the city carries region and country)
        "address": organization.address,
        **_address_parts(organization),
        "latitude": organization.latitude,
        "longitude": organization.longitude,
        "what_happened": organization.what_happened,
        "remark": organization.remark,
        "image": image_url(organization.image_id),
        "people": _refs(organization.people),
        # how each is linked to it: "Dana Cohen (Worked at)"
        "person_links": [
            {"type_id": link.relation_type.id, "type": link.relation_type.name, "person": {"id": link.person.id, "name": shown_name(link.person)},
             "name": f"{shown_name(link.person)} ({link.relation_type.name})"}
            for link in sorted(organization.person_links, key=lambda link: (shown_name(link.person), link.relation_type.name))
        ],
    }


def _newest_first(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: (item["date_sort"], item["name"]), reverse=True)


@bp.route("/api/concert-visits", methods=["GET"])
@auth.login_required
def api_concerts() -> flask.Response:
    query = select(Concert).where(Concert.owner_id == flask.g.user.id).options(
        selectinload(Concert.people), selectinload(Concert.performers), selectinload(Concert.place).selectinload(Place.city).selectinload(City.country), selectinload(Concert.groups),
    )
    concerts = flask.g.db.execute(query).scalars().all()
    return flask.jsonify(_newest_first([concert_json(c) for c in concerts]))


@bp.route("/api/audio-courses", methods=["GET"])
@auth.login_required
def api_audio_courses() -> flask.Response:
    query = select(AudioCourse).where(AudioCourse.owner_id == flask.g.user.id).options(selectinload(AudioCourse.lecturers), selectinload(AudioCourse.device))
    courses = flask.g.db.execute(query).scalars().all()
    # finished ones newest first; those in progress (no date yet) after them
    return flask.jsonify(_newest_first([audio_course_json(c) for c in courses]))


@bp.route("/api/audio-books", methods=["GET"])
@auth.login_required
def api_audio_books() -> flask.Response:
    """ Every audio book (shared), by title. """
    query = select(AudioBook).options(selectinload(AudioBook.versions)).order_by(AudioBook.name, AudioBook.id)
    return flask.jsonify([audio_book_json(b) for b in flask.g.db.scalars(query)])


@bp.route("/api/audio-book-versions", methods=["GET"])
@auth.login_required
def api_audio_book_versions() -> flask.Response:
    """ Every version of every audio book (shared), by the book's title, each saying whether the user heard it. """
    mine = {listen.version_id: listen for listen in flask.g.db.scalars(select(AudioBookListen).where(AudioBookListen.owner_id == flask.g.user.id))}
    query = select(AudioBookVersion).join(AudioBook).options(selectinload(AudioBookVersion.book)).order_by(AudioBook.name, AudioBookVersion.id)
    return flask.jsonify([audio_book_version_json(v, mine.get(v.id)) for v in flask.g.db.scalars(query)])


@bp.route("/api/audio-books-heard", methods=["GET"])
@auth.login_required
def api_audio_books_heard() -> flask.Response:
    """
    Your audio books: the shared audio books filtered to those the user heard
    a version of, each with their rating and review of it (their
    AudioBookHeard, which a listen makes). One whose listens were all
    deleted is not listed, and keeps the rating and review for when one is
    heard again.
    """
    heard_of = select(AudioBookVersion.book_id).join(AudioBookListen).where(AudioBookListen.owner_id == flask.g.user.id)
    query = select(AudioBookHeard).where(AudioBookHeard.owner_id == flask.g.user.id, AudioBookHeard.book_id.in_(heard_of)).options(
        selectinload(AudioBookHeard.book).selectinload(AudioBook.versions).selectinload(AudioBookVersion.listens),
    )
    # the latest finished, or come into the library, first
    return flask.jsonify(_newest_first([audio_book_heard_json(row) for row in flask.g.db.scalars(query)]))


@bp.route("/api/audio-book-listens", methods=["GET"])
@auth.login_required
def api_audio_book_listens() -> flask.Response:
    query = select(AudioBookListen).where(AudioBookListen.owner_id == flask.g.user.id).options(
        selectinload(AudioBookListen.version).selectinload(AudioBookVersion.book), selectinload(AudioBookListen.device),
    )
    # the latest finished, or come into the library, first
    return flask.jsonify(_newest_first([audio_book_listen_json(listen) for listen in flask.g.db.scalars(query)]))


@bp.route("/api/podcasts", methods=["GET"])
@auth.login_required
def api_podcasts() -> flask.Response:
    """ Every podcast (shared), by name. """
    query = select(Podcast).options(selectinload(Podcast.episodes)).order_by(Podcast.name)
    return flask.jsonify([podcast_json(p) for p in flask.g.db.scalars(query)])


@bp.route("/api/podcast-episodes", methods=["GET"])
@auth.login_required
def api_podcast_episodes() -> flask.Response:
    """ Every episode of every podcast (shared), the latest published first, each saying whether the user heard it. """
    mine = {heard.episode_id: heard for heard in flask.g.db.scalars(select(EpisodeHeard).where(EpisodeHeard.owner_id == flask.g.user.id))}
    query = select(PodcastEpisode).options(selectinload(PodcastEpisode.podcast)).order_by(PodcastEpisode.published_utcz.desc(), PodcastEpisode.id.desc())
    return flask.jsonify([podcast_episode_json(e, mine.get(e.id)) for e in flask.g.db.scalars(query)])


@bp.route("/api/podcasts-heard", methods=["GET"])
@auth.login_required
def api_podcasts_heard() -> flask.Response:
    """
    Your podcasts: the shared podcasts filtered to those the user heard an
    episode of, each with their rating and review of it (their PodcastHeard,
    which hearing an episode makes). One whose episodes heard were all
    deleted is not listed, and keeps the rating and review for when one is
    heard again.
    """
    heard_of = select(PodcastEpisode.podcast_id).join(EpisodeHeard).where(EpisodeHeard.owner_id == flask.g.user.id)
    query = select(PodcastHeard).where(PodcastHeard.owner_id == flask.g.user.id, PodcastHeard.podcast_id.in_(heard_of)).options(
        selectinload(PodcastHeard.podcast).selectinload(Podcast.episodes).selectinload(PodcastEpisode.heard).selectinload(EpisodeHeard.episode),
    )
    # the one heard last first
    return flask.jsonify(_newest_first([podcast_heard_json(p) for p in flask.g.db.scalars(query)]))


@bp.route("/api/episodes-heard", methods=["GET"])
@auth.login_required
def api_episodes_heard() -> flask.Response:
    query = select(EpisodeHeard).where(EpisodeHeard.owner_id == flask.g.user.id).options(
        selectinload(EpisodeHeard.episode).selectinload(PodcastEpisode.podcast), selectinload(EpisodeHeard.device),
    )
    # the latest heard first; of those heard the same day, the latest published first
    episodes = [episode_heard_json(e) for e in flask.g.db.scalars(query)]
    return flask.jsonify(sorted(episodes, key=lambda e: (e["date_sort"], e["published"]), reverse=True))


def _films(kind: str) -> flask.Response:
    """ Every film of kind (shared), by title, each with the user's watches of it. """
    mine: dict[int, list[FilmWatch]] = {}
    for watch in flask.g.db.scalars(select(FilmWatch).where(FilmWatch.owner_id == flask.g.user.id)):
        mine.setdefault(watch.film_id, []).append(watch)
    query = select(Film).where(Film.kind == kind).order_by(Film.name, Film.year, Film.id)
    return flask.jsonify([film_json(f, mine.get(f.id, [])) for f in flask.g.db.scalars(query)])


def _film_watches(kind: str) -> flask.Response:
    """ The user's watches of the films of kind, the latest watched first; those still to see (no date) after them. """
    query = select(FilmWatch).join(Film).where(FilmWatch.owner_id == flask.g.user.id, Film.kind == kind).options(
        selectinload(FilmWatch.film), selectinload(FilmWatch.device), selectinload(FilmWatch.people), selectinload(FilmWatch.recommended_by),
    )
    return flask.jsonify(_newest_first([film_watch_json(w) for w in flask.g.db.scalars(query)]))


@bp.route("/api/films", methods=["GET"])
@auth.login_required
def api_films() -> flask.Response:
    return _films("film")


@bp.route("/api/series", methods=["GET"])
@auth.login_required
def api_series() -> flask.Response:
    return _films("series")


@bp.route("/api/film-watches", methods=["GET"])
@auth.login_required
def api_film_watches() -> flask.Response:
    return _film_watches("film")


@bp.route("/api/series-watches", methods=["GET"])
@auth.login_required
def api_series_watches() -> flask.Response:
    return _film_watches("series")


@bp.route("/api/youtube-videos", methods=["GET"])
@auth.login_required
def api_youtube() -> flask.Response:
    query = select(YouTubeVideo).where(YouTubeVideo.owner_id == flask.g.user.id).options(selectinload(YouTubeVideo.device))
    videos = flask.g.db.execute(query).scalars().all()
    return flask.jsonify(_newest_first([youtube_video_json(v) for v in videos]))


@bp.route("/api/chess-games", methods=["GET"])
@auth.login_required
def api_chess_games() -> flask.Response:
    """
    The user's games, newest first. ?compact=1 says the names of the fields
    once ("columns") and each game as its values in that order ("rows"),
    which is what the page asks for: 60,000 games are half the size so.
    """
    games = flask.g.db.execute(select(*CHESS_LISTED).where(ChessGame.owner_id == flask.g.user.id)).all()
    listed = _newest_first([chess_game_json(game) for game in games])
    if flask.request.args.get("compact") != "1":
        return flask.jsonify(listed)
    # (a game's name is its players': the page puts it together)
    columns = [column for column in (listed[0] if listed else chess_game_json(ChessGame(white="", black=""))) if column != "name"]
    return flask.jsonify({"columns": columns, "rows": [[game[column] for column in columns] for game in listed]})


@bp.route("/api/chess-games/<int:row_id>", methods=["GET"])
@auth.login_required
def api_chess_game(row_id: int) -> flask.Response:
    """
    One game, with what only a game opened needs: its text, and its moves to
    play through (each with the clock after it, where one was written). One
    recorded without its moves has neither.
    """
    game = owned(ChessGame, row_id)
    moves = pgn.parse(game.pgn).moves if game.pgn else []
    return flask.jsonify({
        **chess_game_json(game),
        "pgn": game.pgn,
        "moves": [move.san for move in moves],
        "clocks": [move.clock for move in moves] if any(move.clock for move in moves) else [],
    })


def _museum_visit_type() -> VisitType:
    found = flask.g.db.scalars(select(VisitType).where(VisitType.name == MUSEUM_VISIT)).first()
    if found is None:
        raise ApiError(500, f"there is no visit type {MUSEUM_VISIT!r}")
    return found


def _museum_visits(place_id: int | None = None) -> dict[Place, list[Visit]]:
    """ The signed-in user's museum visits, by the museum (a place) each was to. """
    query = (
        select(Visit).join(VisitType).where(Visit.owner_id == flask.g.user.id, VisitType.name == MUSEUM_VISIT, Visit.place_id.is_not(None))
        .options(selectinload(Visit.people), selectinload(Visit.place).selectinload(Place.city).selectinload(City.country))
        .order_by(Visit.id)
    )
    if place_id is not None:
        query = query.where(Visit.place_id == place_id)
    by_place: dict[Place, list[Visit]] = {}
    for visit in flask.g.db.scalars(query):
        assert visit.place is not None
        by_place.setdefault(visit.place, []).append(visit)
    return by_place


@bp.route("/api/museum-visits", methods=["GET"])
@auth.login_required
def api_museums() -> flask.Response:
    """ The museums the user visited (shared places), each with their visits to it. """
    return flask.jsonify(_newest_first([museum_json(place, visits) for place, visits in _museum_visits().items()]))


def _museum(body: dict[str, Any] | None, place_id: int | None = None) -> Place:
    """ The museum a request is about: the place of place_id (a route's) or body's place_id, which must be a museum. """
    place = flask.g.db.get(Place, place_id) if place_id is not None else owned_ref(body or {}, "place_id", Place, "place")
    if place is None:
        raise ApiError(404 if place_id is not None else 400, "no such museum" if place_id is not None else "place_id: choose the museum")
    if not any(kind.name == MUSEUM_KIND for kind in place.kinds):
        raise ApiError(400, f"{place.name} is not a museum (a place of the kind {MUSEUM_KIND}): an admin can say it is, on the Places page")
    return place


def _apply_museum_visits(place: Place, had: list[Visit], body: dict[str, Any]) -> list[Visit]:
    """
    visits, sent, are all the user's visits to the museum: one with the id of
    a visit they had is that visit, changed; the others are new, and those
    they had that are not sent are gone.
    """
    sent = body.get("visits")
    if not isinstance(sent, list) or not all(isinstance(item, dict) for item in sent):
        raise ApiError(400, "visits: expected a list of visits")
    by_id = {visit.id: visit for visit in had}
    kind = _museum_visit_type()
    visits: list[Visit] = []
    for item in sent:
        visit_id = item.get("id")
        if visit_id is not None and (visit_id not in by_id or visit_id in {visit.id for visit in visits}):
            raise ApiError(400, "visits: unknown visit")
        visit = by_id[visit_id] if visit_id is not None else Visit(owner_id=flask.g.user.id, place=place, type=kind)
        _apply_visit(visit, item)
        visits.append(visit)
        flask.g.db.add(visit)
    for visit in had:
        if visit not in visits:
            flask.g.db.delete(visit)
    return visits


@bp.route("/api/museum-visits", methods=["POST"])
@auth.login_required
def api_museum_add() -> tuple[flask.Response, int]:
    """ The user's visits to a museum they have none of yet: {"place_id": ..., "visits": [...]}. """
    body = json_body()
    place = _museum(body)
    if _museum_visits(place.id):
        raise ApiError(409, f"{place.name} has visits in your Museum visits already: add the visit to them")
    visits = _apply_museum_visits(place, [], body)
    flask.g.db.commit()
    return flask.jsonify(museum_json(place, visits)), 201


@bp.route("/api/museum-visits/<int:place_id>", methods=["PUT"])
@auth.login_required
def api_museum_update(place_id: int) -> flask.Response:
    """ All the user's visits to the museum place_id: {"visits": [...]}. The museum itself is shared: an admin changes it on the Places page. """
    place = _museum(None, place_id)
    visits = _apply_museum_visits(place, _museum_visits(place.id).get(place, []), json_body())
    flask.g.db.commit()
    return flask.jsonify(museum_json(place, visits))


@bp.route("/api/museum-visits/<int:place_id>", methods=["DELETE"])
@auth.login_required
def api_museum_delete(place_id: int) -> flask.Response:
    """ The user's visits to the museum place_id; the museum stays, everyone's. """
    for visit in _museum_visits(place_id).get(flask.g.db.get(Place, place_id), []):
        flask.g.db.delete(visit)
    flask.g.db.commit()
    return flask.Response(status=204)


@bp.route("/api/people", methods=["GET"])
@auth.login_required
def api_people() -> flask.Response:
    query = (
        select(Person)
        .where(Person.owner_id == flask.g.user.id)
        .options(
            selectinload(Person.organizations), selectinload(Person.types), selectinload(Person.names),
            selectinload(Person.organization_links).selectinload(PersonOrganization.relation_type),
            selectinload(Person.organization_links).selectinload(PersonOrganization.organization),
            selectinload(Person.relations).selectinload(PersonRelation.relation_type), selectinload(Person.relations).selectinload(PersonRelation.other),
            selectinload(Person.related).selectinload(PersonRelation.relation_type), selectinload(Person.related).selectinload(PersonRelation.person),
        )
        .order_by(Person.first_name, Person.surname, Person.id)
    )
    people = flask.g.db.execute(query).scalars().all()
    return flask.jsonify([person_json(p) for p in people])


@bp.route("/api/organizations", methods=["GET"])
@auth.login_required
def api_organizations() -> flask.Response:
    query = (
        select(Organization)
        .where(Organization.owner_id == flask.g.user.id)
        .options(
            selectinload(Organization.people), selectinload(Organization.types), selectinload(Organization.relations), selectinload(Organization.city).selectinload(City.country),
            selectinload(Organization.headquarters).selectinload(City.country),
            selectinload(Organization.person_links).selectinload(PersonOrganization.relation_type),
            selectinload(Organization.person_links).selectinload(PersonOrganization.person),
        )
        .order_by(Organization.name)
    )
    organizations = flask.g.db.execute(query).scalars().all()
    return flask.jsonify([organization_json(c) for c in organizations])


@bp.route("/api/places", methods=["GET"])
@auth.login_required
def api_places() -> flask.Response:
    query = select(Place).options(
        selectinload(Place.concerts), selectinload(Place.visits), selectinload(Place.kinds), selectinload(Place.city).selectinload(City.country),
    ).order_by(Place.name, Place.id)
    places = flask.g.db.execute(query).scalars().all()
    return flask.jsonify([place_json(p) for p in places])


@bp.route("/api/groups", methods=["GET"])
@auth.login_required
def api_groups() -> flask.Response:
    query = select(Group).where(Group.owner_id == flask.g.user.id).options(selectinload(Group.members), selectinload(Group.concerts)).order_by(Group.name)
    groups = flask.g.db.execute(query).scalars().all()
    return flask.jsonify([group_json(g) for g in groups])


@bp.route("/api/cities", methods=["GET"])
@auth.login_required
def api_cities() -> flask.Response:
    query = (
        select(City)
        .options(
            selectinload(City.places).selectinload(Place.kinds), selectinload(City.organizations), selectinload(City.headquarters_of), selectinload(City.country),
            selectinload(City.region_row), selectinload(City.more_photos),
        )
        .order_by(City.name, City.id)
    )
    return _listed([city_json(c) for c in flask.g.db.execute(query).scalars().all()])


def _listed(listed: list[dict[str, Any]]) -> flask.Response:
    """
    A long list (the cities of the world, tens of thousands of them): as
    it is, or, with ?compact=1 (what the page asks for), with the names of
    its fields said once ("columns") and each row as its values in that
    order ("rows"), which is a fraction of the size.
    """
    if flask.request.args.get("compact") != "1":
        return flask.jsonify(listed)
    columns = list(listed[0]) if listed else []
    return flask.jsonify({"columns": columns, "rows": [[row[column] for column in columns] for row in listed]})


@bp.route("/api/regions", methods=["GET"])
@auth.login_required
def api_regions() -> flask.Response:
    """ The regions the cities say, each with its country and its cities: what the city form offers. """
    query = select(Region).options(selectinload(Region.cities), selectinload(Region.country)).order_by(Region.name, Region.id)
    return flask.jsonify([
        {"id": region.id, "name": region.name, "country": country_ref(region.country), "cities": _refs(region.cities)}
        for region in flask.g.db.execute(query).scalars().all()
    ])


@bp.route("/api/countries", methods=["GET"])
@auth.login_required
def api_countries() -> flask.Response:
    query = select(Country).options(selectinload(Country.cities), selectinload(Country.currencies), selectinload(Country.languages)).order_by(Country.name)
    return flask.jsonify([country_json(c) for c in flask.g.db.execute(query).scalars().all()])


@bp.route("/api/currencies", methods=["GET"])
@auth.login_required
def api_currencies() -> flask.Response:
    query = select(Currency).options(selectinload(Currency.countries)).order_by(Currency.code)
    return flask.jsonify([currency_json(c) for c in flask.g.db.execute(query).scalars().all()])




# ─── adding ──────────────────────────────────────────────────────────────────



def _apply_dates(row: Concert | Visit | AudioCourse | AudioBookListen | EpisodeHeard | FilmWatch | YouTubeVideo, body: dict[str, Any]) -> None:
    """
    The date as typed: YYYY, YYYY-MM or YYYY-MM-DD, stored at that precision,
    or nothing. date_timezone is where it happened (an IANA name). A date
    sent back exactly as the row shows it leaves it as it is, so a stored
    timestamp keeps its time.
    """
    value = text(body, "date")
    zone = text(body, "date_timezone")
    if zone:
        try:
            zoneinfo.ZoneInfo(zone)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError) as e:
            raise ApiError(400, f"date_timezone: unknown time zone {zone!r}") from e
    row.date_timezone = zone
    if value == (date_json(row)["date"] or ""):
        return
    utcz, ymd, my, y = None, None, "", None
    month = re.fullmatch(r"(\d{4})-(\d{2})", value)
    if re.fullmatch(r"\d{4}", value):
        y = int(value)
    elif month:
        if not 1 <= int(month.group(2)) <= 12:
            raise ApiError(400, "date: no such month")
        my = f"{month.group(2)}-{month.group(1)}"
    elif value:
        try:
            ymd = datetime.date.fromisoformat(value)
        except ValueError as e:
            raise ApiError(400, "date: expected YYYY, YYYY-MM or YYYY-MM-DD") from e
    row.date_utcz, row.date_ymd, row.date_my, row.date_y = utcz, ymd, my, y




def _owned_people(body: dict[str, Any]) -> list[Person]:
    return owned_list(body, "people", Person)












def _apply_concert(concert: Concert, body: dict[str, Any]) -> None:
    concert.name = text(body, "name", required=True)
    concert.performers = owned_list(body, "performers", Person)
    concert.groups = owned_list(body, "groups", Group)
    concert.event = text(body, "event")
    concert.genre = text(body, "genre")
    concert.place = owned_ref(body, "place_id", Place, "place")
    concert.tickets = opt_int(body, "tickets", 0, 1000)
    concert.broadcast = body.get("broadcast") is True
    concert.review = text(body, "review")
    concert.remark = text(body, "remark")
    # a photo is only ever replaced by a new upload, never blanked by omission
    apply_picture(concert, body)
    concert.people = _owned_people(body)
    concert.alone = body.get("alone") is True
    if concert.alone and concert.people:
        raise ApiError(400, "a concert gone to alone has no one in With")
    _apply_dates(concert, body)








def _apply_country(country: Country, body: dict[str, Any]) -> None:
    name = text(body, "name", required=True)
    clash = flask.g.db.execute(select(Country.id).where(Country.name == name, Country.id != country.id)).first()
    if clash is not None:
        raise ApiError(409, f"{name} is already in Countries")
    code = text(body, "code").upper() or None
    if code is not None and not re.fullmatch(r"[A-Z]{2}", code):
        raise ApiError(400, "code: a country's code is its two letters, as ISO 3166 names it (IL, US, FR)")
    if code is not None and flask.g.db.execute(select(Country.id).where(Country.code == code, Country.id != country.id)).first() is not None:
        raise ApiError(409, f"code: {code} is another country's")
    code3 = text(body, "code3").upper()
    if code3 and not re.fullmatch(r"[A-Z]{3}", code3):
        raise ApiError(400, "code3: a country's three-letter code, as ISO 3166 names it (ISR, USA, FRA)")
    country.name, country.code, country.code3 = name, code, code3
    if "currency_ids" in body:
        country.currencies = owned_list(body, "currency_ids", Currency)
    country.latitude, country.longitude = coordinates(body)
    apply_picture(country, body)






def _apply_city(city: City, body: dict[str, Any]) -> None:
    name = text(body, "name", required=True)
    country = owned_ref(body, "country_id", Country, "country")
    # its region, by name: the row of that name in that country, made when a city first says it
    region = region_for(flask.g.db, text(body, "region"), country)
    clash = flask.g.db.execute(
        select(City.id).where(
            City.name == name,
            City.region_id == region.id if region is not None and region.id is not None else City.region_id.is_(None),
            City.country_id == country.id if country else City.country_id.is_(None), City.id != city.id,
        )
    ).first()
    # (a region made just now has no city in it yet)
    if clash is not None and (region is None or region.id is not None):
        raise ApiError(409, f"{name}{', ' + country.name if country else ''} is already in Cities")
    city.name, city.region_row, city.country = name, region, country
    city.latitude, city.longitude = coordinates(body)
    city.population = opt_int(body, "population", 0, 10**11)
    if "photos" in body:
        # all its photos, replacing those it had: the first is the one its card shows
        # (cities.image_id and its credit), the others follow it
        photos = sent_photos(body["photos"])
        city.image_id, (city.image_source, city.image_license, city.image_author) = photos[0] if photos else (None, ("", "", ""))
        city.more_photos = photo_rows(city.more_photos, CityPhoto, photos[1:])
    else:
        apply_picture(city, body)


def _apply_place(place: Place, body: dict[str, Any]) -> None:
    name = text(body, "name", required=True)
    city = owned_ref(body, "city_id", City, "city")
    clash = flask.g.db.execute(
        select(Place.id).where(
            Place.name == name, Place.city_id == city.id if city else Place.city_id.is_(None), Place.id != place.id,
        )
    ).first()
    if clash is not None:
        raise ApiError(409, f"{name}{', ' + city.name if city else ''} is already in Places")
    place.name = name
    place.city = city
    _apply_address(place, body)
    place.latitude, place.longitude = coordinates(body)
    place.website = text(body, "website")
    place.kinds = owned_list(body, "kinds", PlaceKind)
    apply_picture(place, body)


def _apply_group(group: Group, body: dict[str, Any]) -> None:
    name = text(body, "name", required=True)
    clash = flask.g.db.execute(select(Group.id).where(Group.owner_id == flask.g.user.id, Group.name == name, Group.id != group.id)).first()
    if clash is not None:
        raise ApiError(409, f"{name} is already in Groups")
    # looked up before anything is set on a new group, which is not in the session yet
    members = owned_list(body, "members", Person)
    group.name = name
    group.members = members
    group.description = text(body, "description")
    group.website = text(body, "website")
    apply_picture(group, body)


def _apply_visit(visit: Visit, body: dict[str, Any]) -> None:
    visit.rating = opt_int(body, "rating", RATING_MIN, RATING_MAX)
    visit.review = text(body, "review")
    visit.remark = text(body, "remark")
    visit.tickets = opt_int(body, "tickets", 0, 1000)
    visit.people = _owned_people(body)
    visit.alone = body.get("alone") is True
    if visit.alone and visit.people:
        raise ApiError(400, "a visit made alone has no one in With")
    _apply_dates(visit, body)


def _apply_currency(currency: Currency, body: dict[str, Any]) -> None:
    code = text(body, "code", required=True).upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise ApiError(400, "code: a currency's code is its three letters, as ISO 4217 names it (ILS, USD, EUR)")
    if flask.g.db.execute(select(Currency.id).where(Currency.code == code, Currency.id != currency.id)).first() is not None:
        raise ApiError(409, f"{code} is already in Currencies")
    currency.code = code
    currency.name = text(body, "name")
    currency.symbol = text(body, "symbol")
    currency.digits = opt_int(body, "digits", 0, 6)


def place_kind_json(kind: PlaceKind) -> dict[str, Any]:
    return {"id": kind.id, "name": kind.name, "count": len(kind.places)}


def visit_type_json(kind: VisitType) -> dict[str, Any]:
    # how many visits are of it: the signed-in user's
    return {"id": kind.id, "name": kind.name, "count": len(_mine(kind.visits))}


def _apply_named(model: type[PlaceKind | VisitType], what: str) -> Callable[[Any, dict[str, Any]], None]:
    """ How a body is applied to a shared list of names (place kinds, visit types): a name once in it. """
    def apply(row: Any, body: dict[str, Any]) -> None:
        name = text(body, "name", required=True)
        if flask.g.db.execute(select(model.id).where(model.name == name, model.id != row.id)).first() is not None:
            raise ApiError(409, f"{name} is already in {what}")
        row.name = name
    return apply


def _stamp(body: dict[str, Any], key: str, current: datetime.datetime | None) -> datetime.datetime | None:
    """ A moment as YYYY-MM-DD or a full UTC timestamp; sent back as shown, it is kept as it was. """
    value = text(body, key)
    if not value:
        return None
    if value == _stamp_json(current):
        return current
    try:
        if len(value) == 10:
            return datetime.datetime.fromisoformat(value)
        return datetime.datetime.fromisoformat(value).astimezone(datetime.UTC).replace(tzinfo=None)
    except ValueError as e:
        raise ApiError(400, f"{key}: expected YYYY-MM-DD") from e


def _apply_audio_course(course: AudioCourse, body: dict[str, Any]) -> None:
    course.name = text(body, "name", required=True)
    course.lecturers = owned_list(body, "lecturers", Person)
    course.rating = opt_int(body, "rating", RATING_MIN, RATING_MAX)
    course.review = text(body, "review")
    course.device = owned_ref(body, "device_id", Device, "device")
    course.listened_at = text(body, "listened_at")
    course.started_utcz = _stamp(body, "started", course.started_utcz)
    course.ended_utcz = _stamp(body, "ended", course.ended_utcz)
    course.progress = text(body, "progress")
    course.great_courses_id = opt_int(body, "great_courses_id", 1, 2**31 - 1)
    course.great_courses_slug = text(body, "great_courses_slug")
    course.audible_asin = text(body, "audible_asin")
    course.link = text(body, "link")
    if course.link and not course.link.startswith(("https://", "http://")):
        raise ApiError(400, "link: expected an http(s) URL")
    apply_image(course, body)
    _apply_dates(course, body)


def _opt_number(body: dict[str, Any], key: str, low: float, high: float) -> float | None:
    """ A number from low to high, or None when empty. """
    value = body.get(key)
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as e:
        raise ApiError(400, f"{key}: expected a number") from e
    if not low <= number <= high:
        raise ApiError(400, f"{key}: expected {low:g} to {high:g}")
    return number


def _apply_audio_book(book: AudioBook, body: dict[str, Any]) -> None:
    name, subtitle, authors = text(body, "name", required=True), text(body, "subtitle"), text(body, "authors")
    clash = flask.g.db.execute(select(AudioBook.id).where(
        AudioBook.name == name, AudioBook.subtitle == subtitle, AudioBook.authors == authors, AudioBook.id != book.id,
    )).first()
    if clash is not None:
        raise ApiError(409, f"{name}{f': {subtitle}' if subtitle else ''}{f' by {authors}' if authors else ''} is already in Audio books")
    book.name = name
    book.subtitle = subtitle
    book.authors = authors
    book.series = text(body, "series")
    book.series_sequence = text(body, "series_sequence")
    for key, pattern, example in BOOK_IDS:
        value = text(body, key)
        if value and not pattern.fullmatch(value):
            raise ApiError(400, f"{key}: expected an id like {example}")
        setattr(book, key, value)


def _apply_audio_book_version(version: AudioBookVersion, body: dict[str, Any]) -> None:
    book = owned_ref(body, "book_id", AudioBook, "audio book")
    if book is None:
        raise ApiError(400, "book_id: a version is of an audio book")
    kind = text(body, "kind")
    if kind not in AUDIO_BOOK_KINDS:
        raise ApiError(400, f"kind: expected one of {', '.join(AUDIO_BOOK_KINDS)}")
    asin = text(body, "asin")
    if asin and kind != "audible":
        raise ApiError(400, "asin: only an Audible version has an ASIN")
    if asin:
        clash = flask.g.db.execute(select(AudioBookVersion.id).where(AudioBookVersion.asin == asin, AudioBookVersion.id != version.id)).first()
        if clash is not None:
            raise ApiError(409, f"asin: {asin} is in Audio book versions already")
    genres = body.get("genres", [])
    if isinstance(genres, str):
        genres = [g.strip() for g in genres.split(",")]
    if not isinstance(genres, list) or not all(isinstance(g, str) for g in genres):
        raise ApiError(400, "genres: expected a list of names")
    version.book = book
    version.kind = kind
    version.asin = asin or None
    # kept as listed, repeats too: Audible's list says each genre's path (AudioBookVersion.genres)
    version.genres = [g.strip() for g in genres if g.strip()]
    version.narrators = text(body, "narrators")
    version.minutes = opt_int(body, "minutes", 1, 100_000)
    version.parts = opt_int(body, "parts", 1, 10_000)
    released = text(body, "released")
    try:
        version.released = datetime.date.fromisoformat(released) if released else None
    except ValueError as e:
        raise ApiError(400, "released: expected YYYY-MM-DD") from e
    apply_image(version, body)


def hearing(owner_id: int, book: AudioBook) -> AudioBookHeard:
    """ owner's AudioBookHeard of book, made when they have none: a version heard is of a book they heard. """
    found = next((row for row in book.heard if row.owner_id == owner_id), None)
    if found is None:
        found = AudioBookHeard(owner_id=owner_id, book=book)
    return found


def _listens_of(row: AudioBookHeard) -> int:
    """ How many versions of row's book its user heard. """
    return len(flask.g.db.scalars(select(AudioBookListen.id).join(AudioBookVersion).where(
        AudioBookListen.owner_id == row.owner_id, AudioBookVersion.book_id == row.book_id,
    )).all())


def _apply_audio_book_heard(row: AudioBookHeard, body: dict[str, Any]) -> None:
    book = owned_ref(body, "book_id", AudioBook, "audio book")
    if book is None:
        raise ApiError(400, "book_id: choose the audio book")
    if row.id is None:
        # Your audio books are the books the user heard a version of: hearing one adds it
        raise ApiError(409, f"{book.name} is in Your audio books once you heard a version of it: add it in Audio book listens")
    clash = flask.g.db.execute(select(AudioBookHeard.id).where(
        AudioBookHeard.owner_id == flask.g.user.id, AudioBookHeard.book_id == book.id, AudioBookHeard.id != row.id,
    )).first()
    if clash is not None:
        raise ApiError(409, f"{book.name} is already in Your audio books")
    if row.book_id is not None and row.book_id != book.id and _listens_of(row):
        raise ApiError(409, f"you heard {row.book.name}: it stays the book your listens are of")
    row.book = book
    row.rating = opt_int(body, "rating", RATING_MIN, RATING_MAX)
    row.review = text(body, "review")


def _apply_audio_book_listen(listen: AudioBookListen, body: dict[str, Any]) -> None:
    version = owned_ref(body, "version_id", AudioBookVersion, "audio book version")
    if version is None:
        raise ApiError(400, "version_id: choose the version heard")
    clash = flask.g.db.execute(select(AudioBookListen.id).where(
        AudioBookListen.owner_id == flask.g.user.id, AudioBookListen.version_id == version.id, AudioBookListen.id != listen.id,
    )).first()
    if clash is not None:
        raise ApiError(409, f"{version_name(version)} is already in your Audio book listens")
    listen.version = version
    listen.finished = bool(body.get("finished"))
    listen.percent_heard = _opt_number(body, "percent_heard", 0, 100)
    listen.started_utcz = _stamp(body, "started", listen.started_utcz)
    listen.progress = text(body, "progress")
    listen.listened_at = text(body, "listened_at")
    listen.device = owned_ref(body, "device_id", Device, "device")
    _apply_dates(listen, body)
    flask.g.db.add(hearing(flask.g.user.id, version.book))


def _web_link(body: dict[str, Any], key: str) -> str:
    value = text(body, key)
    if value and not value.startswith(("https://", "http://")):
        raise ApiError(400, f"{key}: expected an http(s) URL")
    return value


def _apply_podcast(podcast: Podcast, body: dict[str, Any]) -> None:
    name = text(body, "name", required=True)
    clash = flask.g.db.execute(select(Podcast.id).where(Podcast.name == name, Podcast.id != podcast.id)).first()
    if clash is not None:
        raise ApiError(409, f"{name} is already in Podcasts")
    podcast.name = name
    podcast.url = _web_link(body, "url")
    podcast.rss_feed = _web_link(body, "rss_feed")
    apply_image(podcast, body)


def _apply_podcast_episode(episode: PodcastEpisode, body: dict[str, Any]) -> None:
    podcast = owned_ref(body, "podcast_id", Podcast, "podcast")
    if podcast is None:
        raise ApiError(400, "podcast_id: an episode is of a podcast")
    guid = text(body, "guid")
    if guid:
        clash = flask.g.db.execute(select(PodcastEpisode.id).where(
            PodcastEpisode.podcast_id == podcast.id, PodcastEpisode.guid == guid, PodcastEpisode.id != episode.id,
        )).first()
        if clash is not None:
            raise ApiError(409, f"guid: that episode of {podcast.name} is in Podcast episodes already")
    episode.podcast = podcast
    episode.guid = guid or None
    episode.name = text(body, "name", required=True)
    episode.description = text(body, "description")
    episode.published_utcz = _stamp(body, "published", episode.published_utcz)
    episode.number = opt_int(body, "number", 0, 2**31 - 1)
    episode.duration = opt_int(body, "duration", 0, 2**31 - 1)
    episode.episode_type = text(body, "episode_type")
    episode.explicit = text(body, "explicit")
    episode.enclosure_url = _web_link(body, "enclosure_url")
    episode.image_url = _web_link(body, "image_url")
    episode.author = text(body, "author")


def listening(owner_id: int, podcast: Podcast) -> PodcastHeard:
    """ owner's PodcastHeard of podcast, made (and added) when they have none: an episode heard is of a podcast they listen to. """
    found = next((row for row in podcast.heard if row.owner_id == owner_id), None)
    if found is None:
        found = PodcastHeard(owner_id=owner_id, podcast=podcast)
    return found


def _apply_podcast_heard(row: PodcastHeard, body: dict[str, Any]) -> None:
    podcast = owned_ref(body, "podcast_id", Podcast, "podcast")
    if podcast is None:
        raise ApiError(400, "podcast_id: choose the podcast")
    if row.id is None:
        # Your podcasts are the podcasts the user heard an episode of: hearing one adds it
        raise ApiError(409, f"{podcast.name} is in Your podcasts once you heard an episode of it: add the episode in Episodes heard")
    clash = flask.g.db.execute(select(PodcastHeard.id).where(
        PodcastHeard.owner_id == flask.g.user.id, PodcastHeard.podcast_id == podcast.id, PodcastHeard.id != row.id,
    )).first()
    if clash is not None:
        raise ApiError(409, f"{podcast.name} is already in your Podcasts heard")
    if row.podcast_id is not None and row.podcast_id != podcast.id and _heard_of(row):
        raise ApiError(409, f"you heard episodes of {row.podcast.name}: it stays the podcast they are of")
    row.podcast = podcast
    row.rating = opt_int(body, "rating", RATING_MIN, RATING_MAX)
    row.review = text(body, "review")


def _heard_of(row: PodcastHeard) -> int:
    """ How many episodes of row's podcast its user heard. """
    return len(flask.g.db.scalars(select(EpisodeHeard.id).join(PodcastEpisode).where(
        EpisodeHeard.owner_id == row.owner_id, PodcastEpisode.podcast_id == row.podcast_id,
    )).all())


def _apply_episode_heard(row: EpisodeHeard, body: dict[str, Any]) -> None:
    episode = owned_ref(body, "episode_id", PodcastEpisode, "episode")
    if episode is None:
        raise ApiError(400, "episode_id: choose the episode")
    clash = flask.g.db.execute(select(EpisodeHeard.id).where(
        EpisodeHeard.owner_id == flask.g.user.id, EpisodeHeard.episode_id == episode.id, EpisodeHeard.id != row.id,
    )).first()
    if clash is not None:
        raise ApiError(409, f"{episode.name} is already in your Episodes heard")
    row.episode = episode
    row.rating = opt_int(body, "rating", RATING_MIN, RATING_MAX)
    row.review = text(body, "review")
    row.listened_at = text(body, "listened_at")
    row.device = owned_ref(body, "device_id", Device, "device")
    _apply_dates(row, body)
    flask.g.db.add(listening(flask.g.user.id, episode.podcast))


YOUTUBE_ID = re.compile(rf"[A-Za-z0-9_-]{{{YOUTUBE_ID_LENGTH}}}")
# the id inside a pasted link: youtube.com/watch?v=ID, youtu.be/ID, youtube.com/shorts/ID, /embed/ID, /live/ID
YOUTUBE_LINK = re.compile(r"(?:[?&]v=|youtu\.be/|/(?:shorts|embed|live)/)([A-Za-z0-9_-]+)")


def youtube_id(value: str) -> str:
    """ The video id of what was typed: an id, or a link to the video. """
    found = YOUTUBE_LINK.search(value)
    if found:
        value = found.group(1)
    if not YOUTUBE_ID.fullmatch(value):
        raise ApiError(400, f"youtube_id: expected a video id ({YOUTUBE_ID_LENGTH} characters) or a link to the video")
    return value


def _apply_youtube_video(video: YouTubeVideo, body: dict[str, Any]) -> None:
    video.youtube_id = youtube_id(text(body, "youtube_id", required=True))
    clash = flask.g.db.execute(select(YouTubeVideo.id).where(
        YouTubeVideo.owner_id == flask.g.user.id, YouTubeVideo.youtube_id == video.youtube_id, YouTubeVideo.id != video.id,
    )).first()
    if clash is not None:
        raise ApiError(409, "that video is in your list already")
    # one YouTube no longer has may have no name: only its id is known
    video.name = text(body, "name", required=not video.unavailable)
    video.rating = opt_int(body, "rating", RATING_MIN, RATING_MAX)
    video.review = text(body, "review")
    video.device = owned_ref(body, "device_id", Device, "device")
    video.watched_at = text(body, "watched_at")
    _apply_dates(video, body)


def _apply_film(film: Film, body: dict[str, Any], kind: str = "film") -> None:
    """ A film, or a series (kind, which the body may change: a film then moves to the Series page). """
    name = text(body, "name", required=True)
    kind = text(body, "kind") or kind
    if kind not in FILM_KINDS:
        raise ApiError(400, f"kind: expected one of {', '.join(FILM_KINDS)}")
    imdb = imdb_id(text(body, "imdb_id"))
    if imdb:
        clash = flask.g.db.execute(select(Film.id).where(Film.imdb_id == imdb, Film.id != film.id)).first()
        if clash is not None:
            raise ApiError(409, f"imdb_id: {imdb} is in Films already")
    genres = body.get("genres", [])
    if isinstance(genres, str):
        genres = genres.split(",")
    if not isinstance(genres, list) or not all(isinstance(g, str) for g in genres):
        raise ApiError(400, "genres: expected a list of names")
    film.kind = kind
    film.name = name
    film.year = opt_int(body, "year", 1850, 2200)
    film.directors = text(body, "directors")
    film.genres = list(dict.fromkeys(g.strip() for g in genres if g.strip()))
    film.imdb_id = imdb or None
    film.tmdb_id = opt_int(body, "tmdb_id", 1, 2**31 - 1)
    for key, pattern, example in FILM_IDS:
        value = text(body, key)
        if value and not pattern.fullmatch(value):
            raise ApiError(400, f"{key}: expected an id like {example}")
        setattr(film, key, value)
    apply_image(film, body)


def _apply_series(film: Film, body: dict[str, Any]) -> None:
    _apply_film(film, body, "series")


def _seasons(body: dict[str, Any], key: str) -> list[int]:
    """ Season numbers, as a list or as typed ("1, 2, 3"), each once, in order. """
    value = body.get(key) or []
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",") if part.strip()]
    try:
        seasons = sorted({int(season) for season in value})
    except (TypeError, ValueError) as e:
        raise ApiError(400, f"{key}: expected season numbers, like 1, 2, 3") from e
    if any(not 0 <= season <= 1000 for season in seasons):
        raise ApiError(400, f"{key}: expected season numbers from 0 to 1000")
    return seasons


def _apply_film_watch(watch: FilmWatch, body: dict[str, Any]) -> None:
    film = owned_ref(body, "film_id", Film, "film")
    if film is None:
        raise ApiError(400, "film_id: choose the film")
    status = text(body, "status") or "done"
    if status not in FILM_WATCH_STATUSES:
        raise ApiError(400, f"status: expected one of {', '.join(FILM_WATCH_STATUSES)}")
    # what it points to is looked up first: the watch joins the film's (and the people's) last, once nothing is queried
    device = owned_ref(body, "device_id", Device, "device")
    recommended_by = owned_ref(body, "recommended_by_id", Person, "person")
    people = _owned_people(body)
    watch.status = status
    watch.rating = opt_int(body, "rating", RATING_MIN, RATING_MAX)
    watch.review = text(body, "review")
    watch.watched_at = text(body, "watched_at")
    seen, not_seen = _seasons(body, "seasons_seen"), _seasons(body, "seasons_not_seen")
    if set(seen) & set(not_seen):
        raise ApiError(400, f"season {min(set(seen) & set(not_seen))} is both seen and not seen")
    watch.seasons_seen, watch.seasons_not_seen = seen, not_seen
    _apply_dates(watch, body)
    watch.device = device
    watch.recommended_by = recommended_by
    watch.people = people
    watch.film = film


def _apply_chess_game(game: ChessGame, body: dict[str, Any]) -> None:
    """
    A game is added by its PGN, one game's, and says what it is itself; the
    user says which side they played. Edited, its PGN may be sent again (it
    is read again) or left out. final_position is where the pieces ended,
    worked out by the page, which plays the moves: the server only reads
    them. It is the picture of the user's own card, so it is taken as said.
    A game recorded without its moves (scripts/import_chess_xml.py) has no
    text, and may not know the side the user played; its opponent and how it
    ended stay as recorded. One with its text says both sides, so the user
    says which they played, and whom they played and how it ended are read
    out of it.
    """
    written = body.get("pgn")
    if written is not None and not isinstance(written, str):
        raise ApiError(400, "pgn: expected a string")
    if not (written or "").strip():
        if game.id is None:
            raise ApiError(400, "pgn: required")
    else:
        if len(pgn.split(written or "")) > 1:
            raise ApiError(400, "pgn: one game at a time (scripts/import_chess.py imports a file of them)")
        try:
            read = pgn.parse(written or "")
        except pgn.PgnError as e:
            raise ApiError(400, f"pgn: {e}") from e
        fields = pgn.fields(read)
        clash = flask.g.db.execute(select(ChessGame.id).where(
            ChessGame.owner_id == flask.g.user.id, ChessGame.source_key == fields["source_key"], ChessGame.id != game.id,
        )).first()
        if clash is not None:
            raise ApiError(409, "that game is in your list already")
        for column, value in fields.items():
            setattr(game, column, value)
        game.date_timezone = "UTC" if game.date_utcz is not None else ""
        # where it ended, as the site wrote it; with no move there is no position to show
        game.final_position = read.tags.get("CurrentPosition", "").split(" ")[0] if read.moves else ""
    # else as the page says, which played the moves (it sends it once the game is added)
    position = text(body, "final_position")
    if position:
        game.final_position = position
    if game.final_position and not pgn.POSITION.fullmatch(game.final_position):
        raise ApiError(400, "final_position: expected where the pieces stand, as the first field of a FEN")
    color = text(body, "color")
    if color not in pgn.COLORS:
        raise ApiError(400, "color: white or black, the side you played, or empty where it is not known")
    if not color and game.pgn:
        raise ApiError(400, "color: white or black, the side you played (the game's text says both sides)")
    game.color = color
    if game.pgn:
        game.opponent = pgn.opponent(game.color, game.white, game.black)
        game.outcome = pgn.outcome(game.color, game.result)
    game.remark = text(body, "remark")


def _apply_person(person: Person, body: dict[str, Any]) -> None:
    # two people may share a name, so there is no clash to look for
    # either name, or both, may be missing: someone with no name goes by the
    # description, so it is only a person with none of the three, who could
    # not be picked in any picker, that is refused
    person.honorific = text(body, "honorific")
    person.first_name = text(body, "first_name")
    person.middle_name = " ".join(text(body, "middle_name").split())
    person.surname = text(body, "surname")
    person.description = text(body, "description")
    # one word each; the middle name holds whatever comes between
    for key, value in (("honorific", person.honorific), ("first_name", person.first_name), ("surname", person.surname)):
        if names.has_space(value):
            raise ApiError(400, f"{key}: one word, without spaces (a surname of two words is hyphenated; more names go in the middle name)")
    if not person.first_name and not person.middle_name and not person.surname and not person.description:
        raise ApiError(400, "a person needs a name or a description")
    if "organization_links" in body:
        person.organization_links = _organization_links(person, body["organization_links"])
    elif "organizations" in body:
        person.organization_links = _links_to(person, owned_list(body, "organizations", Organization))
    person.types = owned_list(body, "type_ids", PersonType)
    if "names" in body:
        _apply_person_names(person, body["names"])
    if "photos" in body:
        # all their photos, replacing those they had, in this order: the first is the default
        person.photos = photo_rows(person.photos, PersonPhoto, sent_photos(body["photos"]))
        for position, photo in enumerate(person.photos):
            photo.position = position
    if "relations" in body:
        person.relations = _person_relations(person, body["relations"])


def localized(key: str, value: Any, field: str, one_per_locale: bool) -> list[tuple[str, str]]:
    """
    [{"locale", field}, ...] as (locale, text) pairs, each once: a language
    of the locales table and a text not empty, written in that language's
    script; one_per_locale refuses two in one language.
    """
    locales = languages.known(flask.g.db)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ApiError(400, f"{key}: expected a list of {{locale, {field}}}")
    out: dict[tuple[str, str], None] = {}
    for item in value:
        locale, words = item.get("locale"), item.get(field)
        if locale not in locales:
            raise ApiError(400, f"{key}: unknown language {locale!r}")
        if not isinstance(words, str) or not words.strip():
            raise ApiError(400, f"{key}: a {field} is needed in {locales[locale].name}")
        if not languages.fits(locales[locale], words):
            raise ApiError(400, f"{key}: {words.strip()!r} is not written in {locales[locale].name}: choose the language it is in")
        out[locale, " ".join(words.split())] = None
    pairs = list(out)
    if one_per_locale and len({locale for locale, _ in pairs}) != len(pairs):
        raise ApiError(400, f"{key}: one {field} per language")
    return pairs


NAME_PARTS = ("honorific", "first_name", "middle_name", "surname")


def _apply_person_names(person: Person, value: Any) -> None:
    """
    A person's names in other languages than English, replacing those they
    had (a row kept per language, renamed in place): [{locale, honorific,
    first_name, middle_name, surname}, ...], one per language, each part
    written in that language; or {locale, name}, the whole name, which is
    split into its parts.
    """
    locales = languages.known(flask.g.db)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ApiError(400, "names: expected a list of {locale, honorific, first_name, middle_name, surname}")
    kept = {n.locale: n for n in person.names}
    rows: dict[str, PersonName] = {}
    for item in value:
        locale = item.get("locale")
        if locale not in locales:
            raise ApiError(400, f"names: unknown language {locale!r}")
        if locale == DEFAULT_LOCALE:
            raise ApiError(400, "names: the English name is the person's own name parts")
        if locale in rows:
            raise ApiError(400, "names: one name per language")
        row = kept.get(locale) or PersonName(locale=locale, name="")
        if any(part in item for part in NAME_PARTS):
            honorific, first, middle, surname = (" ".join(text(item, part).split()) for part in NAME_PARTS)
            for key, part in (("honorific", honorific), ("first_name", first), ("surname", surname)):
                if names.has_space(part):
                    raise ApiError(400, f"names: {key}: one word, without spaces (more names go in the middle name)")
            row.set_parts(honorific, first, middle, surname)
        else:
            row.set_whole(text(item, "name"))
        if not row.name:
            raise ApiError(400, f"names: a name is needed in {locales[locale].name}")
        # each part by itself: a surname in other letters does not hide behind the rest
        strange = next((part for part in (row.honorific, row.first_name, row.middle_name, row.surname) if not languages.fits(locales[locale], part)), None)
        if strange is not None:
            raise ApiError(400, f"names: {strange!r} is not written in {locales[locale].name}: choose the language it is in")
        rows[locale] = row
    person.names = list(rows.values())




def _organization_links(person: Person, value: Any) -> list[PersonOrganization]:
    """
    A person's links to organizations from [{"type_id", "organization_id"}, ...]:
    each a person-org relation type and an organization of the user's; one
    already there is kept as it is.
    """
    if not isinstance(value, list) or not all(isinstance(r, dict) for r in value):
        raise ApiError(400, "organization_links: expected a list of {type_id, organization_id}")
    kept = {(link.relation_type_id, link.organization_id): link for link in person.organization_links}
    out: dict[tuple[int, int], PersonOrganization] = {}
    for item in value:
        type_id, organization_id = item.get("type_id"), item.get("organization_id")
        if not all(isinstance(i, int) and not isinstance(i, bool) for i in (type_id, organization_id)):
            raise ApiError(400, "organization_links: type_id and organization_id are ids")
        kind = flask.g.db.get(PersonOrganizationType, type_id)
        if kind is None or kind.owner_id != flask.g.user.id:
            raise ApiError(400, "organization_links: unknown kind of link")
        organization = flask.g.db.get(Organization, organization_id)
        if organization is None or organization.owner_id != flask.g.user.id:
            raise ApiError(400, "organization_links: unknown organization")
        out[type_id, organization_id] = kept.get((type_id, organization_id)) or PersonOrganization(relation_type=kind, organization=organization)
    return list(out.values())


def _links_to(person: Person, organizations: list[Organization]) -> list[PersonOrganization]:
    """
    Links to exactly these organizations, for a client that sends only which:
    the links already there to them are kept, a new one is of the user's
    first kind ("Worked at" when they have it).
    """
    wanted = {o.id for o in organizations}
    links = [link for link in person.organization_links if link.organization_id in wanted]
    linked = {link.organization_id for link in links}
    missing = [o for o in organizations if o.id not in linked]
    if missing:
        kinds = flask.g.db.execute(select(PersonOrganizationType).where(PersonOrganizationType.owner_id == flask.g.user.id)).scalars().all()
        if not kinds:
            raise ApiError(400, "organizations: add a kind of link first (Types, Person-org relations)")
        kind = next((k for k in kinds if k.name == "Worked at"), min(kinds, key=lambda k: k.name))
        links += [PersonOrganization(relation_type=kind, organization=o) for o in missing]
    return links


def _person_relations(person: Person, value: Any) -> list[PersonRelation]:
    """
    A person's own relations from [{"type_id", "person_id"}, ...]: each a
    person relation type and a person of the user's, never the person
    themselves; one already there is kept as it is.
    """
    if not isinstance(value, list) or not all(isinstance(r, dict) for r in value):
        raise ApiError(400, "relations: expected a list of {type_id, person_id}")
    kept = {(r.relation_type_id, r.other_id): r for r in person.relations}
    out: dict[tuple[int, int], PersonRelation] = {}
    for item in value:
        type_id, other_id = item.get("type_id"), item.get("person_id")
        if not all(isinstance(i, int) and not isinstance(i, bool) for i in (type_id, other_id)):
            raise ApiError(400, "relations: type_id and person_id are ids")
        kind = flask.g.db.get(PersonRelationType, type_id)
        if kind is None or kind.owner_id != flask.g.user.id:
            raise ApiError(400, "relations: unknown relation type")
        other = flask.g.db.get(Person, other_id)
        if other is None or other.owner_id != flask.g.user.id:
            raise ApiError(400, "relations: unknown person")
        if other_id == person.id:
            raise ApiError(400, "relations: a person is not related to themselves")
        out[type_id, other_id] = kept.get((type_id, other_id)) or PersonRelation(relation_type=kind, other=other)
    return list(out.values())


def _apply_organization(organization: Organization, body: dict[str, Any]) -> None:
    name = text(body, "name", required=True)
    clash = flask.g.db.execute(
        select(Organization.id).where(Organization.owner_id == flask.g.user.id, Organization.name == name, Organization.id != organization.id)
    ).first()
    if clash is not None:
        raise ApiError(409, f"{name} is already in Organizations")
    organization.name = name
    # looked up before anything is set on a new organization, which is not in the session yet
    types = owned_list(body, "type_ids", OrganizationType)
    relations = owned_list(body, "relation_ids", RelationType)
    organization.types = types
    organization.relations = relations
    organization.status = text(body, "status")
    organization.website = text(body, "website")
    organization.location = text(body, "location")
    organization.city = owned_ref(body, "city_id", City, "city")
    organization.headquarters = owned_ref(body, "headquarters_id", City, "city")
    _apply_address(organization, body)
    organization.latitude, organization.longitude = coordinates(body)
    organization.what_happened = text(body, "what_happened")
    organization.remark = text(body, "remark")
    apply_image(organization, body)


# ─── the routes that add, edit and delete ───────────────────────────────────

@dataclasses.dataclass(frozen=True)
class _View:
    """ What the routes below need of a view: its rows, how a request body is applied to one, and what one looks like as JSON. """
    model: type[Any]
    apply: Callable[[Any, dict[str, Any]], None]
    json: Callable[[Any], dict[str, Any]]


# the path of a view (/api/<path>) -> the view
# (museum-visits, a museum with the user's visits to it, has routes of its own above)
VIEWS: dict[str, _View] = {
    "concert-visits": _View(Concert, _apply_concert, concert_json),
    "audio-courses": _View(AudioCourse, _apply_audio_course, audio_course_json),
    "audio-books": _View(AudioBook, _apply_audio_book, audio_book_json),
    "audio-book-versions": _View(AudioBookVersion, _apply_audio_book_version, audio_book_version_json),
    "audio-books-heard": _View(AudioBookHeard, _apply_audio_book_heard, audio_book_heard_json),
    "audio-book-listens": _View(AudioBookListen, _apply_audio_book_listen, audio_book_listen_json),
    "podcasts": _View(Podcast, _apply_podcast, podcast_json),
    "podcast-episodes": _View(PodcastEpisode, _apply_podcast_episode, podcast_episode_json),
    "podcasts-heard": _View(PodcastHeard, _apply_podcast_heard, podcast_heard_json),
    "episodes-heard": _View(EpisodeHeard, _apply_episode_heard, episode_heard_json),
    "films": _View(Film, _apply_film, film_json),
    "film-watches": _View(FilmWatch, _apply_film_watch, film_watch_json),
    # the same rows, of the kind series
    "series": _View(Film, _apply_series, film_json),
    "series-watches": _View(FilmWatch, _apply_film_watch, film_watch_json),
    "youtube-videos": _View(YouTubeVideo, _apply_youtube_video, youtube_video_json),
    "chess-games": _View(ChessGame, _apply_chess_game, chess_game_json),
    "people": _View(Person, _apply_person, person_json),
    "organizations": _View(Organization, _apply_organization, organization_json),
    "places": _View(Place, _apply_place, place_json),
    "groups": _View(Group, _apply_group, group_json),
    "cities": _View(City, _apply_city, city_json),
    "countries": _View(Country, _apply_country, country_json),
    "currencies": _View(Currency, _apply_currency, currency_json),
    "place-kinds": _View(PlaceKind, _apply_named(PlaceKind, "Place kinds"), place_kind_json),
    "visit-types": _View(VisitType, _apply_named(VisitType, "Visit types"), visit_type_json),
}


@bp.route("/api/<any('place-kinds', 'visit-types'):what>", methods=["GET"])
@auth.login_required
def api_shared_names(what: str) -> flask.Response:
    view = VIEWS[what]
    rows = flask.g.db.scalars(select(view.model).order_by(view.model.name))
    return flask.jsonify([view.json(row) for row in rows])


def _may_change(model: type[Any]) -> None:
    """ A shared row is everyone's: only an admin with Edit shared data turned on adds, changes or deletes one. """
    if is_shared(model):
        require_edit_shared()


def drop_unused_regions() -> None:
    """ A region no city says any more (its last city moved, or was deleted) goes too. """
    used = select(City.region_id).where(City.region_id.is_not(None))
    for region in flask.g.db.scalars(select(Region).where(Region.id.not_in(used))):
        flask.g.db.delete(region)


# the paths, as the part of a route that takes any of them
WHAT = f"<any({', '.join(repr(path) for path in VIEWS)}):what>"


@bp.route(f"/api/{WHAT}", methods=["POST"])
@auth.login_required
def api_world_add(what: str) -> tuple[flask.Response, int]:
    view = VIEWS[what]
    _may_change(view.model)
    row = view.model() if is_shared(view.model) else view.model(owner_id=flask.g.user.id)
    view.apply(row, json_body())
    flask.g.db.add(row)
    flask.g.db.commit()
    return flask.jsonify(view.json(row)), 201


@bp.route(f"/api/{WHAT}/<int:row_id>", methods=["PUT"])
@auth.login_required
def api_world_update(what: str, row_id: int) -> flask.Response:
    view = VIEWS[what]
    _may_change(view.model)
    row = owned(view.model, row_id)
    view.apply(row, json_body())
    # a picture taken away or replaced goes, with its image; so does a region no city says any more
    flask.g.db.flush()
    drop_unused_images()
    drop_unused_regions()
    flask.g.db.commit()
    return flask.jsonify(view.json(row))


@bp.route(f"/api/{WHAT}/<int:row_id>", methods=["DELETE"])
@auth.login_required
def api_world_delete(what: str, row_id: int) -> flask.Response:
    # the ORM also removes the row's links (to people, to organizations, to concerts and museums);
    # the concerts at a deleted place are kept, with no place
    _may_change(VIEWS[what].model)
    row = owned(VIEWS[what].model, row_id)
    # what someone heard stays: a podcast someone listens to, an episode someone heard, a podcast heard with episodes heard
    if isinstance(row, Podcast) and row.heard:
        raise ApiError(409, f"{row.name} is listened to (Podcasts heard): it stays")
    if isinstance(row, PodcastEpisode) and row.heard:
        raise ApiError(409, f"{row.name} was heard (Episodes heard): it stays")
    if isinstance(row, PodcastHeard) and _heard_of(row):
        raise ApiError(409, f"you heard {_heard_of(row)} episodes of {row.podcast.name}: delete them first")
    # and so does an audio book someone heard, a version someone heard, a book heard with listens
    if isinstance(row, AudioBook) and (row.heard or any(v.listens for v in row.versions)):
        raise ApiError(409, f"{row.name} was heard (Audio book listens): it stays")
    if isinstance(row, AudioBookVersion) and row.listens:
        raise ApiError(409, f"{version_name(row)} was heard (Audio book listens): it stays")
    # and so does a film someone watched
    if isinstance(row, Film) and row.watches:
        raise ApiError(409, f"{row.name} was watched ({'Series' if row.kind == 'series' else 'Film'} watches): it stays")
    if isinstance(row, AudioBookHeard) and _listens_of(row):
        raise ApiError(409, f"you heard {row.book.name} ({_listens_of(row)} listens): delete them first")
    flask.g.db.delete(row)
    flask.g.db.flush()
    drop_unused_images()
    drop_unused_regions()
    flask.g.db.commit()
    return flask.Response(status=204)
