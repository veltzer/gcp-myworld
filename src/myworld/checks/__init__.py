"""
Checks over the whole database, of every account: rules the data should
follow that the app does not enforce when it is written (an SVG logo
inserted with SQL, say). An admin runs them from the Checks page
(GET /api/checks), and scripts/check.py runs the same ones from the
command line, so both always agree.

A check is a function from a database session to a Result, registered
with @check: one more is one function in the module of its page here, and both the page and the
script pick it up. A check only reads; it never changes anything.
"""

import importlib

from myworld.checks.core import (
    CHECKS,
    DATASETS,
    PROBLEMS_SHOWN,
    Check,
    Problem,
    Result,
    check,
    result_json,
)
from myworld.checks.organizations import logo_problems

# a module registers its checks as it is imported; a page lists its checks in this order
for _module in (
    "organizations", "people", "museums", "audio_courses", "library", "concerts", "enumerations",
    "groups", "places", "cities", "countries", "shared_names", "locales", "youtube", "chess", "common",
):
    importlib.import_module(f"myworld.checks.{_module}")

__all__ = ["CHECKS", "DATASETS", "PROBLEMS_SHOWN", "Check", "Problem", "Result", "check", "logo_problems", "result_json"]
