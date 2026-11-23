"""
The Imports page's API: the importers there are (myworld.importers), each
with its parameters and what may be chosen for them, starting a run (a job
of its own does it: the answer is the run, queued), and the runs: running
ones and the last that ended. Every user imports into their own data only,
and sees their own runs; an admin sees everyone's, with whose they are.
A regular user may start so many runs a month (core.runs_allowed).
"""

from typing import Any

import flask
from sqlalchemy import delete, select

from myworld import audible, auth, gcalendar, goodreads, importers, youtube
from myworld.api import ApiError, json_body
from myworld.checks import DATASETS
from myworld.importers import jobs
from myworld.models import IMPORT_ENDED, ROLE_ADMIN, ImportRun, User

bp = flask.Blueprint("imports", __name__)

# how many of the runs that ended the page lists (every running one is listed)
RUNS_SHOWN = 20


def _limit_json() -> dict[str, Any]:
    """ How many runs the user started this month, and may: allowed is None for no limit. """
    return {"used": importers.runs_used(flask.g.db, flask.g.user), "allowed": importers.runs_allowed(flask.g.user)}


def _last_params(importer: importers.Importer) -> dict[str, Any]:
    """ The parameters of the user's last run of importer (dry or not): what the page starts from. """
    last = flask.g.db.scalars(
        select(ImportRun).where(ImportRun.owner_id == flask.g.user.id, ImportRun.importer == importer.name).order_by(ImportRun.id.desc()).limit(1)
    ).first()
    return last.params if last is not None and isinstance(last.params, dict) else {}


def _param_json(param: importers.Param, unavailable: str, last: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": param.name, "title": param.title, "kind": param.kind,
        "description": param.description, "required": param.required,
        "single": param.single, "choices": [], "chosen": [], "error": "",
    }
    # the choices are asked of the source only when the importer can run
    if param.choices is not None and not unavailable:
        try:
            out["choices"] = [{"value": value, "label": label} for value, label in param.choices(flask.g.db, flask.g.user)]
        except importers.ImporterError as e:
            out["error"] = str(e)
    # what was chosen the last time, of what may be chosen now (a playlist deleted since is not)
    values = {choice["value"] for choice in out["choices"]}
    remembered = last.get(param.name)
    if isinstance(remembered, list):
        out["chosen"] = [value for value in remembered if value in values]
    return out


@bp.route("/api/importers", methods=["GET"])
@auth.login_required
def api_importers() -> flask.Response:
    out = []
    for importer in importers.IMPORTERS.values():
        if not importers.visible(importer, flask.g.user):
            continue
        unavailable = importer.unavailable(flask.g.db, flask.g.user)
        out.append({
            "name": importer.name,
            "title": importer.title,
            "description": importer.description,
            "dataset": importer.dataset,
            "dataset_name": DATASETS[importer.dataset] if importer.dataset else "",
            "admin_only": importer.admin_only,
            # it writes the shared data, everyone's (only admins see it)
            "shared": importer.shared,
            # the page lists it with the admins' importers
            "for_admins": importers.for_admins(importer),
            "unavailable": unavailable,
            "params": [_param_json(param, unavailable, _last_params(importer)) for param in importer.params],
        })
    return flask.jsonify({"importers": out, "youtube": youtube.status_json(flask.g.db, flask.g.user),
                          "audible": audible.status_json(flask.g.db, flask.g.user),
                          "calendar": gcalendar.status_json(flask.g.db, flask.g.user),
                          "goodreads": goodreads.status_json(flask.g.db, flask.g.user), "limit": _limit_json()})


@bp.route("/api/importers/<name>/runs", methods=["POST"])
@auth.login_required
def api_run(name: str) -> flask.Response:
    """
    Start a run of an importer: {"params": {...}, "dry_run": true|false}.
    The answer (202) is the run, queued (or failed, when its job could not
    be started); GET /api/import-runs says how it goes.
    """
    importer = importers.IMPORTERS.get(name)
    if importer is None or not importers.visible(importer, flask.g.user):
        raise ApiError(404, f"no importer called {name}")
    body = json_body()
    dry_run = body.get("dry_run", False)
    if not isinstance(dry_run, bool):
        raise ApiError(400, "dry_run: expected true or false")
    dispatch = jobs.dispatcher(flask.current_app.config["engine"])
    try:
        record = importers.start(flask.g.db, flask.g.user, importer, body.get("params") or {}, dry_run, dispatch)
    except importers.ParamError as e:
        raise ApiError(400, str(e)) from e
    except importers.LimitError as e:
        raise ApiError(429, str(e)) from e
    except importers.ImporterError as e:
        # the choices could not be read to check the parameters against
        raise ApiError(409, str(e)) from e
    return flask.make_response(flask.jsonify(importers.run_json(record)), 202)


@bp.route("/api/import-runs/clear", methods=["POST"])
@auth.login_required
def api_runs_clear() -> flask.Response:
    """
    Delete the runs that ended, records and logs: the signed-in user's, or
    everyone's for an admin (whose list is everyone's). A run going is left
    alone, and so is everything the runs imported: only the runs go. They
    still count against the month's runs (models.ImportUsage). {"cleared": n}.
    """
    importers.settle(flask.g.db)
    query = delete(ImportRun).where(ImportRun.status.in_(IMPORT_ENDED))
    if flask.g.user.role != ROLE_ADMIN:
        query = query.where(ImportRun.owner_id == flask.g.user.id)
    cleared = flask.g.db.execute(query).rowcount
    flask.g.db.commit()
    return flask.jsonify({"cleared": cleared})


@bp.route("/api/import-runs/<int:run_id>", methods=["GET"])
@auth.login_required
def api_run_one(run_id: int) -> flask.Response:
    """
    One run, with its whole log: what its Log on the Imports page shows,
    and looks at again while it goes. The signed-in user's own, or anyone's
    for an admin (with whose it is); 404 for anyone else.
    """
    importers.settle(flask.g.db)
    admin = flask.g.user.role == ROLE_ADMIN
    record = flask.g.db.get(ImportRun, run_id)
    if record is None or (record.owner_id != flask.g.user.id and not admin):
        raise ApiError(404, "no such import run")
    return flask.jsonify(importers.run_json(record, flask.g.db.get(User, record.owner_id) if admin else None))


@bp.route("/api/import-runs/<int:run_id>", methods=["DELETE"])
@auth.login_required
def api_run_delete(run_id: int) -> flask.Response:
    """
    Delete one run that ended, its record and log: the signed-in user's
    own, or anyone's for an admin (404 for anyone else); 409 for one still
    going. What it imported stays, and it still counts against the month's
    runs (models.ImportUsage).
    """
    importers.settle(flask.g.db)
    record = flask.g.db.get(ImportRun, run_id)
    if record is None or (record.owner_id != flask.g.user.id and flask.g.user.role != ROLE_ADMIN):
        raise ApiError(404, "no such import run")
    if not importers.ended(record):
        raise ApiError(409, "this run is still going: it can be cleared once it ended")
    flask.g.db.delete(record)
    flask.g.db.commit()
    return flask.Response(status=204)


@bp.route("/api/import-runs", methods=["GET"])
@auth.login_required
def api_runs() -> flask.Response:
    """
    The runs going (queued or running) and the last RUNS_SHOWN that ended,
    each newest first: the signed-in user's, or everyone's for an admin,
    with whose each is. Runs whose jobs stopped are failed first.
    """
    importers.settle(flask.g.db)
    admin = flask.g.user.role == ROLE_ADMIN
    query = select(ImportRun, User).join(User, User.id == ImportRun.owner_id).order_by(ImportRun.id.desc())
    if not admin:
        query = query.where(ImportRun.owner_id == flask.g.user.id)
    going = flask.g.db.execute(query.where(ImportRun.status.not_in(IMPORT_ENDED))).all()
    ended = flask.g.db.execute(query.where(ImportRun.status.in_(IMPORT_ENDED)).limit(RUNS_SHOWN)).all()
    def shown(record, owner):
        return importers.run_json(record, owner if admin else None)
    return flask.jsonify({
        "running": [shown(record, owner) for record, owner in going],
        "ended": [shown(record, owner) for record, owner in ended],
        "everyone": admin,
        "limit": _limit_json(),
    })
