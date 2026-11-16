"""Service calendars, trips, disruptions and the daily connection listing.

Each trip belongs to a service (see ``clock.Service``) that says on which
days it runs.  Trip times are minutes after midnight of the service day.

Disruptions apply to one trip on one service day.  A cancellation takes the
trip out; a delay shifts the arrival at one stop and every later time of the
trip (without a stop: the whole trip).  A new delay for the same trip and day
replaces the old one, and a delay of 0 removes it.  Disruptions take effect at
once for every listing, board and journey.

The *listing* of a calendar day holds the connections (one hop between two
consecutive stops) that run on it, see :meth:`Timetable.connections`.
"""
import datetime
import re
from dataclasses import dataclass

from .clock import LATEST, MINUTES_PER_DAY, ONE_DAY, Service, parse_date, parse_time, parse_weekdays
from .errors import JunctionError, NotRunning, UnknownTrip
from .network import whole

MAX_DELAY = 720
IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,15}")


def _ident(value, what):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise JunctionError(f"bad {what} {value!r}")
    return value


@dataclass(frozen=True)
class StopTime:
    station: str
    arrival: int
    departure: int


@dataclass(frozen=True)
class Trip:
    trip_id: str
    line: str
    service_id: str
    stops: tuple

    def stop_index(self, station):
        for index, stop in enumerate(self.stops):
            if stop.station == station:
                return index
        raise JunctionError(f"trip {self.trip_id} does not call at {station}")

    @property
    def origin(self):
        return self.stops[0].station

    @property
    def terminus(self):
        return self.stops[-1].station


@dataclass(frozen=True)
class Connection:
    """One hop of a trip between two consecutive stops, in minutes of the listing's day."""
    trip_id: str
    line: str
    service_day: datetime.date
    index: int
    start: str
    end: str
    departure: int
    arrival: int
    departure_delay: int
    arrival_delay: int


class Timetable:
    """Services and trips over a :class:`~junction.network.Network`, plus disruptions."""

    def __init__(self, network):
        self.network = network
        self._services = {}
        self._trips = {}
        self._delays = {}        # (trip id, service day) -> (minutes, index of the first delayed stop)
        self._cancelled = set()  # (trip id, service day)
        self._listings = {}      # calendar day -> tuple of connections

    def add_service(self, service_id, weekdays, start, end, removed=(), added=()):
        """Add a service; ``weekdays`` is text for ``parse_weekdays``."""
        _ident(service_id, "service id")
        if service_id in self._services:
            raise JunctionError(f"service {service_id} already exists")
        start, end = parse_date(start), parse_date(end)
        if end < start:
            raise JunctionError(f"service {service_id} ends before it starts")
        service = Service(service_id, parse_weekdays(weekdays), start, end,
                          tuple(sorted({parse_date(day) for day in removed})),
                          tuple(sorted({parse_date(day) for day in added})))
        self._services[service_id] = service
        self._listings.clear()
        return service

    def service(self, service_id):
        if service_id not in self._services:
            raise JunctionError(f"unknown service {service_id!r}")
        return self._services[service_id]

    def add_trip(self, trip_id, line, service_id, stops):
        """Add a trip.  ``stops`` holds ``(station, arrival, departure)``; the first stop's arrival
        and the last stop's departure may be ``None``.  A stop never departs before it is
        reached, the trip needs at least one minute between stops and calls at a station once."""
        _ident(trip_id, "trip id")
        _ident(line, "line")
        if trip_id in self._trips:
            raise JunctionError(f"trip {trip_id} already exists")
        self.service(service_id)
        stops = list(stops)
        if len(stops) < 2:
            raise JunctionError(f"trip {trip_id} needs at least two stops")
        built, previous = [], None
        for position, raw in enumerate(stops):
            try:
                station, arrival, departure = raw
            except (TypeError, ValueError):
                raise JunctionError(f"trip {trip_id}: a stop is (station, arrival, departure)") from None
            self.network.station(station)
            if position == 0 and arrival is None:
                arrival = departure
            if position == len(stops) - 1 and departure is None:
                departure = arrival
            arrival, departure = parse_time(arrival), parse_time(departure)
            if departure < arrival or (previous is not None and arrival <= previous):
                raise JunctionError(f"trip {trip_id}: times must increase along the trip")
            if any(stop.station == station for stop in built):
                raise JunctionError(f"trip {trip_id} calls at {station} twice")
            built.append(StopTime(station, arrival, departure))
            previous = departure
        trip = self._trips[trip_id] = Trip(trip_id, line, service_id, tuple(built))
        self._listings.clear()
        return trip

    def trip(self, trip_id):
        if not isinstance(trip_id, str) or trip_id not in self._trips:
            raise UnknownTrip(f"unknown trip {trip_id!r}")
        return self._trips[trip_id]

    def trips(self, line=None):
        """Trips sorted by id, optionally of one line."""
        return [trip for _, trip in sorted(self._trips.items()) if line is None or trip.line == line]

    def lines(self):
        return sorted({trip.line for trip in self._trips.values()})

    def trips_on(self, day):
        """Ids of the trips whose service runs on service ``day``, sorted (cancelled trips included)."""
        day = parse_date(day)
        return [trip_id for trip_id, trip in sorted(self._trips.items()) if self._services[trip.service_id].runs_on(day)]

    def _running(self, trip_id, day):
        trip, day = self.trip(trip_id), parse_date(day)
        if not self._services[trip.service_id].runs_on(day):
            raise NotRunning(f"trip {trip_id} does not run on {day}")
        return trip, day

    def delay(self, trip_id, day, minutes, from_station=None):
        """Delay ``trip_id`` on service ``day`` by ``minutes`` (0-720) from ``from_station`` on."""
        trip, day = self._running(trip_id, day)
        whole(minutes, 0, MAX_DELAY, "delay")
        first = 0 if from_station is None else trip.stop_index(from_station)
        if trip.stops[-1].arrival + minutes > LATEST:
            raise JunctionError(f"trip {trip_id} would run past 47:59")
        if minutes:
            self._delays[(trip_id, day)] = (minutes, first)
        else:
            self._delays.pop((trip_id, day), None)
        self._invalidate(day)

    def cancel(self, trip_id, day):
        trip, day = self._running(trip_id, day)
        if (trip_id, day) in self._cancelled:
            raise JunctionError(f"trip {trip_id} is already cancelled on {day}")
        self._cancelled.add((trip_id, day))
        self._invalidate(day)

    def reinstate(self, trip_id, day):
        """Undo a cancellation (delays stay)."""
        trip, day = self._running(trip_id, day)
        if (trip_id, day) not in self._cancelled:
            raise JunctionError(f"trip {trip_id} is not cancelled on {day}")
        self._cancelled.discard((trip_id, day))
        self._invalidate(day)

    def is_cancelled(self, trip_id, day):
        return (self.trip(trip_id).trip_id, parse_date(day)) in self._cancelled

    def disruptions(self):
        """``"2026-03-02 T1 cancelled"`` and ``"2026-03-02 T1 +15 from TRN"`` lines, by day, then trip."""
        lines = [(day, trip_id, "cancelled") for trip_id, day in self._cancelled]
        lines += [(day, trip_id, f"+{minutes} from {self._trips[trip_id].stops[first].station}")
                  for (trip_id, day), (minutes, first) in self._delays.items()]
        return [f"{day} {trip_id} {text}" for day, trip_id, text in sorted(lines)]

    def stop_times(self, trip_id, day):
        """Expected ``[(station, arrival, departure, delay)]`` on service ``day``, in service-day minutes."""
        trip, day = self._running(trip_id, day)
        minutes, first = self._delays.get((trip_id, day), (0, 0))
        return [(stop.station, stop.arrival + shift, stop.departure + shift, shift)
                for shift, stop in ((minutes if index >= first else 0, stop) for index, stop in enumerate(trip.stops))]

    def _hops(self, trip_id, service_day, shift):
        trip, times, found = self._trips[trip_id], self.stop_times(trip_id, service_day), []
        for index in range(len(times) - 1):
            start, _, departure, departure_delay = times[index]
            end, arrival, _, arrival_delay = times[index + 1]
            if departure - shift < 0:
                continue
            found.append(Connection(trip_id, trip.line, service_day, index, start, end, departure - shift,
                                    arrival - shift, departure_delay, arrival_delay))
        return found

    def connections(self, day):
        """The listing of calendar ``day``, sorted by departure, arrival, trip id and stop.

        It holds every connection of the trips of service day ``day`` with their
        own times (24:00 and later included), plus the connections of the
        previous service day's trips that depart at 24:00 or later, moved back
        by 24 hours.  Cancelled trips are left out and delays are applied.  A
        listing is built once and kept until the timetable changes."""
        day = parse_date(day)
        listing = self._listings.get(day)
        if listing is None:
            found = []
            for service_day, shift in ((day - ONE_DAY, MINUTES_PER_DAY), (day, 0)):
                for trip_id in self.trips_on(service_day):
                    if (trip_id, service_day) not in self._cancelled:
                        found += self._hops(trip_id, service_day, shift)
            listing = tuple(sorted(found, key=lambda hop: (hop.departure, hop.arrival, hop.trip_id, hop.index)))
            self._listings[day] = listing
        return listing

    def _invalidate(self, service_day):
        """Forget the kept listings that show trips of ``service_day``."""
        for listed in (service_day, service_day + ONE_DAY):
            self._listings.pop(listed, None)
