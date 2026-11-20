"""
Importers: what brings a user's data in from elsewhere (their YouTube
playlists, ...), run from the Imports page with parameters of their own.
Any of them may be run again whenever: a row is added only once, and what
the user wrote is never changed (see core). Every run is kept
(models.ImportRun), and a dry run says what a run would do and keeps
nothing else.

An importer is a module here that registers one (core.register): the page
and its API (myworld.imports) pick it up.
"""

import importlib

from myworld.importers.core import (
    IMPORTERS,
    Importer,
    ImporterError,
    Param,
    ParamError,
    Report,
    parse_params,
    register,
    run,
    run_json,
)

# a module registers its importer as it is imported; the page lists them in this order
for _module in ("youtube_playlists",):
    importlib.import_module(f"myworld.importers.{_module}")

__all__ = ["IMPORTERS", "Importer", "ImporterError", "Param", "ParamError", "Report", "parse_params", "register", "run", "run_json"]
