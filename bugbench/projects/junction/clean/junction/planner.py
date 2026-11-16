"""Journey planning on one day's connection listing.

``Planner.plan`` returns the journey from ``origin`` to ``destination`` that
departs at or after the requested time and

1. arrives earliest; among those
2. uses the fewest rides (fewest transfers); among those
3. departs latest.

A journey starts with a ride from the origin and ends with a ride into the
destination.  Between two rides the passenger either stays at the station,
which needs the station's minimum transfer time, or walks one footpath, which
needs the walking time instead.  A journey has at most ``max_rides`` rides
(default 4).  Only the listing of the requested calendar day is used, so a
journey continues past midnight only on trips of that service day.
"""
from .clock import LATEST, parse_date, parse_time
from .errors import JunctionError, NoConnection
from .journey import Journey, Ride, Walk
from .network import whole

MAX_RIDES = 4


def can_change(network, station, arrival, departure):
    """True when a passenger who arrives at ``station`` at ``arrival`` can catch another trip
    that leaves ``station`` at ``departure`` (the station's minimum transfer time)."""
    return departure - arrival >= network.transfer_minutes(station)


class Planner:
    """Plans journeys over a :class:`~junction.timetable.Timetable`."""

    def __init__(self, timetable):
        self.timetable = timetable
        self.network = timetable.network

    def plan(self, origin, destination, day, after="00:00", max_rides=MAX_RIDES):
        """The best journey (see the module rules); :class:`NoConnection` if there is none."""
        self.network.station(origin)
        self.network.station(destination)
        if origin == destination:
            raise JunctionError("origin and destination must differ")
        day, start = parse_date(day), parse_time(after)
        whole(max_rides, 1, 8, "max_rides")
        listing = self.timetable.connections(day)
        best = self._search(listing, origin, destination, start, max_rides)
        if best is None:
            raise NoConnection(f"no journey from {origin} to {destination} on {day} after {after}")
        later = sorted({hop.departure for hop in listing if hop.start == origin and hop.departure > best.departure},
                       reverse=True)
        for moment in later:
            found = self._search(listing, origin, destination, moment, max_rides)
            if found is not None and (found.arrival, found.transfers) == (best.arrival, best.transfers):
                return found
        return best

    def journeys(self, origin, destination, day, after="00:00", count=3, max_rides=MAX_RIDES):
        """Up to ``count`` journeys; each next one is planned from one minute after the previous departure."""
        whole(count, 1, 20, "count")
        found, moment = [], parse_time(after)
        while len(found) < count and moment <= LATEST:
            try:
                journey = self.plan(origin, destination, day, moment, max_rides)
            except NoConnection:
                break
            found.append(journey)
            moment = journey.departure + 1
        return found

    def _boarding(self, stay, walk, hop):
        """Legs so far for a passenger who can board ``hop``, or ``None``."""
        here = hop.start
        if here in walk and hop.departure >= walk[here][0]:
            return walk[here][1]
        if here in stay and can_change(self.network, here, stay[here][0], hop.departure):
            return stay[here][1]
        return None

    def _search(self, listing, origin, destination, start, max_rides):
        """Earliest arrival with the fewest rides, by rounds (round ``n`` adds the ``n``-th ride)."""
        stay = {}                       # station -> (arrival by ride, legs)
        walk = {origin: (start, ())}    # station -> (ready after walking or at the start, legs)
        best = None
        for _ in range(max_rides):
            board_stay, board_walk = dict(stay), dict(walk)
            on_board, improved = {}, set()
            for hop in listing:
                if hop.departure < start:
                    continue
                key = (hop.trip_id, hop.service_day)
                if key not in on_board:
                    legs = self._boarding(board_stay, board_walk, hop)
                    if legs is None:
                        continue
                    on_board[key] = (legs, hop)
                legs, first = on_board[key]
                current = stay.get(hop.end)
                if current is None or hop.arrival < current[0]:
                    stops = self.timetable.trip(hop.trip_id).stops[first.index:hop.index + 2]
                    ride = Ride(hop.trip_id, hop.line, tuple(stop.station for stop in stops), first.departure, hop.arrival)
                    stay[hop.end] = (hop.arrival, legs + (ride,))
                    improved.add(hop.end)
            if not improved:
                break
            for station in sorted(improved):
                arrival, legs = stay[station]
                for path in self.network.footpaths(station):
                    there = arrival + path.minutes
                    if path.end not in walk or there < walk[path.end][0]:
                        step = Walk(path.start, path.end, arrival, there, path.metres)
                        walk[path.end] = (there, legs + (step,))
            if destination in improved and (best is None or stay[destination][0] < best.arrival):
                best = Journey(stay[destination][1])
        return best
