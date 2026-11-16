"""Departure and arrival boards and line summaries.

Boards are read from one calendar day's listing.  A departure board shows
every trip leaving the station (not trips that end there), an arrival board
every trip arriving (not trips that start there).  Rows are sorted by
expected time, then line, then trip id.  ``start`` and ``end`` bound the
expected time, both included.  A delayed row shows ``+N`` after the time.
"""
from dataclasses import dataclass

from .clock import format_time, parse_time, wall_time
from .network import whole


@dataclass(frozen=True)
class Row:
    time: int           # expected, minutes of the listing's day
    scheduled: int
    delay: int
    line: str
    trip_id: str
    other: str          # departures: the trip's terminus; arrivals: the trip's origin


def _rows(timetable, station, day, start, end, limit, leaving):
    timetable.network.station(station)
    low, high = parse_time(start), parse_time(end)
    if limit is not None:
        whole(limit, 1, 1000, "limit")
    rows = []
    for hop in timetable.connections(day):
        trip = timetable.trip(hop.trip_id)
        if leaving and hop.start == station:
            row = Row(hop.departure, hop.departure - hop.departure_delay, hop.departure_delay, hop.line,
                      hop.trip_id, trip.terminus)
        elif not leaving and hop.end == station:
            row = Row(hop.arrival, hop.arrival - hop.arrival_delay, hop.arrival_delay, hop.line, hop.trip_id, trip.origin)
        else:
            continue
        if low <= row.time <= high:
            rows.append(row)
    rows.sort(key=lambda row: (row.time, row.line, row.trip_id))
    return rows if limit is None else rows[:limit]


def departures(timetable, station, day, start="00:00", end="47:59", limit=None):
    """Departure :class:`Row` list for ``station`` on calendar ``day``."""
    return _rows(timetable, station, day, start, end, limit, True)


def arrivals(timetable, station, day, start="00:00", end="47:59", limit=None):
    """Arrival :class:`Row` list for ``station`` on calendar ``day``."""
    return _rows(timetable, station, day, start, end, limit, False)


def format_board(network, rows, title):
    """Board text: the title, then ``"08:02 +5  IC31  Rzeszow Glowny"`` per row (station names)."""
    lines = [title]
    for row in rows:
        time = wall_time(row.time) + (f" +{row.delay}" if row.delay else "")
        lines.append(f"{time:<11} {row.line:<6} {network.station(row.other).name}")
    if not rows:
        lines.append("(no trains)")
    return "\n".join(lines)


def line_summary(timetable, line, day):
    """One row per trip of ``line`` running on service ``day``:
    ``[trip id, origin, departure, terminus, arrival, status]`` with timetable times and the
    status ``"cancelled"``, ``"+N"`` (delay at the terminus) or ``"on time"``; ordered by
    scheduled departure, then trip id."""
    rows = []
    for trip in timetable.trips(line):
        if trip.trip_id not in timetable.trips_on(day):
            continue
        times = timetable.stop_times(trip.trip_id, day)
        if timetable.is_cancelled(trip.trip_id, day):
            status = "cancelled"
        else:
            status = f"+{times[-1][3]}" if times[-1][3] else "on time"
        rows.append((trip.stops[0].departure, trip.trip_id, [trip.trip_id, trip.origin, format_time(times[0][2]),
                                                            trip.terminus, format_time(times[-1][1]), status]))
    return [row for _, _, row in sorted(rows)]
