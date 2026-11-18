"""
The pictures (myworld/pictures.py): what may be uploaded, how an image is
served, and how the photos of a row that has several are kept.
"""

import pytest
import webtest

from myworld import pictures
from tests.conftest import sign_in

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
GIF = b"GIF89a" + b"0" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"0" * 24


@pytest.mark.parametrize(("data", "content_type"), [
    (JPEG, "image/jpeg"),
    (PNG, "image/png"),
    (GIF, "image/gif"),
    (b"GIF87a" + b"0" * 8, "image/gif"),
    (WEBP, "image/webp"),
    (b"", None),
    (b"not an image", None),
    # a sound in the same wrapper as WebP is not a picture
    (b"RIFF\x24\x00\x00\x00WAVEfmt ", None),
    (b"<svg xmlns='http://www.w3.org/2000/svg'/>", None),
    (b"%PDF-1.7", None),
])
def test_an_image_is_told_by_its_first_bytes(data: bytes, content_type: str | None) -> None:
    assert pictures._sniff(data) == content_type  # pylint: disable=protected-access


@pytest.mark.parametrize(("data", "extension", "content_type"), [(JPEG, ".jpg", "image/jpeg"), (PNG, ".png", "image/png"), (GIF, ".gif", "image/gif"), (WEBP, ".webp", "image/webp")])
def test_upload(app: webtest.TestApp, data: bytes, extension: str, content_type: str) -> None:
    sign_in(app)
    # the name and the type the browser claims count for nothing
    upload = app.post("/api/images", upload_files=[("file", "claims-to-be.txt", data)], status=201).json
    assert upload["url"] == f"/api/images/{upload['id']}"
    served = app.get(upload["url"])
    assert (served.body, served.content_type) == (data, content_type)
    assert served.headers["X-Content-Type-Options"] == "nosniff"
    assert "sandbox" in served.headers["Content-Security-Policy"]
    assert served.headers["Cache-Control"].startswith("private, max-age=")
    assert extension in pictures.IMAGE_EXTENSIONS.values()


def test_upload_refuses(app: webtest.TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in(app)
    assert app.post("/api/images", status=400).json == {"error": "file: required"}
    assert app.post("/api/images", upload_files=[("other", "x.jpg", JPEG)], status=400).json == {"error": "file: required"}
    for data in (b"", b"plain text", b"<svg/>"):
        assert app.post("/api/images", upload_files=[("file", "x.jpg", data)], status=400).json == {"error": "file: not a JPEG, PNG, GIF or WebP image"}
    monkeypatch.setattr(pictures, "IMAGE_MAX_BYTES", 2 * 1024 * 1024)
    big = JPEG + b"0" * (2 * 1024 * 1024)
    assert app.post("/api/images", upload_files=[("file", "big.jpg", big)], status=413).json == {"error": "file: larger than 2 MB"}


def test_the_same_picture_is_kept_once(app: webtest.TestApp) -> None:
    sign_in(app)
    first = app.post("/api/images", upload_files=[("file", "a.jpg", JPEG)], status=201).json
    again = app.post("/api/images", upload_files=[("file", "b.jpg", JPEG)], status=200).json
    assert again == first
    other = app.post("/api/images", upload_files=[("file", "c.jpg", JPEG + b"1")], status=201).json
    assert other["id"] != first["id"]
    # each account keeps its own copy
    sign_in(app, sub="someone-else")
    theirs = app.post("/api/images", upload_files=[("file", "a.jpg", JPEG)], status=201).json
    assert theirs["id"] not in (first["id"], other["id"])


def test_an_image_is_its_owners_and_is_not_sent_twice(app: webtest.TestApp) -> None:
    app.get("/api/images/1", status=401)
    sign_in(app)
    url = app.post("/api/images", upload_files=[("file", "a.jpg", JPEG)], status=201).json["url"]
    app.get("/api/images/999", status=404)
    served = app.get(url)
    # a browser that has it asks with its tag and is told it has not changed
    app.get(url, headers={"If-None-Match": served.headers["ETag"]}, status=304)
    app.get(url, headers={"If-None-Match": '"something-else"'}, status=200)
    sign_in(app, sub="someone-else")
    app.get(url, status=404)


def test_a_picture_is_the_users_own(app: webtest.TestApp) -> None:
    sign_in(app, sub="someone-else")
    theirs = app.post("/api/images", upload_files=[("file", "a.jpg", JPEG)], status=201).json["id"]
    sign_in(app)
    mine = app.post("/api/images", upload_files=[("file", "a.jpg", JPEG)], status=201).json["id"]
    assert app.post_json("/api/places", {"name": "Barby", "image_id": theirs}, status=400).json == {"error": "image_id: unknown image"}
    assert app.post_json("/api/places", {"name": "Barby", "image_id": "one"}, status=400).json == {"error": "image_id: expected a number"}
    for photos, error in (
        ("mine", "photos: expected a list of {image_id, image_source, image_license, image_author}"),
        ([mine], "photos: expected a list of {image_id, image_source, image_license, image_author}"),
        ([{"image_id": theirs}], "photos: unknown image"),
        ([{"image_id": mine}, {"image_id": mine}], "photos: expected a list of image ids, each once"),
        ([{"image_id": "one"}], "photos: expected a list of image ids, each once"),
        ([{}], "photos: expected a list of image ids, each once"),
        ([{"image_id": mine, "image_source": 3}], "image_source: expected a string"),
    ):
        assert app.post_json("/api/cities", {"name": "Haifa", "photos": photos}, status=400).json == {"error": error}, photos
        assert app.post_json("/api/people", {"first_name": "Dana", "photos": photos}, status=400).json == {"error": error}, photos


@pytest.mark.parametrize("path", ["cities", "people"])
def test_photos_keep_their_order_and_their_credit(app: webtest.TestApp, path: str) -> None:
    sign_in(app)
    one, two, three = (app.post("/api/images", upload_files=[("file", f"{n}.jpg", JPEG + bytes([n]))]).json["id"] for n in range(3))
    name = {"name": "Haifa"} if path == "cities" else {"first_name": "Dana"}

    def photo(image_id: int, author: str) -> dict[str, object]:
        return {"image_id": image_id, "image_source": f"https://example.com/{image_id}", "image_license": "CC0", "image_author": author}

    row = app.post_json(f"/api/{path}", {**name, "photos": [photo(one, "Ann"), photo(two, "Ben")]}, status=201).json
    assert [(p["id"], p["image_author"]) for p in row["photos"]] == [(one, "Ann"), (two, "Ben")]
    assert row["image"] == f"/api/images/{one}"
    # turned around, with a third and a credit put right: each photo keeps what is sent for it
    row = app.put_json(f"/api/{path}/{row['id']}", {**name, "photos": [photo(three, "Cy"), photo(two, "Benjamin"), photo(one, "Ann")]}).json
    assert [(p["id"], p["image_author"], p["image_source"]) for p in row["photos"]] == [
        (three, "Cy", f"https://example.com/{three}"), (two, "Benjamin", f"https://example.com/{two}"), (one, "Ann", f"https://example.com/{one}"),
    ]
    assert row["image"] == f"/api/images/{three}"
    # not sent, the photos stay; sent empty, they go, and their images with them
    assert len(app.put_json(f"/api/{path}/{row['id']}", name).json["photos"]) == 3
    row = app.put_json(f"/api/{path}/{row['id']}", {**name, "photos": []}).json
    assert (row["photos"], row["image"]) == ([], None)
    for image_id in (one, two, three):
        app.get(f"/api/images/{image_id}", status=404)


@pytest.mark.parametrize(("path", "body"), [
    ("places", {"name": "Barby"}), ("groups", {"name": "Trio"}), ("countries", {"name": "Israel"}), ("concert-visits", {"name": "Jarrett"}),
    ("museum-visits", {"name": "Prado"}), ("organizations", {"name": "ACME"}), ("audio-courses", {"name": "Logic"}),
])
def test_one_picture_replaced_or_taken_away(app: webtest.TestApp, path: str, body: dict[str, str]) -> None:
    sign_in(app)
    old = app.post("/api/images", upload_files=[("file", "old.jpg", JPEG)]).json["id"]
    row = app.post_json(f"/api/{path}", {**body, "image_id": old}, status=201).json
    assert row["image"] == f"/api/images/{old}"
    # left out, it stays
    assert app.put_json(f"/api/{path}/{row['id']}", body).json["image"] == f"/api/images/{old}"
    # replaced (an upload is for the save that follows it), the old image is nobody's and goes
    new = app.post("/api/images", upload_files=[("file", "new.jpg", JPEG + b"1")]).json["id"]
    assert app.put_json(f"/api/{path}/{row['id']}", {**body, "image_id": new}).json["image"] == f"/api/images/{new}"
    app.get(f"/api/images/{old}", status=404)
    # taken away
    assert app.put_json(f"/api/{path}/{row['id']}", {**body, "image_remove": True}).json["image"] is None
    app.get(f"/api/images/{new}", status=404)


def test_a_picture_two_rows_show_is_kept_while_one_does(app: webtest.TestApp) -> None:
    sign_in(app)
    image = app.post("/api/images", upload_files=[("file", "a.jpg", JPEG)]).json["id"]
    place = app.post_json("/api/places", {"name": "Barby", "image_id": image}, status=201).json
    group = app.post_json("/api/groups", {"name": "Trio", "image_id": image}, status=201).json
    app.delete(f"/api/places/{place['id']}", status=204)
    app.get(f"/api/images/{image}", status=200)
    app.delete(f"/api/groups/{group['id']}", status=204)
    app.get(f"/api/images/{image}", status=404)
