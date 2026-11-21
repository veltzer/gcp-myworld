"""
Importers: what brings a user's data in from elsewhere (their YouTube
playlists, ...) or brings everyone's shared data (the countries,
currencies, languages and cities of the world: locale), run from the
Imports page with parameters of their own. Only admins see and run one that
writes the shared data (core.for_admins).
Any of them may be run again whenever: a row is added only once, and what
the user wrote is never changed (see core). Every run is kept
(models.ImportRun), and a dry run says what a run would do and keeps
nothing else.

A run is done by a job of its own, not by the request that asks for it
(core.start, core.execute; on Cloud Run, a Cloud Run Jobs execution: jobs,
worker).

An importer is a module here that registers one (core.register): the page
and its API (myworld.imports) pick it up.
"""

import importlib

from myworld.importers.core import (
    IMPORTERS,
    Importer,
    ImporterError,
    LimitError,
    Param,
    ParamError,
    Report,
    ended,
    execute,
    for_admins,
    parse_params,
    register,
    run_json,
    runs_allowed,
    runs_used,
    settle,
    start,
    visible,
)

# a module registers its importer as it is imported; the page lists them in this order
for _module in ("youtube_playlists", "youtube_details", "audible_library", "locale", "sleep"):
    importlib.import_module(f"myworld.importers.{_module}")

__all__ = [
    "IMPORTERS", "Importer", "ImporterError", "LimitError", "Param", "ParamError", "Report", "ended", "execute", "for_admins",
    "parse_params", "register", "run_json", "runs_allowed", "runs_used", "settle", "start", "visible",
]
