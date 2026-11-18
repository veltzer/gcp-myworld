"""
The readers of a request body (myworld/api.py): each takes a field of a JSON
object and gives its value, or refuses it with an ApiError that says which
field and why.
"""

import datetime
from typing import Any

import pytest

from myworld.api import ApiError, coordinates, opt_date, opt_float, opt_int, text


def refused(call: Any, *args: Any) -> tuple[int, str]:
    with pytest.raises(ApiError) as caught:
        call(*args)
    return caught.value.status, caught.value.message


@pytest.mark.parametrize(("body", "wanted"), [
    ({"name": "  Dune  "}, "Dune"),
    ({"name": ""}, ""),
    ({"name": None}, ""),
    ({}, ""),
    ({"name": "\tDune\n"}, "Dune"),
])
def test_text(body: dict[str, Any], wanted: str) -> None:
    assert text(body, "name") == wanted


@pytest.mark.parametrize("value", [3, 3.5, True, ["Dune"], {"a": 1}])
def test_text_is_a_string(value: Any) -> None:
    assert refused(text, {"name": value}, "name") == (400, "name: expected a string")


@pytest.mark.parametrize("body", [{}, {"name": None}, {"name": ""}, {"name": "   "}])
def test_text_required(body: dict[str, Any]) -> None:
    with pytest.raises(ApiError) as caught:
        text(body, "name", required=True)
    assert (caught.value.status, caught.value.message) == (400, "name: required")


@pytest.mark.parametrize(("value", "wanted"), [(7, 7), ("7", 7), (" 7 ", 7), (1, 1), (10, 10), (None, None), ("", None)])
def test_opt_int(value: Any, wanted: int | None) -> None:
    assert opt_int({"rating": value}, "rating", 1, 10) == wanted
    assert opt_int({}, "rating", 1, 10) is None


@pytest.mark.parametrize("value", [True, False, 7.5, "seven", "7.5", [7], {"n": 7}])
def test_opt_int_is_a_number(value: Any) -> None:
    assert refused(opt_int, {"rating": value}, "rating", 1, 10) == (400, "rating: expected a number")


@pytest.mark.parametrize("value", [0, 11, -3, "0", "11"])
def test_opt_int_has_bounds(value: Any) -> None:
    assert refused(opt_int, {"rating": value}, "rating", 1, 10) == (400, "rating: must be between 1 and 10")


@pytest.mark.parametrize(("value", "wanted"), [(32.07, 32.07), ("32.07", 32.07), (32, 32.0), (-90, -90.0), (90, 90.0), (None, None), ("", None)])
def test_opt_float(value: Any, wanted: float | None) -> None:
    assert opt_float({"latitude": value}, "latitude", -90, 90) == wanted


@pytest.mark.parametrize(("value", "message"), [
    (True, "latitude: expected a number"),
    ("north", "latitude: expected a number"),
    ([32.07], "latitude: expected a number"),
    (90.01, "latitude: must be between -90 and 90"),
    ("-91", "latitude: must be between -90 and 90"),
])
def test_opt_float_refuses(value: Any, message: str) -> None:
    assert refused(opt_float, {"latitude": value}, "latitude", -90, 90) == (400, message)


def test_coordinates_are_both_or_neither() -> None:
    assert coordinates({"latitude": 32.07, "longitude": "34.78"}) == (32.07, 34.78)
    assert coordinates({}) == (None, None)
    assert coordinates({"latitude": "", "longitude": None}) == (None, None)
    for body in ({"latitude": 32.07}, {"longitude": 34.78}, {"latitude": 32.07, "longitude": ""}):
        assert refused(coordinates, body) == (400, "latitude and longitude: give both or neither")
    assert refused(coordinates, {"latitude": 32.07, "longitude": 181}) == (400, "longitude: must be between -180 and 180")


def test_opt_date() -> None:
    assert opt_date({"on": "2003-07-14"}, "on") == datetime.date(2003, 7, 14)
    assert opt_date({"on": " 2003-07-14 "}, "on") == datetime.date(2003, 7, 14)
    assert opt_date({"on": ""}, "on") is None
    assert opt_date({}, "on") is None
    for value in ("2003", "2003-07", "14/07/2003", "2003-02-30", "yesterday"):
        assert refused(opt_date, {"on": value}, "on") == (400, "on: expected a date as YYYY-MM-DD")
    assert refused(opt_date, {"on": 20030714}, "on") == (400, "on: expected a string")
