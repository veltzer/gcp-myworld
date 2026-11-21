"""
The podcasts' RSS feeds, into the shared data (an admin's importer): each
podcast chosen (or every one with a feed) has its feed read, and

- an episode the feed has that the podcast does not yet (by its guid) is
  added, every field as the feed says it;
- an episode it has is given what the feed says of it where it says
  nothing yet, and its whole description where it has only the start of
  it: what an admin wrote or edited is kept;
- a podcast with no cover, or no page, is given the feed's.

It only ever adds and fills, and keeps ids (an episode someone heard points
at it): a run again adds only what the feed added since, and an episode the
feed no longer has stays. A feed that cannot be read is said in the log and
skipped. Marking episodes heard is each user's own importer
(podcast_next).
"""

import dataclasses
import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from myworld import podcasts
from myworld.importers.core import Importer, Param, Report, register
from myworld.models import Image, Podcast, PodcastEpisode, User
from myworld.pictures import IMAGE_EXTENSIONS

# the feed's fields of an episode, filled where the episode has nothing yet
FEED_FIELDS = tuple(field.name for field in dataclasses.fields(podcasts.Episode) if field.name not in ("name", "guid"))
# what the columns take (models.PodcastEpisode); a feed may say more
LIMITS = {"name": 500, "episode_type": 20, "explicit": 10, "enclosure_url": 2000, "image_url": 2000, "author": 300, "guid": 500}


def fitted(episode: podcasts.Episode) -> dict[str, Any]:
    """ The columns of episode, each cut to what its column takes. """
    values = dataclasses.asdict(episode)
    for field, limit in LIMITS.items():
        value = values[field]
        if isinstance(value, str):
            values[field] = value[:limit]
    return values


def _with_feeds(session: Session) -> list[Podcast]:
    return list(session.scalars(select(Podcast).where(Podcast.rss_feed != "").order_by(Podcast.name)))


def podcast_choices(session: Session, _owner: User) -> list[tuple[str, str]]:
    return [(str(podcast.id), podcast.name) for podcast in _with_feeds(session)]


def unavailable(session: Session, _owner: User) -> str:
    return "" if _with_feeds(session) else "Give a podcast its RSS feed first (Podcasts, Edit)"


def _cover(session: Session, owner: User, podcast: Podcast, url: str) -> bool:
    """ Give podcast the feed's cover when it has none; whether it was given. """
    if podcast.image_id is not None or not url:
        return False
    fetched = podcasts.fetch_cover(url)
    if fetched is None:
        return False
    data, content_type = fetched
    filename = f"podcast-feed-{podcast.id}{IMAGE_EXTENSIONS[content_type]}"
    image = session.scalars(select(Image).where(Image.owner_id == owner.id, Image.filename == filename)).first()
    if image is None:
        image = Image(owner_id=owner.id, filename=filename, content_type=content_type, sha256=hashlib.sha256(data).hexdigest(), data=data)
        session.add(image)
    podcast.image = image
    return True


def _fill(episode: PodcastEpisode, said: podcasts.Episode) -> bool:
    """ Give episode what the feed says where it has nothing yet; whether anything was given. """
    values = fitted(said)
    changed = False
    for field in FEED_FIELDS:
        if getattr(episode, field) in ("", None) and values[field] not in ("", None):
            setattr(episode, field, values[field])
            changed = True
    # a description cut short (veltzer.github.io kept 200 characters of each, some of it HTML) is the feed's whole one
    if episode.description and _cut_short(episode.description, said.description):
        episode.description = said.description
        changed = True
    return changed


def _cut_short(had: str, said: str) -> bool:
    """ Whether had is the start of said, as text: a description cut short, not one written in its place. """
    start = podcasts.plain(had).removesuffix("…").strip()
    return len(start) < len(said) and bool(start) and said.startswith(start)


def run(session: Session, owner: User, params: dict[str, Any], report: Report) -> None:
    chosen = set(params.get("podcasts") or [])
    query = select(Podcast).where(Podcast.rss_feed != "").options(selectinload(Podcast.episodes)).order_by(Podcast.name)
    for podcast in session.scalars(query):
        if chosen and str(podcast.id) not in chosen:
            continue
        try:
            feed = podcasts.parse_feed(podcasts.fetch_feed(podcast.rss_feed))
        except podcasts.FeedError as e:
            report.say(f"{podcast.name}: {e}")
            report.count("feeds that could not be read")
            continue
        report.say(f"{podcast.name}: the feed has {len(feed.episodes)} episodes")
        if not podcast.url and feed.link.startswith(("https://", "http://")):
            podcast.url = feed.link[:1000]
            report.count("podcasts given their page")
        if _cover(session, owner, podcast, feed.image_url):
            report.count("covers added")
        have = {episode.guid: episode for episode in podcast.episodes if episode.guid}
        for said in feed.episodes:
            values = fitted(said)
            guid = values["guid"]
            if not guid:
                # nothing to find it again by: it would be added on every run
                continue
            episode = have.get(guid)
            if episode is None:
                episode = PodcastEpisode(**values)
                podcast.episodes.append(episode)
                have[guid] = episode
                report.count("podcast episodes added")
            elif _fill(episode, said):
                report.count("episodes given the feed's details")
    session.flush()


IMPORTER = register(Importer(
    name="podcast-feeds",
    title="Podcast feeds",
    description=(
        "Reads the RSS feeds of the podcasts (the ones chosen, or every one with a feed) into the shared data: every "
        "episode a podcast does not have yet is added, the ones it has get what the feed says where they have nothing "
        "yet, and a podcast with no cover or page gets the feed's. Keeps edits and ids, adds an episode once: safe to run again."
    ),
    dataset="podcast-episodes",
    shared=True,
    params=(
        Param(name="podcasts", title="Podcasts", kind="choices", choices=podcast_choices,
              description="The podcasts whose feeds are read; none chosen reads every one with a feed."),
    ),
    run=run,
    unavailable=unavailable,
))
