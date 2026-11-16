"""Stations, fare zones, minimum transfer times and footpaths.

Every station has a fare zone (1-99) and a minimum transfer time (0-30
minutes, default 3).  Changing trips at the same station needs at least that
many minutes between the arrival and the next departure.

A footpath joins two different stations in both directions.  Its walking time
is its length in metres divided by the walking speed of 80 metres per minute,
rounded up to a whole minute (250 m take 4 minutes).  A walk replaces the
transfer time: a departure at the far end can be caught as soon as the walk
is over.
"""
import math
import re
from dataclasses import dataclass

from .errors import JunctionError, UnknownStation

WALK_SPEED = 80          # metres per minute
MAX_FOOTPATH = 3000      # metres
CODE = re.compile(r"[A-Z][A-Z0-9]{1,5}")


@dataclass(frozen=True)
class Station:
    code: str
    name: str
    zone: int
    transfer: int


@dataclass(frozen=True)
class Footpath:
    start: str
    end: str
    metres: int
    minutes: int


def whole(value, low, high, what):
    """``value`` if it is an int (not a bool) from ``low`` to ``high``, else :class:`JunctionError`."""
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise JunctionError(f"{what} must be a whole number from {low} to {high}, got {value!r}")
    return value


def walking_minutes(metres):
    """Walking time of a footpath of ``metres`` (1-3000): metres / 80, rounded up."""
    return math.ceil(whole(metres, 1, MAX_FOOTPATH, "footpath length") / WALK_SPEED)


class Network:
    """The stations and footpaths of a timetable."""

    def __init__(self):
        self._stations = {}
        self._paths = {}

    def add_station(self, code, name, zone=1, transfer=3):
        """Add a station.  Codes are 2-6 upper-case letters or digits, starting with a letter."""
        if not isinstance(code, str) or not CODE.fullmatch(code):
            raise JunctionError(f"bad station code {code!r}")
        if code in self._stations:
            raise JunctionError(f"station {code} already exists")
        if not isinstance(name, str) or not name.strip():
            raise JunctionError(f"station {code} needs a name")
        station = Station(code, " ".join(name.split()), whole(zone, 1, 99, "zone"),
                          whole(transfer, 0, 30, "transfer time"))
        self._stations[code] = station
        self._paths[code] = {}
        return station

    def station(self, code):
        """The :class:`Station` with ``code``; :class:`UnknownStation` if there is none."""
        if not isinstance(code, str) or code not in self._stations:
            raise UnknownStation(f"unknown station {code!r}")
        return self._stations[code]

    def __contains__(self, code):
        return isinstance(code, str) and code in self._stations

    def stations(self, zone=None):
        """Stations sorted by code, optionally only those in ``zone``."""
        return [station for _, station in sorted(self._stations.items()) if zone is None or station.zone == zone]

    def find(self, text):
        """Stations whose name contains ``text`` (ignoring case), sorted by name, then code."""
        if not isinstance(text, str) or not text.strip():
            raise JunctionError("search text must not be empty")
        needle = text.strip().casefold()
        found = [station for station in self._stations.values() if needle in station.name.casefold()]
        return sorted(found, key=lambda station: (station.name, station.code))

    def transfer_minutes(self, code):
        """Minimum transfer time at ``code``."""
        return self.station(code).transfer

    def add_footpath(self, start, end, metres):
        """Add a footpath usable in both directions; returns the ``start`` -> ``end`` :class:`Footpath`."""
        self.station(start)
        self.station(end)
        if start == end:
            raise JunctionError("a footpath joins two different stations")
        if end in self._paths[start]:
            raise JunctionError(f"footpath {start}-{end} already exists")
        minutes = walking_minutes(metres)
        self._paths[start][end] = Footpath(start, end, metres, minutes)
        self._paths[end][start] = Footpath(end, start, metres, minutes)
        return self._paths[start][end]

    def footpath(self, start, end):
        """The footpath from ``start`` to ``end``; :class:`JunctionError` if there is none."""
        self.station(start)
        self.station(end)
        if end not in self._paths[start]:
            raise JunctionError(f"no footpath from {start} to {end}")
        return self._paths[start][end]

    def footpaths(self, code):
        """Footpaths leaving ``code``, shortest walk first (ties by the far station's code)."""
        self.station(code)
        return sorted(self._paths[code].values(), key=lambda path: (path.minutes, path.end))

    def zones(self, codes):
        """Sorted distinct fare zones of the given stations."""
        return sorted({self.station(code).zone for code in codes})
