"""
Film lookups for the "add a film" form: search The Movie Database (TMDB)
by title, then fetch one film's details normalised to what the library
stores (title, director, year) plus its ids on IMDb, TMDB and Rotten
Tomatoes.

TMDB knows the IMDb and Wikidata ids of a film but not the Rotten Tomatoes
one; Wikidata does (property P1258), so the details call follows the
Wikidata id when TMDB gives one. Needs TMDB_API_KEY (a v3 API key); the
Wikidata call is anonymous.
"""

import os
from typing import Any

import requests

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMAGES = "https://image.tmdb.org/t/p/w92"
WIKIDATA_ENTITY = "https://www.wikidata.org/wiki/Special:EntityData"
ROTTEN_TOMATOES_PROPERTY = "P1258"
HTTP_TIMEOUT = 10
USER_AGENT = "myworld/0.0.1 (https://github.com/veltzer/myworld)"


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
    return response.json().get("entities", {}).get(qid, {})


def _year(release_date: str | None) -> int | None:
    if release_date and len(release_date) >= 4 and release_date[:4].isdigit():
        return int(release_date[:4])
    return None


def _poster(path: str | None) -> str:
    return f"{TMDB_IMAGES}{path}" if path else ""


def search(query: str) -> list[dict[str, Any]]:
    """ Candidate films for a title, most relevant first, enough to pick the right one. """
    data = tmdb_get("/search/movie", query=query, include_adult="false")
    results = []
    for movie in data.get("results", [])[:10]:
        results.append({
            "tmdb_id": movie["id"],
            "title": movie.get("title") or "",
            "original_title": movie.get("original_title") or "",
            "year": _year(movie.get("release_date")),
            "overview": (movie.get("overview") or "")[:300],
            "poster": _poster(movie.get("poster_path")),
        })
    return results


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
