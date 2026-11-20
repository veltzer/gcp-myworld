"""
The videos of YouTube playlists of the user's own account, as YouTube
videos they watched: each one they do not have yet is added, with what
YouTube says of it; one they have is given YouTube's details as they are
now, and keeps everything they wrote of it (rating, review, device, date).
It only ever adds: a video taken out of a playlist since stays.

A playlist does not say when a video was watched (only when it was put in
the playlist), so a video added has no date.
"""

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld import youtube
from myworld.importers.core import Importer, ImporterError, Param, Report, register
from myworld.models import User, YouTubeVideo

ADDED = "YouTube videos added"
REFRESHED = "YouTube videos given YouTube's details"
UNCHANGED = "YouTube videos unchanged"
UNAVAILABLE = "of them YouTube no longer has"

# what YouTube says of a video, as columns: refreshed on a video the user has
DETAILS = ("channel", "category", "duration", "uploaded", "views")


def _client(session: Session, owner: User) -> youtube.Client:
    try:
        return youtube.client_for(session, owner)
    except youtube.YouTubeError as e:
        raise ImporterError(str(e)) from e


def playlists(session: Session, owner: User) -> list[tuple[str, str]]:
    try:
        return youtube.my_playlists(_client(session, owner))
    except youtube.YouTubeError as e:
        raise ImporterError(str(e)) from e


def unavailable(session: Session, owner: User) -> str:
    if not youtube.configured():
        return "Connecting YouTube is not set up on this site"
    if youtube.connection(session, owner) is None:
        return "Connect YouTube first"
    return ""


def run(session: Session, owner: User, params: dict[str, Any], report: Report) -> None:
    client = _client(session, owner)
    try:
        titles = dict(youtube.my_playlists(client))
        ids: dict[str, None] = {}
        for playlist in params["playlists"]:
            found = youtube.playlist_video_ids(client, playlist)
            report.say(f"{titles.get(playlist, playlist)}: {len(found)} videos")
            ids.update(dict.fromkeys(found))
        details = youtube.video_details(client, list(ids))
    except youtube.YouTubeError as e:
        raise ImporterError(str(e)) from e
    have = {
        v.youtube_id: v
        for v in session.scalars(select(YouTubeVideo).where(YouTubeVideo.owner_id == owner.id, YouTubeVideo.youtube_id.in_(list(ids))))
    } if ids else {}
    counted: Counter[str] = Counter()
    for video_id in ids:
        said = details.get(video_id)
        video = have.get(video_id)
        if video is None:
            if said is None:
                # YouTube no longer has it: only its id is known
                session.add(YouTubeVideo(owner_id=owner.id, youtube_id=video_id, name="", review="", watched_at="", unavailable=True))
                counted[UNAVAILABLE] += 1
            else:
                session.add(YouTubeVideo(owner_id=owner.id, youtube_id=video_id, review="", watched_at="", unavailable=False, **said))
            counted[ADDED] += 1
            continue
        changed = False
        if said is None:
            # what was known of it stays; only that it is gone is new
            changed = not video.unavailable
            video.unavailable = True
        else:
            for column in DETAILS:
                if getattr(video, column) != said[column]:
                    setattr(video, column, said[column])
                    changed = True
            if video.unavailable:
                video.unavailable = False
                changed = True
            # one that had no name gets YouTube's; one the user named keeps theirs
            if not video.name and said["name"]:
                video.name = said["name"]
                changed = True
        counted[REFRESHED if changed else UNCHANGED] += 1
    # always in this order, whatever order they came in
    for what in (ADDED, UNAVAILABLE, REFRESHED, UNCHANGED):
        if counted[what]:
            report.count(what, counted[what])


IMPORTER = register(Importer(
    name="youtube-playlists",
    title="YouTube playlists",
    description=(
        "The videos of playlists of your YouTube account, as videos you watched. Only the ones you do not have are "
        "added; the ones you have get YouTube's details as they are now and keep your rating, review and date. "
        "Safe to run again: it only ever adds."
    ),
    dataset="youtube",
    params=(
        Param(
            name="playlists", title="Playlists", kind="choices", required=True,
            description="The playlists of your YouTube account to import", choices=playlists,
        ),
    ),
    run=run,
    unavailable=unavailable,
))
