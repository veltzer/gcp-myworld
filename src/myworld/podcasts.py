"""
A podcast's RSS feed: reading it (fetch_feed) and what it says
(parse_feed): the podcast's page and cover, and each of its episodes with
everything the feed gives of it (title, description, when published, its
number, length, type, explicit, the audio's and the image's addresses,
author, guid), oldest first. A description is kept as text: a feed's is
often HTML, whose tags are dropped and entities read (plain). The importer of the episodes
(myworld.importers.podcast_feeds) is built on it.

A feed is anyone's address, read by the server: only http and https are
read, at most FEED_MAX_BYTES of it, and the XML parser resolves no external
entity (xml.etree never does; expat since 2.4.1 refuses entity expansion
attacks, the "billion laughs").
"""

import dataclasses
import datetime
import email.utils
import html.parser
import math
import xml.etree.ElementTree as ET

import requests

HTTP_TIMEOUT = 30
# a feed of a thousand episodes with long descriptions is a few MB
FEED_MAX_BYTES = 30 * 1024 * 1024
COVER_MAX_BYTES = 8 * 1024 * 1024
ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
# the image types a cover is kept as (pictures.IMAGE_SIGNATURES and WebP)
COVER_SIGNATURES = {b"\xff\xd8\xff": "image/jpeg", b"\x89PNG\r\n\x1a\n": "image/png", b"GIF87a": "image/gif", b"GIF89a": "image/gif"}


class FeedError(Exception):
    """ A feed that could not be read, or is not a feed. """


@dataclasses.dataclass
class Episode:
    """ An episode as its feed says it: the columns of models.PodcastEpisode it fills. """
    name: str
    description: str = ""
    published_utcz: datetime.datetime | None = None
    number: int | None = None
    duration: int | None = None
    episode_type: str = ""
    explicit: str = ""
    enclosure_url: str = ""
    image_url: str = ""
    author: str = ""
    guid: str | None = None


@dataclasses.dataclass
class Feed:
    """ What a feed says: the podcast's page and cover, and its episodes, oldest first. """
    link: str
    image_url: str
    episodes: list[Episode]


def _get(url: str, max_bytes: int) -> bytes:
    """ What is at url, at most max_bytes of it; FeedError when it cannot be read. """
    if not url.startswith(("https://", "http://")):
        raise FeedError(f"{url!r} is not an http or https address")
    try:
        with requests.get(url, timeout=HTTP_TIMEOUT, stream=True, headers={"User-Agent": "My World podcast feeds"}) as response:
            if not response.ok:
                raise FeedError(f"{url} answered {response.status_code}: {response.reason}")
            body = bytearray()
            for chunk in response.iter_content(64 * 1024):
                body += chunk
                if len(body) > max_bytes:
                    raise FeedError(f"{url} is larger than {max_bytes // (1024 * 1024)} MB")
    except requests.RequestException as e:
        raise FeedError(f"{url} could not be read: {e}") from e
    return bytes(body)


def fetch_feed(url: str) -> bytes:
    """ The feed at url, as it is. """
    return _get(url, FEED_MAX_BYTES)


def fetch_cover(url: str) -> tuple[bytes, str] | None:
    """ A cover image and its type, told by its first bytes; None when there is none to be had. """
    try:
        data = _get(url, COVER_MAX_BYTES)
    except FeedError:
        return None
    for signature, content_type in COVER_SIGNATURES.items():
        if data.startswith(signature):
            return data, content_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return data, "image/webp"
    return None


def duration_seconds(value: str) -> int | None:
    """ An iTunes duration (SS, MM:SS or HH:MM:SS, any part with a fraction) in seconds; None for anything else. """
    parts = value.strip().split(":")
    if not value.strip() or len(parts) > 3:
        return None
    total = 0.0
    try:
        for part in parts:
            total = total * 60 + float(part)
    except ValueError:
        return None
    return int(total) if math.isfinite(total) and total >= 0 else None


def published(value: str) -> datetime.datetime | None:
    """ A pubDate ("Wed, 28 Oct 2020 13:00:00 -0000") as the naive UTC the columns keep; None when it is not a date. """
    try:
        stamp = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        return stamp
    return stamp.astimezone(datetime.UTC).replace(tzinfo=None)


class _Text(html.parser.HTMLParser):
    """ The text of some HTML: what a reader sees, its tags gone and its entities read; a paragraph or a line break a space. """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in ("p", "br", "div", "li"):
            self.parts.append(" ")


def plain(text: str) -> str:
    """ A description as text: a feed's is often HTML ("<p>How did <b>certain</b> people..."), which a card shows as it reads. """
    if "<" not in text and "&" not in text:
        return " ".join(text.split())
    parser = _Text()
    parser.feed(text)
    parser.close()
    return " ".join("".join(parser.parts).split())


def _text(element: ET.Element, tag: str) -> str:
    found = element.find(tag)
    return found.text.strip() if found is not None and found.text else ""


def _attr(element: ET.Element, tag: str, name: str) -> str:
    found = element.find(tag)
    return (found.get(name) or "").strip() if found is not None else ""


def _episode(item: ET.Element) -> Episode:
    number = _text(item, f"{ITUNES}episode")
    return Episode(
        name=_text(item, "title") or _text(item, f"{ITUNES}title"),
        description=plain(_text(item, "description") or _text(item, f"{ITUNES}summary")),
        published_utcz=published(_text(item, "pubDate")),
        number=int(number) if number.isdigit() else None,
        duration=duration_seconds(_text(item, f"{ITUNES}duration")),
        episode_type=_text(item, f"{ITUNES}episodeType"),
        explicit=_text(item, f"{ITUNES}explicit"),
        enclosure_url=_attr(item, "enclosure", "url"),
        image_url=_attr(item, f"{ITUNES}image", "href"),
        author=_text(item, f"{ITUNES}author"),
        guid=_text(item, "guid") or None,
    )


def parse_feed(data: bytes) -> Feed:
    """ What an RSS feed says; its episodes oldest first (by when published, as the feed lists them where that is not said). """
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise FeedError(f"the feed is not XML: {e}") from e
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise FeedError("the feed is not an RSS feed")
    # feeds list the newest first
    episodes = [_episode(item) for item in reversed(channel.findall("item"))]
    episodes = [episode for episode in episodes if episode.name]
    if all(episode.published_utcz is not None for episode in episodes):
        episodes.sort(key=lambda episode: episode.published_utcz or datetime.datetime.min)
    return Feed(
        link=_text(channel, "link"),
        image_url=_attr(channel, f"{ITUNES}image", "href") or _text(channel, "image/url"),
        episodes=episodes,
    )
