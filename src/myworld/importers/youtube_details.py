"""
YouTube's details (channel, category, length, upload day, views) for the
user's YouTube videos that have none: the ones that came without them (a
watch history that had only their names), and the ones YouTube no longer
had, in case it has them again. A video YouTube does not have is marked so,
and keeps what was known of it. Nothing is added, and what the user wrote
is never changed.
"""

from typing import TYPE_CHECKING, Any

from sqlalchemy import or_, select

from myworld import youtube
from myworld.importers.core import Importer, ImporterError, Report, register
from myworld.importers.youtube_playlists import client_of, store, unavailable
from myworld.models import User, YouTubeVideo

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def lacking(session: Session, owner: User) -> list[str]:
    """ The ids of the owner's videos without YouTube's details: no channel, or no length. """
    return list(session.scalars(
        select(YouTubeVideo.youtube_id)
        .where(YouTubeVideo.owner_id == owner.id, or_(YouTubeVideo.channel == "", YouTubeVideo.duration.is_(None)))
        .order_by(YouTubeVideo.youtube_id)
    ))


def run(session: Session, owner: User, _params: dict[str, Any], report: Report) -> None:
    ids = lacking(session, owner)
    report.say(f"{len(ids)} videos without YouTube's details")
    if not ids:
        return
    client = client_of(session, owner)
    try:
        details = youtube.video_details(client, ids)
    except youtube.YouTubeError as e:
        raise ImporterError(str(e)) from e
    store(session, owner, ids, details, report)


IMPORTER = register(Importer(
    name="youtube-details",
    title="YouTube details",
    description=(
        "Gives your YouTube videos that have no channel or length YouTube's details: channel, category, length, "
        "upload day and views. A video YouTube no longer has is marked so. Adds nothing and keeps your rating, "
        "review and date. Safe to run again."
    ),
    dataset="youtube",
    params=(),
    run=run,
    unavailable=unavailable,
))
