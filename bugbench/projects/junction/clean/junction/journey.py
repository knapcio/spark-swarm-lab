"""Journeys: rides on trips and walks between stations.

Times are minutes of the planning day's listing; descriptions show them as
clock times (``"00:40+1"`` after midnight).  A journey starts and ends with a
ride.  The number of transfers is the number of rides minus one; a walk
between two rides belongs to the transfer and does not count extra.
"""
from dataclasses import dataclass

from .clock import format_duration, wall_time
from .errors import JunctionError


@dataclass(frozen=True)
class Ride:
    trip_id: str
    line: str
    stops: tuple        # station codes from boarding to alighting
    departure: int
    arrival: int

    @property
    def start(self):
        return self.stops[0]

    @property
    def end(self):
        return self.stops[-1]

    @property
    def minutes(self):
        return self.arrival - self.departure

    def describe(self):
        return (f"{wall_time(self.departure)} {self.start} -> {wall_time(self.arrival)} {self.end}"
                f"  {self.line} {self.trip_id}")


@dataclass(frozen=True)
class Walk:
    start: str
    end: str
    departure: int
    arrival: int
    metres: int

    @property
    def minutes(self):
        return self.arrival - self.departure

    def describe(self):
        return f"walk {self.minutes} min ({self.metres} m) {self.start} -> {self.end}"


class Journey:
    """An immutable sequence of legs (``Ride`` and ``Walk``)."""

    def __init__(self, legs):
        legs = tuple(legs)
        if not legs or not isinstance(legs[0], Ride) or not isinstance(legs[-1], Ride):
            raise JunctionError("a journey starts and ends with a ride")
        for before, after in zip(legs, legs[1:]):
            if after.departure < before.arrival or after.start != before.end:
                raise JunctionError("journey legs must connect in place and time")
        self.legs = legs

    @property
    def origin(self):
        return self.legs[0].start

    @property
    def destination(self):
        return self.legs[-1].end

    @property
    def departure(self):
        return self.legs[0].departure

    @property
    def arrival(self):
        return self.legs[-1].arrival

    @property
    def duration(self):
        return self.arrival - self.departure

    @property
    def rides(self):
        return [leg for leg in self.legs if isinstance(leg, Ride)]

    @property
    def transfers(self):
        return len(self.rides) - 1

    @property
    def walking(self):
        """Total walking minutes."""
        return sum(leg.minutes for leg in self.legs if isinstance(leg, Walk))

    def waits(self):
        """Minutes spent waiting before each leg after the first (walks included)."""
        return [after.departure - before.arrival for before, after in zip(self.legs, self.legs[1:])]

    def stations(self):
        """Every station the journey passes, in order, each consecutive station once."""
        found = []
        for leg in self.legs:
            for code in (leg.stops if isinstance(leg, Ride) else (leg.start, leg.end)):
                if not found or found[-1] != code:
                    found.append(code)
        return found

    def summary(self):
        """``"08:02 KRK -> 09:30 RZE, 1h 28m, 1 transfer"``."""
        count = self.transfers
        return (f"{wall_time(self.departure)} {self.origin} -> {wall_time(self.arrival)} {self.destination}, "
                f"{format_duration(self.duration)}, {count} transfer{'' if count == 1 else 's'}")

    def describe(self):
        """The summary line followed by one line per leg."""
        return "\n".join([self.summary()] + ["  " + leg.describe() for leg in self.legs])

    def __eq__(self, other):
        return isinstance(other, Journey) and self.legs == other.legs

    def __hash__(self):
        return hash(self.legs)

    def __repr__(self):
        return f"Journey({self.summary()!r})"
