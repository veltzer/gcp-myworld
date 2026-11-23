"""
Views (doc/views.md): a user's named selections of their own data sets,
opened by anyone at /view/<username>/<name>, read only.
"""

import webtest

from tests.conftest import sign_in

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 32


def owner(app: webtest.TestApp) -> None:
    """ veltzer, with a concert, a person with a photo, and a book. """
    sign_in(app)
    app.put_json("/api/account/username", {"username": "veltzer"})
    app.post_json("/api/concert-visits", {"name": "Jarrett", "date": "2003-07-14"}, status=201)
    image = app.post("/api/images", upload_files=[("file", "dana.jpg", JPEG)]).json["id"]
    app.post_json("/api/people", {"first_name": "Dana", "photos": [{"image_id": image}]}, status=201)
    app.post_json("/api/library-entries", {"kind": "book", "title": "Dune", "creator": "Frank Herbert", "year": 1965})


def test_the_owner_makes_changes_and_deletes_views(app: webtest.TestApp) -> None:
    owner(app)
    listed = app.get("/api/shared-views").json
    assert listed["views"] == []
    assert listed["username"] == "veltzer"
    assert {"book", "concerts", "people"} <= set(listed["datasets"])
    made = app.post_json("/api/shared-views", {"name": "Music", "title": "My concerts", "datasets": ["people", "concerts"]}, status=201).json
    # the name is taken lowercase; the data sets in the page's order
    assert (made["name"], made["title"], made["datasets"], made["url"], made["access"]) == ("music", "My concerts", ["concerts", "people"], "/view/veltzer/music", "public")
    changed = app.put_json(f"/api/shared-views/{made['id']}", {"name": "music", "title": "", "datasets": ["book"]}).json
    assert (changed["title"], changed["datasets"]) == ("", ["book"])
    assert [v["name"] for v in app.get("/api/shared-views").json["views"]] == ["music"]
    app.delete(f"/api/shared-views/{made['id']}", status=204)
    assert app.get("/api/shared-views").json["views"] == []
    app.get("/view/veltzer/music", status=404)


def test_what_a_view_may_be(app: webtest.TestApp) -> None:
    owner(app)
    app.post_json("/api/shared-views", {"name": "music", "datasets": []}, status=201)
    assert app.post_json("/api/shared-views", {"name": "MUSIC", "datasets": []}, status=409).json == {"error": "name: you have a view called music already"}
    for name in ("", "-x", "has space", "a" * 61, "a/b"):
        app.post_json("/api/shared-views", {"name": name, "datasets": []}, status=400)
    assert app.post_json("/api/shared-views", {"name": "x", "datasets": ["users"]}, status=400).json == {"error": "datasets: no such data set: users"}


def test_a_view_needs_a_username(app: webtest.TestApp) -> None:
    sign_in(app)
    assert app.post_json("/api/shared-views", {"name": "music"}, status=400).json["error"].startswith("choose a username first")


def test_views_are_their_owners_alone(app: webtest.TestApp) -> None:
    owner(app)
    made = app.post_json("/api/shared-views", {"name": "music", "datasets": ["concerts"]}, status=201).json
    sign_in(app, "someone-else")
    app.put_json("/api/account/username", {"username": "dana"})
    assert app.get("/api/shared-views").json["views"] == []
    app.put_json(f"/api/shared-views/{made['id']}", {"name": "mine", "datasets": []}, status=404)
    app.delete(f"/api/shared-views/{made['id']}", status=404)
    # another user may use the same name
    app.post_json("/api/shared-views", {"name": "music", "datasets": []}, status=201)


def test_anyone_opens_a_view_and_reads_what_it_enables_only(app: webtest.TestApp) -> None:
    owner(app)
    app.post_json("/api/shared-views", {"name": "music", "title": "My concerts", "datasets": ["concerts", "people"]}, status=201)
    app.post("/auth/logout")
    # no one signed in
    assert app.get("/api/concert-visits", status=401)
    page = app.get("/view/veltzer/music")
    assert 'data-page="library"' in page.text
    config = app.get("/api/views/veltzer/music").json
    assert config["user"] is None
    assert config["visit"] == {"username": "veltzer", "name": "music", "title": "My concerts", "description": "", "datasets": ["concerts", "people"]}
    assert "book" in config["kinds"]
    base = "/api/views/veltzer/music/data"
    assert [c["name"] for c in app.get(f"{base}/concert-visits").json] == ["Jarrett"]
    people = app.get(f"{base}/people").json
    assert [p["first_name"] for p in people] == ["Dana"]
    # the person's photo, through the view
    assert people[0]["image"].startswith(f"{base}/images/")
    assert app.get(people[0]["image"]).body == JPEG
    # their types, for the type filter
    app.get(f"{base}/person-types")
    # not enabled, not an endpoint a view reads, or nothing to change
    for path in ("library-entries?kind=book", "library-entries", "groups", "organization-types", "stats", "config", "shared-views", "import-runs", "users", "nothing"):
        assert app.get(f"{base}/{path}", status=404).json == {"error": "not part of this view"}, path
    app.post_json(f"{base}/concert-visits", {"name": "Evil"}, status=405)


def test_a_library_kind_in_a_view(app: webtest.TestApp) -> None:
    owner(app)
    app.post_json("/api/shared-views", {"name": "reading", "datasets": ["book"]}, status=201)
    app.post("/auth/logout")
    assert [b["title"] for b in app.get("/api/views/veltzer/reading/data/library-entries?kind=book").json] == ["Dune"]
    app.get("/api/views/veltzer/reading/data/library-entries?kind=film", status=404)
    app.get("/api/views/veltzer/reading/data/concert-visits", status=404)


def test_a_view_that_is_not_there(app: webtest.TestApp) -> None:
    owner(app)
    app.post_json("/api/shared-views", {"name": "music", "datasets": ["concerts"]}, status=201)
    for path in ("/view/veltzer/nothing", "/view/nobody/music"):
        app.get(path, status=404)
    app.get("/api/views/nobody/music", status=404)
    app.get("/api/views/veltzer/nothing/data/concert-visits", status=404)
    # the address is not case sensitive
    app.get("/view/Veltzer/MUSIC")


def test_an_image_comes_through_a_view_only_by_the_address_it_gave(app: webtest.TestApp) -> None:
    owner(app)
    # a photo of the owner's that no row of the view shows
    hidden = app.post("/api/images", upload_files=[("file", "private.jpg", JPEG + b"private")]).json["id"]
    made = app.post_json("/api/shared-views", {"name": "music", "datasets": ["concerts", "people"]}, status=201).json
    app.post("/auth/logout")
    base = "/api/views/veltzer/music/data"
    address = app.get(f"{base}/people").json[0]["image"]
    path, sig = address.split("?sig=")
    assert app.get(address).body == JPEG
    # without the signature, with a wrong one, or another image's id under this one's
    for tried in (path, f"{path}?sig=", f"{path}?sig={'0' * 32}", f"{base}/images/{hidden}", f"{base}/images/{hidden}?sig={sig}"):
        assert app.get(tried, status=404).json == {"error": "not part of this view"}, tried
    # people taken out of the view: the address it gave stops working
    sign_in(app)
    app.put_json(f"/api/shared-views/{made['id']}", {"name": "music", "datasets": ["concerts"]})
    app.post("/auth/logout")
    app.get(address, status=404)
    # and back in, it works again; deleted, it never does
    sign_in(app)
    app.put_json(f"/api/shared-views/{made['id']}", {"name": "music", "datasets": ["concerts", "people"]})
    app.post("/auth/logout")
    assert app.get(address).body == JPEG
    sign_in(app)
    app.delete(f"/api/shared-views/{made['id']}", status=204)
    app.post("/auth/logout")
    app.get(address, status=404)
