"""
The podcast feeds importer (myworld.podcasts, myworld.importers.podcast_feeds),
against feeds that are faked: what a feed says, filling the episodes the
user has, the cover, adding the next episodes after the last one heard, and
that a run again adds nothing.
"""

import datetime
from typing import Any

import pytest
import webtest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from myworld import podcasts
from myworld.importers import core, jobs
from myworld.models import Device, Image, Podcast, PodcastEpisode, User
from tests.conftest import sign_in

FEED_URL = "https://feeds.example.com/history"
COVER_URL = "https://img.example.com/cover.jpg"
COVER = b"\xff\xd8\xffcover"


def item(n: int, **more: str) -> str:
    """ An episode of the feed: n-th, published on the n-th of March 2020. """
    fields = {
        "title": f"{n}. Episode {n}", "description": f"About {n}", "pubDate": f"Sun, {n:02d} Mar 2020 10:00:00 +0200", "guid": f"g{n}", "itunes:episode": str(n), "itunes:duration": "1:02:03",
        "itunes:episodeType": "full", "itunes:explicit": "no", "itunes:author": "Goalhanger", **more,
    }
    inner = "".join(f"<{tag}>{value}</{tag}>" for tag, value in fields.items() if value)
    return f'<item>{inner}<enclosure url="https://audio.example.com/{n}.mp3" type="audio/mpeg"/><itunes:image href="https://img.example.com/{n}.jpg"/></item>'


def feed(*numbers: int) -> bytes:
    """ A feed of the episodes numbered, newest first as feeds list them. """
    items = "".join(item(n) for n in sorted(numbers, reverse=True))
    return (
        '<?xml version="1.0"?><rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel>'
        f'<title>History</title><link>https://history.example.com</link><itunes:image href="{COVER_URL}"/>{items}</channel></rss>'
    ).encode()


class FakeWeb:
    def __init__(self) -> None:
        self.feeds = {FEED_URL: feed(1, 2, 3, 4, 5)}

    def fetch_feed(self, url: str) -> bytes:
        if url not in self.feeds:
            raise podcasts.FeedError(f"{url} answered 404: Not Found")
        return self.feeds[url]

    @staticmethod
    def fetch_cover(url: str) -> tuple[bytes, str] | None:
        return (COVER, "image/jpeg") if url == COVER_URL else None


@pytest.fixture(autouse=True)
def fixture_inline_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """ A run's job is done right away, inside the request that starts it. """
    def dispatcher(engine: Engine) -> Any:
        def dispatch(run_id: int) -> str:
            core.execute(engine, run_id)
            return f"projects/p/locations/r/jobs/myworld-import/executions/run-{run_id}"
        return dispatch
    monkeypatch.setattr(jobs, "dispatcher", dispatcher)


@pytest.fixture(name="web")
def fixture_web(monkeypatch: pytest.MonkeyPatch) -> FakeWeb:
    web = FakeWeb()
    monkeypatch.setattr(podcasts, "fetch_feed", web.fetch_feed)
    monkeypatch.setattr(podcasts, "fetch_cover", web.fetch_cover)
    return web


def run(app: webtest.TestApp, chosen: list[str] | None = None, next_: str | None = None, dry_run: bool = False) -> Any:
    params = {"podcasts": chosen or [], "next": [next_] if next_ else []}
    record = app.post_json("/api/importers/podcast-feeds/runs", {"params": params, "dry_run": dry_run}, status=202).json
    assert record["status"] == "done", record["log"]
    return record


def episodes(engine: Engine) -> list[PodcastEpisode]:
    with Session(engine) as session:
        return list(session.scalars(select(PodcastEpisode).order_by(PodcastEpisode.published_utcz)))


def heard_two(app: webtest.TestApp, engine: Engine) -> int:
    """ A podcast with its feed and its first two episodes heard, the second on a device, the first typed in with a name only. """
    sign_in(app)
    podcast = app.post_json("/api/podcasts", {"name": "History", "rss_feed": FEED_URL}, status=201).json
    with Session(engine) as session:
        owner = session.scalars(select(User)).one()
        device = Device(owner_id=owner.id, name="Samsung S25")
        session.add(device)
        session.add_all([
            PodcastEpisode(owner_id=owner.id, podcast_id=podcast["id"], name="My own name", guid="g1", date_ymd=datetime.date(2026, 3, 1)),
            PodcastEpisode(owner_id=owner.id, podcast_id=podcast["id"], name="2. Episode 2", guid="g2", description="Mine", device=device,
                           listened_at="Night Walks", date_utcz=datetime.datetime(2026, 3, 2, 20), date_timezone="Asia/Jerusalem"),
        ])
        session.commit()
    return int(podcast["id"])


def test_what_a_feed_says() -> None:
    said = podcasts.parse_feed(feed(2, 1))
    assert (said.link, said.image_url) == ("https://history.example.com", COVER_URL)
    first = said.episodes[0]
    assert [e.guid for e in said.episodes] == ["g1", "g2"]
    assert first == podcasts.Episode(
        name="1. Episode 1", description="About 1", published_utcz=datetime.datetime(2020, 3, 1, 8), number=1, duration=3723,
        episode_type="full", explicit="no", enclosure_url="https://audio.example.com/1.mp3", image_url="https://img.example.com/1.jpg",
        author="Goalhanger", guid="g1",
    )
    for wrong in (b"not xml", b"<feed/>"):
        with pytest.raises(podcasts.FeedError):
            podcasts.parse_feed(wrong)
    assert [podcasts.duration_seconds(v) for v in ("286", "32:55", "1:02:03.5", "", "x", "1:2:3:4")] == [286, 1975, 3723, None, None, None]


def test_only_http_is_read() -> None:
    for url in ("file:///etc/passwd", "ftp://example.com/feed", "feed"):
        with pytest.raises(podcasts.FeedError, match="not an http or https address"):
            podcasts.fetch_feed(url)


def test_it_needs_a_podcast_with_a_feed(app: webtest.TestApp) -> None:
    sign_in(app)
    importer = next(i for i in app.get("/api/importers").json["importers"] if i["name"] == "podcast-feeds")
    assert (importer["dataset"], importer["unavailable"]) == ("podcast-episodes", "Give a podcast its RSS feed first (Podcasts, Edit)")
    app.post_json("/api/podcasts", {"name": "History", "rss_feed": FEED_URL}, status=201)
    app.post_json("/api/podcasts", {"name": "No feed"}, status=201)
    importer = next(i for i in app.get("/api/importers").json["importers"] if i["name"] == "podcast-feeds")
    assert importer["unavailable"] == ""
    assert [c["label"] for c in importer["params"][0]["choices"]] == ["History"]
    assert importer["params"][1]["single"] is True


def test_the_feed_fills_what_is_empty_and_keeps_the_rest(app: webtest.TestApp, engine: Engine, web: FakeWeb) -> None:
    heard_two(app, engine)
    record = run(app)
    assert record["counts"] == {"episodes given the feed's details": 2, "covers added": 1, "podcasts given their page": 1}
    first, second = episodes(engine)
    # what the user typed is kept; what was empty is the feed's
    assert (first.name, first.description, first.duration, first.published_utcz) == ("My own name", "About 1", 3723, datetime.datetime(2020, 3, 1, 8))
    assert (second.description, second.enclosure_url) == ("Mine", "https://audio.example.com/2.mp3")
    with Session(engine) as session:
        podcast = session.scalars(select(Podcast)).one()
        assert podcast.url == "https://history.example.com"
        assert podcast.image is not None and (podcast.image.data, podcast.image.filename) == (COVER, f"podcast-feed-{podcast.id}.jpg")
    # again: nothing left to do
    assert run(app)["counts"] == {}


def test_the_next_episodes_are_added_as_heard_now(app: webtest.TestApp, engine: Engine, web: FakeWeb) -> None:
    heard_two(app, engine)
    before = datetime.datetime.now(datetime.UTC).replace(tzinfo=None, microsecond=0)
    assert run(app, next_="2")["counts"]["podcast episodes added"] == 2
    added = episodes(engine)[2:]
    assert [(e.guid, e.name, e.number, e.listened_at, e.date_timezone) for e in added] == [
        ("g3", "3. Episode 3", 3, "Night Walks", "Asia/Jerusalem"), ("g4", "4. Episode 4", 4, "Night Walks", "Asia/Jerusalem"),
    ]
    assert all(e.device_id is not None and e.date_utcz is not None and e.date_utcz >= before for e in added)
    # the next after those, as many as there are
    assert run(app, next_="10")["counts"]["podcast episodes added"] == 1
    assert run(app, next_="10")["counts"] == {}
    assert [e.guid for e in episodes(engine)] == ["g1", "g2", "g3", "g4", "g5"]


def test_after_the_last_heard_and_from_the_first_when_none_was(app: webtest.TestApp, engine: Engine, web: FakeWeb) -> None:
    sign_in(app)
    podcast = app.post_json("/api/podcasts", {"name": "History", "rss_feed": FEED_URL}, status=201).json
    run(app, next_="1")
    assert [e.guid for e in episodes(engine)] == ["g1"]
    # one heard further on: the ones skipped before it are not added
    app.post_json("/api/podcast-episodes", {"name": "4", "podcast_id": podcast["id"], "guid": "g4"}, status=201)
    run(app, next_="5")
    assert [e.guid for e in episodes(engine)] == ["g1", "g4", "g5"]


def test_a_dry_run_keeps_nothing(app: webtest.TestApp, engine: Engine, web: FakeWeb) -> None:
    heard_two(app, engine)
    record = run(app, next_="3", dry_run=True)
    assert record["counts"]["podcast episodes added"] == 3
    assert len(episodes(engine)) == 2
    with Session(engine) as session:
        assert session.scalars(select(Image)).first() is None


def test_a_feed_that_cannot_be_read_is_skipped(app: webtest.TestApp, engine: Engine, web: FakeWeb) -> None:
    sign_in(app)
    gone = app.post_json("/api/podcasts", {"name": "Gone", "rss_feed": "https://feeds.example.com/gone"}, status=201).json
    history = app.post_json("/api/podcasts", {"name": "History", "rss_feed": FEED_URL}, status=201).json
    record = run(app, next_="1")
    assert record["counts"] == {"feeds that could not be read": 1, "covers added": 1, "podcasts given their page": 1, "podcast episodes added": 1}
    assert "Gone: https://feeds.example.com/gone answered 404" in record["log"]
    # only the podcasts chosen
    assert run(app, chosen=[str(gone["id"])], next_="1")["counts"] == {"feeds that could not be read": 1}
    assert run(app, chosen=[str(history["id"])], next_="1")["counts"] == {"podcast episodes added": 1}
