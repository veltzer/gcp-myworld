"""
Film lookups for the "add a film" form: search The Movie Database (TMDB)
by title, then fetch one film's details normalised to what the library
stores (title, director, year) plus its ids on IMDb, TMDB and Rotten
Tomatoes.

TMDB knows the IMDb and Wikidata ids of a film but not the Rotten Tomatoes
one; Wikidata does (property P1258), so the details call follows the
Wikidata id when TMDB gives one. Needs TMDB_API_KEY (a v3 API key); the
Wikidata call is anonymous.

What TMDB says of a film or series by its IMDb id (tmdb_find: its id there,
the year it came out or started, its poster) fills in what Wikidata does
not have, when the key is there. What Wikidata says of films by their IMDb ids (wikidata_films: the item,
the English title, the year, the directors) fills in the films the
importer brings that it has no more than an IMDb id of.
"""

import os
import re
from typing import Any

import requests

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMAGES = "https://image.tmdb.org/t/p/w92"
# a poster as the importer keeps it: wide enough for a card
TMDB_POSTERS = "https://image.tmdb.org/t/p/w500"
WIKIDATA_ENTITY = "https://www.wikidata.org/wiki/Special:EntityData"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
ROTTEN_TOMATOES_PROPERTY = "P1258"
HTTP_TIMEOUT = 10
USER_AGENT = "myworld/0.0.1 (https://github.com/veltzer/gcp-myworld)"


def api_key() -> str:
    return os.environ.get("TMDB_API_KEY", "")


def configured() -> bool:
    return bool(api_key())


class MovieLookupError(Exception):
    """ TMDB or Wikidata did not answer usefully. """


def tmdb_get(path: str, **params: str) -> dict[str, Any]:
    """ One TMDB call; the tests replace this. """
    response = requests.get(
        f"{TMDB_API}{path}",
        params={"api_key": api_key(), **params},
        headers={"User-Agent": USER_AGENT},
        timeout=HTTP_TIMEOUT,
    )
    if not response.ok:
        raise MovieLookupError(f"TMDB answered {response.status_code}")
    data = response.json()
    if not isinstance(data, dict):
        raise MovieLookupError("TMDB answered something that is not an object")
    return data


def wikidata_entity(qid: str) -> dict[str, Any]:
    """ The claims of one Wikidata item; the tests replace this. """
    response = requests.get(
        f"{WIKIDATA_ENTITY}/{qid}.json",
        headers={"User-Agent": USER_AGENT},
        timeout=HTTP_TIMEOUT,
    )
    if not response.ok:
        raise MovieLookupError(f"Wikidata answered {response.status_code}")
    claims: dict[str, Any] = response.json().get("entities", {}).get(qid, {})
    return claims


def _year(release_date: str | None) -> int | None:
    if release_date and len(release_date) >= 4 and release_date[:4].isdigit():
        return int(release_date[:4])
    return None


def _poster(path: str | None) -> str:
    return f"{TMDB_IMAGES}{path}" if path else ""


def search(query: str) -> list[dict[str, Any]]:
    """ Candidate films for a title, most relevant first, enough to pick the right one. """
    data = tmdb_get("/search/movie", query=query, include_adult="false")
    return [
        {
            "tmdb_id": movie["id"],
            "title": movie.get("title") or "",
            "original_title": movie.get("original_title") or "",
            "year": _year(movie.get("release_date")),
            "overview": (movie.get("overview") or "")[:300],
            "poster": _poster(movie.get("poster_path")),
        }
        for movie in data.get("results", [])[:10]
    ]


def rotten_tomatoes_id(wikidata_id: str) -> str:
    """ The Rotten Tomatoes id (like "m/dune_2021") of a Wikidata item, or "" if it has none. """
    try:
        claims = wikidata_entity(wikidata_id).get("claims", {})
        for claim in claims.get(ROTTEN_TOMATOES_PROPERTY, []):
            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(value, str) and value:
                return value
    except (MovieLookupError, requests.RequestException, ValueError):
        # best effort: a film without a Rotten Tomatoes id is still a film
        pass
    return ""


def details(tmdb_id: int) -> dict[str, Any]:
    """ Everything the add form needs for one film. """
    movie = tmdb_get(f"/movie/{tmdb_id}", append_to_response="credits,external_ids")
    directors = [c.get("name", "") for c in movie.get("credits", {}).get("crew", []) if c.get("job") == "Director"]
    external = movie.get("external_ids", {})
    wikidata_id = external.get("wikidata_id") or ""
    return {
        "tmdb_id": movie["id"],
        "title": movie.get("title") or "",
        "original_title": movie.get("original_title") or "",
        "creator": ", ".join(d for d in directors if d),
        "year": _year(movie.get("release_date")),
        "overview": movie.get("overview") or "",
        "poster": _poster(movie.get("poster_path")),
        "runtime": movie.get("runtime"),
        "genres": [g.get("name", "") for g in movie.get("genres", [])],
        "imdb_id": external.get("imdb_id") or "",
        "wikidata_id": wikidata_id,
        "rotten_tomatoes_id": rotten_tomatoes_id(wikidata_id) if wikidata_id else "",
    }


# a film by its IMDb id (P345): its English title (or the one in every
# language, "mul", which Wikidata keeps instead for many), the year it came out
# (P577; a series, the year it started, P580) and its directors (P57)
FILMS_QUERY = """
SELECT ?imdb ?item ?itemLabel (MIN(YEAR(COALESCE(?date, ?start))) AS ?year) (GROUP_CONCAT(DISTINCT ?directorLabel; separator=", ") AS ?directors) WHERE {
  VALUES ?imdb { %s }
  ?item wdt:P345 ?imdb.
  OPTIONAL { ?item wdt:P577 ?date. }
  OPTIONAL { ?item wdt:P580 ?start. }
  OPTIONAL { ?item wdt:P57 ?director. }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,mul". ?item rdfs:label ?itemLabel. ?director rdfs:label ?directorLabel. }
}
GROUP BY ?imdb ?item ?itemLabel
"""
IMDB_ID = re.compile(r"tt\d{7,9}")
# how many films one query asks about
FILMS_PER_QUERY = 100


def sparql(query: str) -> list[dict[str, str]]:
    """ The rows a Wikidata query answers, each its variables' values; the tests replace this. """
    response = requests.get(
        WIKIDATA_SPARQL, params={"query": query, "format": "json"}, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT * 3,
    )
    if not response.ok:
        raise MovieLookupError(f"Wikidata answered {response.status_code}")
    return [{key: value["value"] for key, value in row.items()} for row in response.json()["results"]["bindings"]]


def wikidata_films(imdb_ids: list[str]) -> dict[str, dict[str, Any]]:
    """
    What Wikidata says of the films of imdb_ids ("tt0816692"): IMDb id ->
    its item ("Q13417189"), title, year (None when not said) and directors
    ("Joel Coen, Ethan Coen"). A film Wikidata does not know is left out.
    """
    wanted = sorted(set(imdb_ids))
    for imdb in wanted:
        if not IMDB_ID.fullmatch(imdb):
            raise MovieLookupError(f"{imdb!r} is not an IMDb id")
    found: dict[str, dict[str, Any]] = {}
    for start in range(0, len(wanted), FILMS_PER_QUERY):
        values = " ".join(f'"{imdb}"' for imdb in wanted[start:start + FILMS_PER_QUERY])
        for row in sparql(FILMS_QUERY % values):
            qid = row["item"].rsplit("/", 1)[-1]
            # an item with no English title is labelled by its id: no title then
            title = row.get("itemLabel", "")
            year = row.get("year", "")
            # two items with one IMDb id (rare): the first is kept
            found.setdefault(row["imdb"], {
                "wikidata_id": qid,
                "title": "" if title == qid else title,
                "year": int(year) if year.isdigit() else None,
                "directors": ", ".join(d for d in row.get("directors", "").split(", ") if d and not re.fullmatch(r"Q\d+", d)),
            })
    return found


def tmdb_find(imdb: str) -> dict[str, Any] | None:
    """
    What TMDB says of the film or series of an IMDb id ("tt0816692"): its id
    there, whether it is a series, the year it came out (a series, started)
    and its poster's address ("" when it has none); None when TMDB does not
    know it.
    """
    if not IMDB_ID.fullmatch(imdb):
        raise MovieLookupError(f"{imdb!r} is not an IMDb id")
    data = tmdb_get(f"/find/{imdb}", external_source="imdb_id")
    series = data.get("tv_results") or []
    found = (series or data.get("movie_results") or [None])[0]
    if not isinstance(found, dict):
        return None
    poster = found.get("poster_path")
    return {
        "tmdb_id": found["id"],
        "series": bool(series),
        "year": _year(found.get("first_air_date") or found.get("release_date")),
        "poster_url": f"{TMDB_POSTERS}{poster}" if poster else "",
    }


def poster_bytes(url: str) -> bytes:
    """ A poster's image (JPEG); the tests replace this. """
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT)
    if not response.ok:
        raise MovieLookupError(f"TMDB's images answered {response.status_code}")
    if not response.content.startswith(b"\xff\xd8"):
        raise MovieLookupError(f"{url} is not a JPEG image")
    return response.content
