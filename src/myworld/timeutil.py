"""
Naive UTC datetimes. The *_utcz columns are plain DateTime columns: they hold
UTC with no tzinfo, and read back without one. These make such values (to
store or to compare with those read) without a bare naive constructor.
"""

import datetime as dt


def naive_utc(year: int, month: int = 1, day: int = 1, hour: int = 0, minute: int = 0, second: int = 0) -> dt.datetime:
    """ A UTC moment, without tzinfo, as the *_utcz columns hold it. """
    return dt.datetime(year, month, day, hour, minute, second, tzinfo=dt.UTC).replace(tzinfo=None)


# earlier than any stored moment: where a missing one sorts first
EARLIEST = naive_utc(1)
