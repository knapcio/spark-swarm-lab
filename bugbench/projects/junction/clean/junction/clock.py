"""Times of day, durations, dates, weekday sets and service calendars.

Timetable times are whole minutes after midnight of the *service day*.  A trip
that runs past midnight keeps counting, so 00:40 the next morning is written
``24:40`` (1480 minutes).  Times go from ``00:00`` to ``47:59``.  Passengers see
clock times instead: ``wall_time(1480)`` is ``"00:40+1"``.

A *service* says on which days its trips run: a set of weekdays from a first
to a last date (both included), minus ``removed`` dates, plus ``added`` dates.
"""
import datetime
import re
from dataclasses import dataclass

from .errors import InvalidTime, JunctionError

MINUTES_PER_DAY = 24 * 60
LATEST = 2 * MINUTES_PER_DAY - 1
ONE_DAY = datetime.timedelta(days=1)
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_TIME = re.compile(r"(\d{1,2}):(\d\d)")
_DURATION = re.compile(r"(?:(\d+)h)?(?:(\d+)m?)?")
_DATE = re.compile(r"\d{4}-\d\d-\d\d")


def _check_minutes(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= LATEST:
        raise InvalidTime(f"a time must be 0-{LATEST} minutes, got {value!r}")
    return value


def parse_time(value):
    """``"H:MM"`` or ``"HH:MM"`` (hours 0-47), or an int of minutes -> minutes."""
    if not isinstance(value, str):
        return _check_minutes(value)
    match = _TIME.fullmatch(value.strip())
    if not match or int(match.group(2)) > 59:
        raise InvalidTime(f"bad time {value!r}")
    return _check_minutes(int(match.group(1)) * 60 + int(match.group(2)))


def format_time(minutes):
    """Timetable notation: 520 -> ``"08:40"``, 1480 -> ``"24:40"``."""
    hours, rest = divmod(_check_minutes(minutes), 60)
    return f"{hours:02d}:{rest:02d}"


def wall_time(minutes):
    """Clock notation for passengers: 520 -> ``"08:40"``, 1480 -> ``"00:40+1"``."""
    days, rest = divmod(_check_minutes(minutes), MINUTES_PER_DAY)
    return format_time(rest) + (f"+{days}" if days else "")


def parse_duration(value):
    """``"45"``, ``"45m"``, ``"2h"`` or ``"1h05m"`` (or an int) -> minutes, at most 24 hours."""
    if isinstance(value, bool):
        raise JunctionError("a duration must be text or a whole number of minutes")
    if isinstance(value, int):
        minutes = value
    elif isinstance(value, str):
        match = _DURATION.fullmatch(value.strip())
        if not match or not any(match.groups()):
            raise JunctionError(f"bad duration {value!r}")
        hours, minutes = int(match.group(1) or 0), int(match.group(2) or 0)
        if match.group(1) and minutes > 59:
            raise JunctionError(f"bad duration {value!r}")
        minutes += hours * 60
    else:
        raise JunctionError("a duration must be text or a whole number of minutes")
    if not 0 <= minutes <= MINUTES_PER_DAY:
        raise JunctionError(f"duration out of range: {value!r}")
    return minutes


def format_duration(minutes):
    """``"45m"``, ``"2h 00m"``, ``"1h 05m"``."""
    hours, rest = divmod(minutes, 60)
    return f"{hours}h {rest:02d}m" if hours else f"{rest}m"


def parse_date(value):
    """``"YYYY-MM-DD"`` or a ``datetime.date`` (not a ``datetime``) -> ``date``."""
    if isinstance(value, datetime.datetime):
        raise JunctionError("expected a date, not a datetime")
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str) and _DATE.fullmatch(value.strip()):
        try:
            return datetime.date.fromisoformat(value.strip())
        except ValueError:
            pass
    raise JunctionError(f"bad date {value!r}")


def parse_weekdays(text):
    """``"daily"``, ``"mon-fri"``, ``"sat,sun"`` or a wrapping range such as
    ``"fri-mon"`` -> sorted tuple of weekday numbers (Monday is 0)."""
    if not isinstance(text, str) or not text.strip():
        raise JunctionError("weekdays must be text such as 'mon-fri'")
    text = text.strip().lower()
    if text == "daily":
        return tuple(range(7))
    days = set()
    for part in text.split(","):
        first, dash, last = part.strip().partition("-")
        if first not in WEEKDAYS or (dash and last not in WEEKDAYS):
            raise JunctionError(f"bad weekdays {text!r}")
        start = WEEKDAYS.index(first)
        stop = WEEKDAYS.index(last) if dash else start
        days.update((start + step) % 7 for step in range((stop - start) % 7 + 1))
    return tuple(sorted(days))


def weekday_text(days):
    """Display form of a weekday set: ``"daily"``, ``"mon-fri"``, ``"mon,wed,fri-sun"``.

    Runs of three or more consecutive days are written as a range."""
    days = sorted(set(days))
    if len(days) == 7:
        return "daily"
    runs = []
    for day in days:
        if runs and day == runs[-1][-1] + 1:
            runs[-1].append(day)
        else:
            runs.append([day])
    parts = []
    for run in runs:
        if len(run) >= 3:
            parts.append(f"{WEEKDAYS[run[0]]}-{WEEKDAYS[run[-1]]}")
        else:
            parts += [WEEKDAYS[day] for day in run]
    return ",".join(parts)


@dataclass(frozen=True)
class Service:
    service_id: str
    weekdays: tuple
    start: datetime.date
    end: datetime.date
    removed: tuple = ()
    added: tuple = ()

    def runs_on(self, day):
        """True on an added date, or on a listed weekday from start to end (inclusive) that is not removed."""
        if day in self.added:
            return True
        return self.start <= day <= self.end and day.weekday() in self.weekdays and day not in self.removed

    def describe(self):
        text = f"{self.service_id} {weekday_text(self.weekdays)} {self.start}..{self.end}"
        if self.removed:
            text += " except " + ",".join(str(day) for day in self.removed)
        if self.added:
            text += " add " + ",".join(str(day) for day in self.added)
        return text
