"""Read-only reports: day agenda, weekly hours and conflicts.

Report rows use plain types (str, int) so that callers can print or compare
them directly.  Times are written ``HH:MM`` and dates ``YYYY-MM-DD``.
"""
import datetime

from .timeutil import format_duration, monday_of

DAY = datetime.timedelta(days=1)


def _clock(moment):
    return moment.strftime("%H:%M")


def describe(item):
    """``09:30-09:45 STANDUP Daily standup @R1 [ann, bob]`` plus `` (moved from 09:00)`` when moved."""
    text = f"{_clock(item.start)}-{_clock(item.end)} {item.event_id} {item.title}"
    if item.room:
        text += f" @{item.room}"
    if item.attendees:
        text += " [" + ", ".join(item.attendees) + "]"
    if item.moved:
        original = _clock(item.original_start)
        if item.original_start.date() != item.start.date():
            original = item.original_start.strftime("%Y-%m-%d ") + original
        text += f" (moved from {original})"
    return text


def day_agenda(calendar, day, attendee=None, room=None):
    """One line per occurrence starting on ``day``, in start order."""
    start = datetime.datetime.combine(day, datetime.time())
    return [describe(item) for item in calendar.occurrences(start, start + DAY, attendee=attendee, room=room)]


def series_dates(calendar, event_id):
    """``YYYY-MM-DD HH:MM`` of every visible occurrence of a finite event."""
    return [item.start.strftime("%Y-%m-%d %H:%M") for item in calendar.series(event_id)]


def week_hours(calendar, day):
    """Meeting time per attendee for the Monday-to-Sunday week containing ``day``.

    Returns ``[[person, "7h30m"], ...]`` sorted by person.  Each occurrence
    counts in full for the week in which it starts.
    """
    monday = datetime.datetime.combine(monday_of(day), datetime.time())
    totals = {}
    for item in calendar.occurrences(monday, monday + 7 * DAY):
        for person in item.attendees:
            totals[person] = totals.get(person, datetime.timedelta(0)) + (item.end - item.start)
    return [[person, format_duration(totals[person])] for person in sorted(totals)]


def conflicts(calendar, start, end):
    """Pairs of overlapping occurrences that share a room or an attendee.

    Each row is ``[first id, first start, second id, second start, reason]``
    where the first occurrence is the earlier one in listing order and the
    reason is ``room R1`` or, when no room is shared, ``attendee ann`` for the
    alphabetically first shared attendee.  Back-to-back occurrences do not
    conflict.  Rows are in listing order of the first, then the second item.
    """
    items = calendar.occurrences(start, end)
    rows = []
    for index, first in enumerate(items):
        for second in items[index + 1:]:
            if second.start >= first.end:
                break
            if first.room and first.room == second.room:
                reason = f"room {first.room}"
            else:
                shared = sorted(set(first.attendees) & set(second.attendees))
                if not shared:
                    continue
                reason = f"attendee {shared[0]}"
            rows.append([first.event_id, first.start.strftime("%Y-%m-%d %H:%M"),
                         second.event_id, second.start.strftime("%Y-%m-%d %H:%M"), reason])
    return rows
