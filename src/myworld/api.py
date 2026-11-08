"""
What every JSON endpoint shares: the error that becomes a {"error": ...}
answer, and the readers that validate fields of a request body.
"""

import datetime
from typing import Any

import flask


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


def opt_date(body: dict[str, Any], key: str) -> datetime.date | None:
    value = text(body, key)
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as e:
        raise ApiError(400, f"{key}: expected a date as YYYY-MM-DD") from e
