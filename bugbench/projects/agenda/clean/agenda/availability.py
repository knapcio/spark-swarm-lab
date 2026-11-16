"""Busy time and free slots for people.

Working hours default to 09:00-17:00 on working days (Monday to Friday, not
a holiday).  Weekends and holidays have no free slots.

``free_slots`` proposes start times on a grid: the first candidate is the
start of working hours and the next ones follow every ``step`` minutes
(15 by default).  A slot must end no later than the end of working hours and
must not overlap any occurrence attended by one of the people.  Occurrences
are half-open, so a slot may start exactly when a meeting ends.
"""
import datetime

from .errors import AgendaError, InvalidTime
from .timeutil import Interval, merge

DEFAULT_HOURS = (datetime.time(9, 0), datetime.time(17, 0))
DAY = datetime.timedelta(days=1)


def _hours(hours):
    opening, closing = DEFAULT_HOURS if hours is None else hours
    if not isinstance(opening, datetime.time) or not isinstance(closing, datetime.time) or not opening < closing:
        raise InvalidTime("working hours must be two times, opening before closing")
    return opening, closing


def _people(people):
    people = [people] if isinstance(people, str) else list(people)
    if not people:
        raise AgendaError("at least one person is needed")
    return people


def busy(calendar, person, day):
    """Merged intervals of ``day`` (midnight to midnight) that ``person`` spends in occurrences."""
    midnight = datetime.datetime.combine(day, datetime.time())
    window = Interval(midnight, midnight + DAY)
    # an occurrence that started the evening before can still overlap this day
    found = []
    for item in calendar.occurrences(midnight - DAY, midnight + DAY, attendee=person):
        if item.interval.overlaps(window):
            found.append(Interval(max(item.start, window.start), min(item.end, window.end)))
    return merge(found)


def busy_minutes(calendar, person, day, hours=None):
    """Minutes of working hours on ``day`` that ``person`` is busy."""
    opening, closing = _hours(hours)
    work = Interval(datetime.datetime.combine(day, opening), datetime.datetime.combine(day, closing))
    total = datetime.timedelta(0)
    for interval in busy(calendar, person, day):
        if interval.overlaps(work):
            total += min(interval.end, work.end) - max(interval.start, work.start)
    return int(total.total_seconds() // 60)


def free_slots(calendar, people, day, duration, step=15, hours=None):
    """Start times on ``day`` at which every one of ``people`` is free for ``duration``."""
    people = _people(people)
    if not isinstance(duration, datetime.timedelta) or duration <= datetime.timedelta(0):
        raise InvalidTime("duration must be a positive timedelta")
    if isinstance(step, bool) or not isinstance(step, int) or step < 1:
        raise InvalidTime("step must be a positive number of minutes")
    opening, closing = _hours(hours)
    if not calendar.is_working_day(day):
        return []
    blocked = merge(interval for person in people for interval in busy(calendar, person, day))
    moment = datetime.datetime.combine(day, opening)
    closing_time = datetime.datetime.combine(day, closing)
    slots = []
    while moment + duration <= closing_time:
        slot = Interval(moment, moment + duration)
        if not any(slot.overlaps(interval) for interval in blocked):
            slots.append(moment)
        moment += datetime.timedelta(minutes=step)
    return slots


def first_common_slot(calendar, people, from_day, duration, days=14, hours=None):
    """Earliest free slot for all ``people`` within ``days`` days from ``from_day``, or None."""
    for offset in range(days):
        slots = free_slots(calendar, people, from_day + offset * DAY, duration, hours=hours)
        if slots:
            return slots[0]
    return None
