"""
Checks of the YouTube videos.
"""

import re

from sqlalchemy.orm import Session

from myworld.checks.core import (
    Result,
    check,
    dated,
    problem,
    rows,
)
from myworld.models import (
    YOUTUBE_ID_LENGTH,
    YouTubeVideo,
)

YOUTUBE_ID = re.compile(rf"[A-Za-z0-9_-]{{{YOUTUBE_ID_LENGTH}}}")


@check("youtube-ids", "Every YouTube video has a well-formed id", "YouTube videos", "youtube")
def check_youtube_ids(session: Session) -> Result:
    """
    Every YouTube video, of every account, has an id YouTube could have
    given: 11 letters, digits, - and _. One that is not links to no video.
    """
    videos = rows(session, YouTubeVideo)
    problems = [
        problem(v, f"has the id {v.youtube_id!r}, not {YOUTUBE_ID_LENGTH} letters, digits, - and _")
        for v in videos
        if not YOUTUBE_ID.fullmatch(v.youtube_id)
    ]
    return Result(checked=len(videos), problems=problems)


@check("youtube-dates", "Every YouTube video has a date", "YouTube videos", "youtube")
def check_youtube_dates(session: Session) -> Result:
    """ Every YouTube video, of every account, has the date it was watched (a day, a month, a year or a full time). """
    videos = rows(session, YouTubeVideo)
    return Result(checked=len(videos), problems=[problem(v, "has no date") for v in videos if not dated(v)])


@check("youtube-reviews", "Every YouTube video is rated and reviewed", "YouTube videos", "youtube")
def check_youtube_reviews(session: Session) -> Result:
    """ Every YouTube video, of every account, has a rating and a review. """
    videos = rows(session, YouTubeVideo)
    problems = []
    for video in videos:
        missing = [what for what, absent in (("rating", video.rating is None), ("review", not video.review.strip())) if absent]
        if missing:
            problems.append(problem(video, f"has no {' and no '.join(missing)}"))
    return Result(checked=len(videos), problems=problems)


@check("youtube-devices", "Every YouTube video has a device", "YouTube videos", "youtube")
def check_youtube_devices(session: Session) -> Result:
    """ Every YouTube video, of every account, has the device it was watched on. """
    videos = rows(session, YouTubeVideo)
    return Result(checked=len(videos), problems=[problem(v, "has no device") for v in videos if v.device_id is None])
