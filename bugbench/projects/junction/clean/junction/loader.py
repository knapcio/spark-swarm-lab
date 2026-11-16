"""Text formats and the :class:`Junction` facade.

Timetable text has one statement per line; ``#`` starts a comment::

    station KRK "Krakow Glowny" zone 1 transfer 5
    footpath KRK KRB 250
    service WK mon-fri 2026-03-02..2026-03-31 except 2026-03-13 add 2026-03-14
    trip T1 IC31 WK
      KRK 08:02
      TRN 08:41 08:43
      RZE 09:30

``zone`` and ``transfer`` are optional (defaults 1 and 3).  ``except`` and
``add`` take comma-separated dates.  The indented stop lines of a trip follow
its ``trip`` line; a stop line has one time (arrival = departure) or two
(arrival, departure).  Statements may come in any order as long as stations
and services exist before they are used.

A disruption feed is applied line by line, in order::

    delay T1 2026-03-02 +15 from TRN
    cancel T1 2026-03-03
    reinstate T1 2026-03-03

An error raises :class:`ParseError` with the line number; the lines before it
stay applied.
"""
import re

from . import boards, fares
from .errors import JunctionError, ParseError
from .network import Network
from .planner import MAX_RIDES, Planner
from .timetable import Timetable

_STATION = re.compile(r'station\s+(\S+)\s+"([^"]*)"((?:\s+(?:zone|transfer)\s+\d+)*)')
_OPTION = re.compile(r"(zone|transfer)\s+(\d+)")
_SERVICE = re.compile(r"service\s+(\S+)\s+(\S+)\s+(\S+)\.\.(\S+)((?:\s+(?:except|add)\s+\S+)*)")
_EXTRA = re.compile(r"(except|add)\s+(\S+)")
_DELAY = re.compile(r"delay\s+(\S+)\s+(\S+)\s+\+(\d+)(?:\s+from\s+(\S+))?")


def _statements(text):
    """``(line number, indented, words-or-text)`` for every line that is not blank or a comment."""
    if not isinstance(text, str):
        raise JunctionError("expected text")
    for number, raw in enumerate(text.splitlines(), 1):
        content = raw.split("#", 1)[0].rstrip()
        if content.strip():
            yield number, content[:1].isspace(), content.strip()


def _options(pattern, rest):
    values = {}
    for name, value in pattern.findall(rest):
        if name in values:
            raise JunctionError(f"{name} given twice")
        values[name] = value
    return values


def load(text):
    """Read timetable text into a :class:`Timetable` (with its :class:`Network`)."""
    timetable = Timetable(Network())
    trip = None

    def finish():
        if trip is not None:
            number, trip_id, line, service, stops = trip
            try:
                timetable.add_trip(trip_id, line, service, stops)
            except JunctionError as exc:
                raise ParseError(number, str(exc)) from None

    for number, indented, content in _statements(text):
        try:
            if indented:
                if trip is None:
                    raise JunctionError("stop line outside a trip")
                words = content.split()
                if len(words) not in (2, 3):
                    raise JunctionError("a stop line is: STATION TIME [TIME]")
                trip[4].append((words[0], words[1], words[-1]))
                continue
            finish()
            trip = None
            keyword = content.split()[0]
            if keyword == "station":
                match = _STATION.fullmatch(content)
                if not match:
                    raise JunctionError('expected: station CODE "Name" [zone N] [transfer N]')
                options = _options(_OPTION, match.group(3))
                timetable.network.add_station(match.group(1), match.group(2), int(options.get("zone", 1)),
                                              int(options.get("transfer", 3)))
            elif keyword == "footpath":
                words = content.split()
                if len(words) != 4 or not words[3].isdigit():
                    raise JunctionError("expected: footpath CODE CODE METRES")
                timetable.network.add_footpath(words[1], words[2], int(words[3]))
            elif keyword == "service":
                match = _SERVICE.fullmatch(content)
                if not match:
                    raise JunctionError("expected: service ID DAYS FROM..TO [except DATES] [add DATES]")
                extra = _options(_EXTRA, match.group(5))
                timetable.add_service(match.group(1), match.group(2), match.group(3), match.group(4),
                                      extra.get("except", "").split(",") if "except" in extra else (),
                                      extra.get("add", "").split(",") if "add" in extra else ())
            elif keyword == "trip":
                words = content.split()
                if len(words) != 4:
                    raise JunctionError("expected: trip ID LINE SERVICE")
                trip = (number, words[1], words[2], words[3], [])
            else:
                raise JunctionError(f"unknown statement {keyword!r}")
        except ParseError:
            raise
        except JunctionError as exc:
            raise ParseError(number, str(exc)) from None
    finish()
    return timetable


def apply_disruptions(timetable, text):
    """Apply a disruption feed to ``timetable``; returns the number of lines applied."""
    applied = 0
    for number, _, content in _statements(text):
        words = content.split()
        try:
            if words[0] == "delay":
                match = _DELAY.fullmatch(content)
                if not match:
                    raise JunctionError("expected: delay TRIP DATE +MINUTES [from STATION]")
                timetable.delay(match.group(1), match.group(2), int(match.group(3)), match.group(4))
            elif words[0] in ("cancel", "reinstate") and len(words) == 3:
                getattr(timetable, words[0])(words[1], words[2])
            else:
                raise JunctionError("expected: delay, cancel or reinstate")
        except JunctionError as exc:
            raise ParseError(number, str(exc)) from None
        applied += 1
    return applied


class Junction:
    """One timetable with planning, boards, fares and disruptions."""

    def __init__(self, timetable):
        self.timetable = timetable
        self.network = timetable.network
        self.planner = Planner(timetable)

    @classmethod
    def from_text(cls, text):
        return cls(load(text))

    def plan(self, origin, destination, day, after="00:00", max_rides=MAX_RIDES):
        return self.planner.plan(origin, destination, day, after, max_rides)

    def journeys(self, origin, destination, day, after="00:00", count=3):
        return self.planner.journeys(origin, destination, day, after, count)

    def departures(self, station, day, start="00:00", end="47:59", limit=None):
        return boards.departures(self.timetable, station, day, start, end, limit)

    def arrivals(self, station, day, start="00:00", end="47:59", limit=None):
        return boards.arrivals(self.timetable, station, day, start, end, limit)

    def board(self, station, day, start="00:00", end="47:59", limit=None):
        """Departure board text titled ``"<name> <date>"``."""
        rows = self.departures(station, day, start, end, limit)
        return boards.format_board(self.network, rows, f"{self.network.station(station).name} {day}")

    def fare(self, journey, concession="full"):
        """Fare as text, e.g. ``"5.60"``."""
        return fares.format_money(fares.fare(self.network, journey, concession))

    def apply(self, text):
        return apply_disruptions(self.timetable, text)
