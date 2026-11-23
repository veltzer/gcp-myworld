"""
Views (doc/views.md): a user's named selections of their own data sets,
which anyone may open, read only, at /view/<username>/<name>.

The owner makes, changes and deletes them through /api/shared-views. A
visitor's page is the library page in visitor mode: what it would ask the
library API (GET /api/<what>), it asks the view (GET
/api/views/<username>/<name>/data/<what>), which answers it as the library
endpoint would answer the owner, when the endpoint is one the view's data
sets may read (READS) and never otherwise.

An image comes through the view only by the address the view gave it in the
rows it sent: that address is signed (image_signature), so a visitor cannot
reach any other image of the owner's by trying ids, and taking a data set
out of the view (or deleting it) makes the old addresses stop working.
"""

import hashlib
import hmac
import re
from collections.abc import Callable, Mapping
from typing import Any

import flask
import werkzeug
from sqlalchemy import select
from werkzeug.exceptions import MethodNotAllowed, NotFound
from werkzeug.routing import RequestRedirect

from myworld import auth
from myworld.api import ApiError, json_body, text
from myworld.models import (
    KINDS,
    VIEW_ACCESS_PUBLIC,
    VIEW_NAME_MAX,
    VIEW_NAME_PATTERN,
    SharedView,
    User,
)
from myworld.views import HTML_DIR, vocabularies

bp = flask.Blueprint("sharing", __name__)

# the data sets a view can show: the library's kinds, then the views of the user's own rows (the page's names)
WORLD_DATASETS = ("concerts", "museums", "audio-courses", "audio-books-heard", "audio-book-listens", "podcasts-heard", "episodes-heard", "film-watches", "series-watches", "youtube", "chess", "certifications", "courses", "trips", "lectures", "rallies", "loans", "websites", "people", "groups", "organizations")
DATASETS = (*KINDS, *WORLD_DATASETS)

TITLE_MAX = 200

# library endpoint -> the data set whose view may read it (given the endpoint's arguments), or None
READS: dict[str, Callable[[Mapping[str, Any]], str | None]] = {
    "world.api_concerts": lambda _args: "concerts",
    "world.api_museums": lambda _args: "museums",
    "world.api_audio_courses": lambda _args: "audio-courses",
    "world.api_audio_books_heard": lambda _args: "audio-books-heard",
    "world.api_audio_book_listens": lambda _args: "audio-book-listens",
    "world.api_podcasts_heard": lambda _args: "podcasts-heard",
    "world.api_episodes_heard": lambda _args: "episodes-heard",
    "world.api_film_watches": lambda _args: "film-watches",
    "world.api_series_watches": lambda _args: "series-watches",
    "world.api_youtube": lambda _args: "youtube",
    "world.api_chess_games": lambda _args: "chess",
    "world.api_chess_game": lambda _args: "chess",
    "world.api_certifications": lambda _args: "certifications",
    "world.api_courses": lambda _args: "courses",
    "world.api_loans": lambda _args: "loans",
    "world.api_websites": lambda _args: "websites",
    "world.api_trips": lambda _args: "trips",
    "world.api_lectures": lambda _args: "lectures",
    "world.api_rallies": lambda _args: "rallies",
    "world.api_people": lambda _args: "people",
    "world.api_groups": lambda _args: "groups",
    "world.api_organizations": lambda _args: "organizations",
    # the types of people and organizations, for their type filter
    "enumerations.api_types": lambda args: {"person-types": "people", "organization-types": "organizations"}.get(args["what"]),
    # one kind of the library at a time
    "views.api_library_list": lambda _args: flask.request.args.get("kind"),
}

# an image the rows of a view show: any data set's, by the signed address the view gave it
IMAGE_ENDPOINT = "pictures.api_image"


def image_signature(view: SharedView, image_id: int) -> str:
    """
    What proves the view gave out the address of image_id: an HMAC, under the
    app's secret key, of the view, the data sets it shows now and the image.
    """
    message = f"{view.id}:{','.join(sorted(view.datasets))}:{image_id}".encode()
    key = str(flask.current_app.config["SECRET_KEY"]).encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()[:32]


def _image_address(view: SharedView) -> Callable[[int], str]:
    base = f"/api/views/{view.owner.username}/{view.name}/data/images"
    return lambda image_id: f"{base}/{image_id}?sig={image_signature(view, image_id)}"


def view_path(username: str, name: str) -> str:
    return f"/view/{username}/{name}"


def view_json(view: SharedView) -> dict[str, Any]:
    return {
        "id": view.id,
        "name": view.name,
        "title": view.title,
        "description": view.description,
        "datasets": [d for d in view.datasets if d in DATASETS],
        "access": view.access,
        "url": view_path(view.owner.username or "", view.name),
        "created_at": view.created_at.isoformat(timespec="seconds"),
        "updated_at": view.updated_at.isoformat(timespec="seconds"),
    }


# ─── the owner's ─────────────────────────────────────────────────────────────

def _own(view_id: int) -> SharedView:
    view = flask.g.db.get(SharedView, view_id)
    if view is None or view.owner_id != flask.g.user.id:
        raise ApiError(404, "no such view")
    return view


def _apply(view: SharedView, body: dict[str, Any]) -> None:
    name = text(body, "name", required=True).lower()
    if not re.fullmatch(VIEW_NAME_PATTERN, name):
        raise ApiError(400, f"name: 1 to {VIEW_NAME_MAX} lowercase letters, digits, dots, dashes or underscores, starting with a letter or digit (it is the end of the view's address)")
    taken = flask.g.db.scalars(select(SharedView.id).where(SharedView.owner_id == flask.g.user.id, SharedView.name == name, SharedView.id != view.id)).first()
    if taken is not None:
        raise ApiError(409, f"name: you have a view called {name} already")
    title = text(body, "title")
    if len(title) > TITLE_MAX:
        raise ApiError(400, f"title: at most {TITLE_MAX} characters")
    datasets = body.get("datasets", [])
    if not isinstance(datasets, list) or not all(isinstance(d, str) for d in datasets):
        raise ApiError(400, "datasets: expected a list of data sets")
    unknown = [d for d in datasets if d not in DATASETS]
    if unknown:
        raise ApiError(400, f"datasets: no such data set: {', '.join(unknown)}")
    view.name = name
    view.title = title
    view.description = text(body, "description")
    # in the order the page lists them
    view.datasets = [d for d in DATASETS if d in datasets]


@bp.route("/api/shared-views", methods=["GET"])
@auth.login_required
def api_views() -> flask.Response:
    """ The user's views, and the data sets a view can show. """
    views = flask.g.db.scalars(select(SharedView).where(SharedView.owner_id == flask.g.user.id).order_by(SharedView.name)).all()
    return flask.jsonify({"datasets": list(DATASETS), "username": flask.g.user.username, "views": [view_json(v) for v in views]})


@bp.route("/api/shared-views", methods=["POST"])
@auth.login_required
def api_view_add() -> tuple[flask.Response, int]:
    if not flask.g.user.username:
        raise ApiError(400, "choose a username first (Settings): a view's address has it")
    view = SharedView(owner_id=flask.g.user.id, owner=flask.g.user, access=VIEW_ACCESS_PUBLIC)
    _apply(view, json_body())
    flask.g.db.add(view)
    flask.g.db.commit()
    return flask.jsonify(view_json(view)), 201


@bp.route("/api/shared-views/<int:view_id>", methods=["PUT"])
@auth.login_required
def api_view_update(view_id: int) -> flask.Response:
    view = _own(view_id)
    _apply(view, json_body())
    flask.g.db.commit()
    return flask.jsonify(view_json(view))


@bp.route("/api/shared-views/<int:view_id>", methods=["DELETE"])
@auth.login_required
def api_view_delete(view_id: int) -> flask.Response:
    flask.g.db.delete(_own(view_id))
    flask.g.db.commit()
    return flask.Response(status=204)


# ─── the visitor's ───────────────────────────────────────────────────────────

def _visited(username: str, name: str) -> SharedView:
    """ The view an address names, if anyone may open it (404 otherwise, the same for one that does not exist). """
    owner = flask.g.db.scalars(select(User).where(User.username == username.lower())).first()
    view = None if owner is None else flask.g.db.scalars(select(SharedView).where(SharedView.owner_id == owner.id, SharedView.name == name.lower())).first()
    if view is None or view.access != VIEW_ACCESS_PUBLIC:
        raise ApiError(404, "no such view")
    return view


@bp.route("/view/<username>/<name>", methods=["GET"])
def view_page(username: str, name: str) -> werkzeug.Response:
    """ The library page, which sees by its address that it shows a view (visitor mode). """
    try:
        _visited(username, name)
    except ApiError:
        return flask.Response("There is no such view.\n", status=404, mimetype="text/plain")
    response = flask.send_from_directory(HTML_DIR, "library.html")
    # what a view shows is public, but it may change at any time
    response.headers["Cache-Control"] = "no-cache"
    return response


@bp.route("/api/views/<username>/<name>", methods=["GET"])
def api_visit_config(username: str, name: str) -> flask.Response:
    """ The view page's config: the vocabularies, no one signed in, and the view. """
    view = _visited(username, name)
    return flask.jsonify({
        **vocabularies(),
        "user": None,
        "visit": {"username": view.owner.username, "name": view.name, "title": view.title or view.name, "description": view.description, "datasets": view_json(view)["datasets"]},
    })


@bp.route("/api/views/<username>/<name>/data/<path:what>", methods=["GET"])
def api_visit_data(username: str, name: str, what: str) -> Any:
    """ GET /api/<what>, answered as the view's owner would get it, if the view's data sets may read it. """
    view = _visited(username, name)
    try:
        endpoint, args = flask.current_app.url_map.bind(flask.request.host).match(f"/api/{what}", method="GET")
    except (NotFound, MethodNotAllowed, RequestRedirect) as e:
        raise ApiError(404, "not part of this view") from e
    if endpoint == IMAGE_ENDPOINT:
        if not hmac.compare_digest(flask.request.args.get("sig", ""), image_signature(view, args["image_id"])):
            raise ApiError(404, "not part of this view")
    else:
        reads = READS.get(str(endpoint))
        dataset = None if reads is None else reads(args)
        if dataset is None or dataset not in view.datasets:
            raise ApiError(404, "not part of this view")
    function = flask.current_app.view_functions[str(endpoint)]
    # past login_required: the owner is who it is read as
    flask.g.user = view.owner
    flask.g.image_address = _image_address(view)
    return getattr(function, "__wrapped__", function)(**args)

