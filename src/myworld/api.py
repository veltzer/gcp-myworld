"""
What every JSON endpoint shares: the error that becomes a {"error": ...}
answer, the readers that validate fields of a request body, and the ones
that turn the ids it sends into rows of the signed-in user.
"""

import datetime
from typing import Any

import flask
from sqlalchemy import select


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def handle_api_error(error: ApiError) -> tuple[flask.Response, int]:
    return flask.jsonify({"error": error.message}), error.status


def json_body() -> dict[str, Any]:
    body = flask.request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(400, "expected a JSON object")
    return body


def text(body: dict[str, Any], key: str, required: bool = False) -> str:
    value = body.get(key)
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ApiError(400, f"{key}: expected a string")
    value = value.strip()
    if required and not value:
        raise ApiError(400, f"{key}: required")
    return value


def opt_int(body: dict[str, Any], key: str, low: int, high: int) -> int | None:
    value = body.get(key)
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ApiError(400, f"{key}: expected a number")
    try:
        number = int(value)
    except ValueError as e:
        raise ApiError(400, f"{key}: expected a number") from e
    if number < low or number > high:
        raise ApiError(400, f"{key}: must be between {low} and {high}")
    return number


def opt_float(body: dict[str, Any], key: str, low: float, high: float) -> float | None:
    value = body.get(key)
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ApiError(400, f"{key}: expected a number")
    try:
        number = float(value)
    except ValueError as e:
        raise ApiError(400, f"{key}: expected a number") from e
    if not low <= number <= high:
        raise ApiError(400, f"{key}: must be between {low:g} and {high:g}")
    return number


def coordinates(body: dict[str, Any]) -> tuple[float | None, float | None]:
    """ latitude and longitude: both, or neither. """
    latitude = opt_float(body, "latitude", -90, 90)
    longitude = opt_float(body, "longitude", -180, 180)
    if (latitude is None) != (longitude is None):
        raise ApiError(400, "latitude and longitude: give both or neither")
    return latitude, longitude


def opt_date(body: dict[str, Any], key: str) -> datetime.date | None:
    value = text(body, key)
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as e:
        raise ApiError(400, f"{key}: expected a date as YYYY-MM-DD") from e


def owned[T](model: type[T], row_id: int) -> T:
    """ The user's own row row_id of model: the one an address names (404 when it is not theirs). """
    row: Any = flask.g.db.get(model, row_id)
    if row is None or row.owner_id != flask.g.user.id:
        raise ApiError(404, "no such entry")
    return row


def owned_ref[T](body: dict[str, Any], key: str, model: type[T], what: str) -> T | None:
    """ body[key], the id of one of the user's own rows of model (what names it in the error), as that row; None when none is sent. """
    row_id = opt_int(body, key, 1, 2**31 - 1)
    if row_id is None:
        return None
    row: Any = flask.g.db.get(model, row_id)
    if row is None or row.owner_id != flask.g.user.id:
        raise ApiError(400, f"{key}: unknown {what}")
    return row


def owned_list[T](body: dict[str, Any], key: str, model: type[T]) -> list[T]:
    """ body[key], a list of ids of the user's own rows of model, as those rows. """
    ids = body.get(key) or []
    if not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        raise ApiError(400, f"{key}: expected a list of ids")
    if not ids:
        return []
    table: Any = model
    rows = flask.g.db.execute(
        select(table).where(table.owner_id == flask.g.user.id, table.id.in_(ids))
    ).scalars().all()
    if len(rows) != len(set(ids)):
        raise ApiError(400, f"{key}: unknown {model.__name__.lower()}")
    return list(rows)
