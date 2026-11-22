"""
The pictures of everything: serving and uploading the images, the one
picture of a row (image_id) with the credit its license asks for, the
photos of a row that has several, and dropping the images nothing shows.
"""

import hashlib
from typing import Any

import flask
import werkzeug
from sqlalchemy import select

from myworld import auth
from myworld.api import ApiError, opt_int, text
from myworld.models import (
    AudioBook,
    AudioCourse,
    City,
    CityPhoto,
    Concert,
    Country,
    Cover,
    Device,
    Group,
    Image,
    Organization,
    PersonPhoto,
    PersonType,
    Place,
    Podcast,
    UserWork,
)

bp = flask.Blueprint("pictures", __name__)

# the rows with one picture and its credit
type Pictured = City | Country | Group | Device | PersonType | Place | Concert

# images never change once imported (a new photo is a new row), so browsers may keep them
IMAGE_MAX_AGE = 7 * 24 * 3600
# uploads: what a browser can show, recognised by its first bytes, not by what the client claims
IMAGE_MAX_BYTES = 8 * 1024 * 1024
IMAGE_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/gif": (b"GIF87a", b"GIF89a"),
}
IMAGE_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}


def image_url(image_id: int | None) -> str | None:
    if image_id is None:
        return None
    # read through a view (sharing.py): its visitor fetches the image through the view, by a signed address
    address = flask.g.get("image_address")
    if address is not None:
        return address(image_id)
    return flask.url_for("pictures.api_image", image_id=image_id)


def picture_json(row: Pictured) -> dict[str, Any]:
    return {"image": image_url(row.image_id), "image_source": row.image_source, "image_license": row.image_license, "image_author": row.image_author}


def _shared_images() -> Any:
    """ The images shared rows show (a place's photo, a podcast's or audio book's cover, a city's, a country's flag): everyone sees them, whoever uploaded them. """
    return select(Place.image_id).where(Place.image_id.is_not(None)).union(
        select(Podcast.image_id).where(Podcast.image_id.is_not(None)),
        select(AudioBook.image_id).where(AudioBook.image_id.is_not(None)),
        select(City.image_id).where(City.image_id.is_not(None)),
        select(CityPhoto.image_id),
        select(Country.image_id).where(Country.image_id.is_not(None)),
    )


def _may_see(image: Image | None) -> bool:
    """ The user's own image, or one a shared row shows. """
    if image is None:
        return False
    return image.owner_id == flask.g.user.id or image.id in set(flask.g.db.scalars(_shared_images()))


@bp.route("/api/images/<int:image_id>", methods=["GET"])
@auth.login_required
def api_image(image_id: int) -> werkzeug.Response:
    image = flask.g.db.get(Image, image_id)
    if not _may_see(image):
        return flask.Response(status=404)
    assert image is not None
    response = flask.Response(image.data, mimetype=image.content_type)
    response.headers["Cache-Control"] = f"private, max-age={IMAGE_MAX_AGE}"
    # the imported logos are SVG: opened on their own they must not run scripts on this origin
    response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.set_etag(image.sha256)
    return response.make_conditional(flask.request)


def _sniff(data: bytes) -> str | None:
    for content_type, signatures in IMAGE_SIGNATURES.items():
        if data.startswith(signatures):
            return content_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def owned_image(body: dict[str, Any]) -> int | None:
    image_id = opt_int(body, "image_id", 1, 2**31 - 1)
    if image_id is None:
        return None
    # the user's own, or one a shared row shows already (sent back as it was, by an admin changing that row)
    if not _may_see(flask.g.db.get(Image, image_id)):
        raise ApiError(400, "image_id: unknown image")
    return image_id


def owned_images(key: str, values: list[Any]) -> list[int]:
    """ Ids of the user's own images, as sent in a list (key names it in the error), each once and in the order sent. """
    ids = [value for value in values if isinstance(value, int) and not isinstance(value, bool)]
    if len(ids) != len(values) or len(set(ids)) != len(ids):
        raise ApiError(400, f"{key}: expected a list of image ids, each once")
    found = set(flask.g.db.scalars(select(Image.id).where(Image.owner_id == flask.g.user.id, Image.id.in_(ids)))) if ids else set()
    found |= set(ids) & set(flask.g.db.scalars(_shared_images()))
    if len(found) != len(ids):
        raise ApiError(400, f"{key}: unknown image")
    return ids


def apply_image(row: Any, body: dict[str, Any]) -> None:
    """
    The one picture of a row: a new upload (image_id) replaces it, and
    image_remove takes it away; sent neither, it stays as it is (a picture
    is never blanked by omission).
    """
    image_id = owned_image(body)
    if image_id is not None:
        row.image_id = image_id
    elif body.get("image_remove") is True:
        row.image_id = None


def apply_picture(row: Pictured, body: dict[str, Any]) -> None:
    apply_image(row, body)
    row.image_source, row.image_license, row.image_author = _credit(body)


def _credit(item: dict[str, Any]) -> tuple[str, str, str]:
    """ The credit a license asks for, as sent: where the picture is from, its license and who made it. """
    return text(item, "image_source"), text(item, "image_license"), text(item, "image_author")


def photo_json(photo: Pictured | CityPhoto | PersonPhoto) -> dict[str, Any]:
    """ One of the photos of a row that has several: its image and its credit. """
    return {"id": photo.image_id, "image": image_url(photo.image_id), "image_source": photo.image_source, "image_license": photo.image_license, "image_author": photo.image_author}


def sent_photos(value: Any) -> list[tuple[int, tuple[str, str, str]]]:
    """
    The photos of a row as sent, [{image_id, image_source, image_license,
    image_author}, ...]: each an image of the user's own, once, with its
    credit, in the order sent (the first is the one a card shows).
    """
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ApiError(400, "photos: expected a list of {image_id, image_source, image_license, image_author}")
    ids = owned_images("photos", [item.get("image_id") for item in value])
    return list(zip(ids, (_credit(item) for item in value), strict=True))


def photo_rows[T: (CityPhoto, PersonPhoto)](had: list[T], model: type[T], photos: list[tuple[int, tuple[str, str, str]]]) -> list[T]:
    """ The rows of photos: the row a photo already had is kept (with the credit now sent), a new photo gets a new one, and the rows not named are gone. """
    kept = {photo.image_id: photo for photo in had}
    rows = []
    for image_id, credit in photos:
        row = kept.get(image_id) or model(image_id=image_id)
        row.image_source, row.image_license, row.image_author = credit
        rows.append(row)
    return rows


def drop_unused_images() -> None:
    """ Photos and logos nothing shows any more (replaced or deleted) go too. """
    db = flask.g.db
    used = select(Concert.image_id).where(Concert.image_id.is_not(None)).union(
        select(Organization.image_id).where(Organization.image_id.is_not(None)),
        select(AudioCourse.image_id).where(AudioCourse.image_id.is_not(None)),
        select(AudioBook.image_id).where(AudioBook.image_id.is_not(None)),
        select(Podcast.image_id).where(Podcast.image_id.is_not(None)),
        select(UserWork.image_id).where(UserWork.image_id.is_not(None)),
        select(Cover.image_id),
        select(City.image_id).where(City.image_id.is_not(None)),
        select(CityPhoto.image_id),
        select(Country.image_id).where(Country.image_id.is_not(None)),
        select(Group.image_id).where(Group.image_id.is_not(None)),
        select(Place.image_id).where(Place.image_id.is_not(None)),
        select(Device.image_id).where(Device.image_id.is_not(None)),
        select(PersonType.image_id).where(PersonType.image_id.is_not(None)),
        select(PersonPhoto.image_id),
    )
    for image in db.execute(select(Image).where(Image.owner_id == flask.g.user.id, Image.id.not_in(used))).scalars():
        db.delete(image)


@bp.route("/api/images", methods=["POST"])
@auth.login_required
def api_images_add() -> tuple[flask.Response, int]:
    """ Upload a photo (multipart, field "file"); the answer's id goes into image_id. """
    upload = flask.request.files.get("file")
    if upload is None:
        raise ApiError(400, "file: required")
    data = upload.read(IMAGE_MAX_BYTES + 1)
    if len(data) > IMAGE_MAX_BYTES:
        raise ApiError(413, f"file: larger than {IMAGE_MAX_BYTES // (1024 * 1024)} MB")
    content_type = _sniff(data)
    if content_type is None:
        raise ApiError(400, "file: not a JPEG, PNG, GIF or WebP image")
    sha256 = hashlib.sha256(data).hexdigest()
    filename = f"upload-{sha256[:16]}{IMAGE_EXTENSIONS[content_type]}"
    db = flask.g.db
    image = db.execute(select(Image).where(Image.owner_id == flask.g.user.id, Image.filename == filename)).scalar_one_or_none()
    created = image is None
    if image is None:
        image = Image(owner_id=flask.g.user.id, filename=filename, content_type=content_type, sha256=sha256, data=data)
        db.add(image)
        db.commit()
    return flask.jsonify({"id": image.id, "url": image_url(image.id)}), 201 if created else 200
