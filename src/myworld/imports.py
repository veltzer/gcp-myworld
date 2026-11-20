"""
The Imports page's API: the importers there are (myworld.importers), each
with its parameters and what may be chosen for them, running one, and the
signed-in user's last runs. Every user imports into their own data only.
"""

from typing import Any

import flask
from sqlalchemy import select

from myworld import auth, importers, youtube
from myworld.api import ApiError, json_body
from myworld.checks import DATASETS
from myworld.models import ImportRun

bp = flask.Blueprint("imports", __name__)

# how many of a user's runs the page lists
RUNS_SHOWN = 20


def _param_json(param: importers.Param, unavailable: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": param.name, "title": param.title, "kind": param.kind,
        "description": param.description, "required": param.required,
        "choices": [], "error": "",
    }
    # the choices are asked of the source only when the importer can run
    if param.choices is not None and not unavailable:
        try:
            out["choices"] = [{"value": value, "label": label} for value, label in param.choices(flask.g.db, flask.g.user)]
        except importers.ImporterError as e:
            out["error"] = str(e)
    return out


@bp.route("/api/importers", methods=["GET"])
@auth.login_required
def api_importers() -> flask.Response:
    out = []
    for importer in importers.IMPORTERS.values():
        unavailable = importer.unavailable(flask.g.db, flask.g.user)
        out.append({
            "name": importer.name,
            "title": importer.title,
            "description": importer.description,
            "dataset": importer.dataset,
            "dataset_name": DATASETS[importer.dataset],
            "unavailable": unavailable,
            "params": [_param_json(param, unavailable) for param in importer.params],
        })
    return flask.jsonify({"importers": out, "youtube": youtube.status_json(flask.g.db, flask.g.user)})


@bp.route("/api/importers/<name>/runs", methods=["POST"])
@auth.login_required
def api_run(name: str) -> flask.Response:
    """ Run an importer: {"params": {...}, "dry_run": true|false}. The run is answered whether it was done or failed. """
    importer = importers.IMPORTERS.get(name)
    if importer is None:
        raise ApiError(404, f"no importer called {name}")
    body = json_body()
    dry_run = body.get("dry_run", False)
    if not isinstance(dry_run, bool):
        raise ApiError(400, "dry_run: expected true or false")
    try:
        record = importers.run(flask.g.db, flask.g.user, importer, body.get("params") or {}, dry_run)
    except importers.ParamError as e:
        raise ApiError(400, str(e)) from e
    except importers.ImporterError as e:
        # the choices could not be read to check the parameters against
        raise ApiError(409, str(e)) from e
    return flask.jsonify(importers.run_json(record))


@bp.route("/api/import-runs", methods=["GET"])
@auth.login_required
def api_runs() -> flask.Response:
    """ The signed-in user's last runs, newest first. """
    records = flask.g.db.scalars(
        select(ImportRun).where(ImportRun.owner_id == flask.g.user.id).order_by(ImportRun.id.desc()).limit(RUNS_SHOWN)
    )
    return flask.jsonify([importers.run_json(r) for r in records])
