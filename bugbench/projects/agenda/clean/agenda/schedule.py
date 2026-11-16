"""A line-oriented schedule language for building and querying a calendar.

One command per line; blank lines and lines starting with ``#`` are ignored::

    holiday 2026-04-06
    event STANDUP "Daily standup" at 2026-03-02 09:30 for 15m repeat weekly on weekdays room R1 with ann,bob
    event REVIEW "Design review" at 2026-03-04 14:00 for 1h30m with ann
    cancel STANDUP 2026-03-10 09:30
    move STANDUP 2026-03-11 09:30 to 2026-03-11 10:00
    split STANDUP at 2026-03-16 09:30 as STANDUP-2 room R2
    remove REVIEW
    free ann,bob on 2026-03-03 for 30m
    agenda 2026-03-03 for ann
    hours 2026-03-03

The words after ``repeat`` up to ``room`` or ``with`` form the recurrence
rule (see :func:`agenda.recurrence.parse_rule`).  ``replay`` runs the
commands in order and stops at the first failing line by raising
:class:`ScheduleError` with its line number.
"""
from . import reports
from .availability import free_slots
from .calendar import Calendar
from .errors import AgendaError, ScheduleError
from .recurrence import parse_rule
from .timeutil import parse_date, parse_datetime, parse_duration


def tokenize(text, line=0):
    """Split one line into words; double quotes group words and ``\\"`` escapes a quote."""
    words, current, quoted, index, started = [], [], False, 0, False
    while index < len(text):
        char = text[index]
        if quoted:
            if char == "\\" and index + 1 < len(text):
                current.append(text[index + 1])
                index += 1
            elif char == '"':
                quoted = False
            else:
                current.append(char)
        elif char == '"':
            quoted, started = True, True
        elif char.isspace():
            if current or started:
                words.append("".join(current))
                current, started = [], False
        else:
            current.append(char)
        index += 1
    if quoted:
        raise ScheduleError(line, "unterminated quote")
    if current or started:
        words.append("".join(current))
    return words


def _take(words, keyword, count=1):
    """Remove ``keyword`` and the ``count`` words after it; returns them or None if absent."""
    if keyword not in words:
        return None
    index = words.index(keyword)
    values = words[index + 1:index + 1 + count]
    if len(values) != count:
        raise AgendaError(f"{keyword!r} needs {count} value(s)")
    del words[index:index + 1 + count]
    return values


def _expect(words, size, usage):
    if len(words) != size:
        raise AgendaError(f"usage: {usage}")


def _people(text):
    return [name.strip() for name in text.split(",") if name.strip()]


def _event(calendar, words):
    if len(words) < 7 or words[2] != "at" or words[5] != "for":
        raise AgendaError('usage: event ID "Title" at DATE TIME for DURATION [repeat RULE] [room R] [with a,b]')
    event_id, title = words[0], words[1]
    start, duration = parse_datetime(words[3], words[4]), parse_duration(words[6])
    rest = words[7:]
    room = _take(rest, "room")
    attendees = _take(rest, "with")
    rule = None
    if rest:
        if rest[0] != "repeat":
            raise AgendaError(f"unexpected {rest[0]!r}")
        rule = parse_rule(rest[1:])
    calendar.add_event(event_id, title, start, duration, rule, room[0] if room else None,
                       _people(attendees[0]) if attendees else ())
    return {"event": event_id}


def _split(calendar, words):
    room, title = _take(words, "room"), _take(words, "title")
    if len(words) != 6 or words[1] != "at" or words[4] != "as":
        raise AgendaError("usage: split ID at DATE TIME as NEW_ID [room R] [title T]")
    new = calendar.split(words[0], parse_datetime(words[2], words[3]), words[5],
                         title=title[0] if title else None, **({"room": room[0]} if room else {}))
    return {"event": new.event_id}


def execute(calendar, words):
    """Run one tokenized command; returns a result dict (without the line number)."""
    command, args = words[0], words[1:]
    if command == "event":
        result = _event(calendar, args)
    elif command == "holiday":
        _expect(args, 1, "holiday DATE")
        calendar.add_holiday(parse_date(args[0]))
        result = {}
    elif command == "cancel":
        _expect(args, 3, "cancel ID DATE TIME")
        calendar.cancel(args[0], parse_datetime(args[1], args[2]))
        result = {}
    elif command == "move":
        _expect(args, 6, "move ID DATE TIME to DATE TIME")
        if args[3] != "to":
            raise AgendaError("usage: move ID DATE TIME to DATE TIME")
        calendar.move(args[0], parse_datetime(args[1], args[2]), parse_datetime(args[4], args[5]))
        result = {}
    elif command == "split":
        result = _split(calendar, args)
    elif command == "remove":
        _expect(args, 1, "remove ID")
        calendar.remove(args[0])
        result = {}
    elif command == "free":
        _expect(args, 5, "free PEOPLE on DATE for DURATION")
        if args[1] != "on" or args[3] != "for":
            raise AgendaError("usage: free PEOPLE on DATE for DURATION")
        slots = free_slots(calendar, _people(args[0]), parse_date(args[2]), parse_duration(args[4]))
        result = {"slots": [moment.strftime("%H:%M") for moment in slots]}
    elif command == "agenda":
        person = _take(args, "for")
        _expect(args, 1, "agenda DATE [for PERSON]")
        result = {"lines": reports.day_agenda(calendar, parse_date(args[0]), attendee=person[0] if person else None)}
    elif command == "hours":
        _expect(args, 1, "hours DATE")
        result = {"hours": reports.week_hours(calendar, parse_date(args[0]))}
    else:
        raise AgendaError(f"unknown command {command!r}")
    return dict(result, command=command)


def replay(text, calendar=None):
    """Execute every command of ``text``; returns ``(calendar, results)``."""
    calendar = calendar if calendar is not None else Calendar()
    results = []
    for number, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        words = tokenize(stripped, number)
        try:
            result = execute(calendar, words)
        except ScheduleError:
            raise
        except AgendaError as exc:
            raise ScheduleError(number, str(exc)) from exc
        result["line"] = number
        results.append(result)
    return calendar, results
