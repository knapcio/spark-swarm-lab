"""Hidden behavioural probes for the junction project. NEVER shown to agents.

BUGBENCH-HIDDEN-CANARY 6757f080-bugbench-junction-probes

Each ``probe_*`` function builds fresh state, exercises public behaviour and
returns a JSON-compatible observation.  This file contains no expected values:
the trusted parent compares observations with ``expected.json``, which was
frozen from the clean reference project.  Probes only use behaviour documented
in ``README.md`` and docstrings.
"""
import datetime

D = datetime.date


def _error(callable_, *args, **kwargs):
    try:
        callable_(*args, **kwargs)
    except Exception as exc:  # observation only; the parent decides
        return type(exc).__name__
    return None


def _plan(junction, *args, **kwargs):
    from junction import JunctionError
    try:
        return junction.plan(*args, **kwargs).describe().splitlines()
    except JunctionError as exc:
        return type(exc).__name__


def _rows(rows):
    return [[row.time, row.scheduled, row.delay, row.line, row.trip_id, row.other] for row in rows]


def _hops(listing):
    return [[c.trip_id, str(c.service_day), c.index, c.start, c.end, c.departure, c.arrival, c.departure_delay,
             c.arrival_delay] for c in listing]


BASE = """
station KRK "Krakow Glowny" zone 1 transfer 5
station KRB "Krakow Bus Station" zone 1 transfer 2
station BCH "Bochnia" zone 2 transfer 0
station TRN "Tarnow" zone 3 transfer 4
station RZE "Rzeszow Glowny" zone 4
station WIE "Wieliczka" zone 2
station DEB "Debica" zone 4 transfer 6
station NSC "Nowy Sacz" zone 5 transfer 3
footpath KRK KRB 240
footpath TRN DEB 1600
service WK mon-fri 2026-03-02..2026-03-31 except 2026-03-13 add 2026-03-14
service NT daily 2026-03-01..2026-03-31
service SA sat,sun 2026-03-01..2026-04-30
trip T1 IC31 WK
  KRK 08:02
  BCH 08:20 08:21
  TRN 08:41 08:43
  RZE 09:30
trip T2 R2 WK
  KRK 08:10
  BCH 08:31 08:33
  TRN 09:05
trip T3 R5 WK
  WIE 07:40
  KRK 07:52
trip B1 B7 WK
  WIE 07:30
  KRB 07:51
trip S1 R9 WK
  TRN 08:50
  NSC 10:05
trip S2 R9 WK
  TRN 09:20
  DEB 09:41
  RZE 10:10
trip N1 N9 NT
  KRK 22:50
  BCH 23:10 23:11
  TRN 23:40
trip W1 IC31 SA
  KRK 10:00
  TRN 11:00
"""


def _base():
    from junction import Junction
    return Junction.from_text(BASE)


# --- clock ------------------------------------------------------------------------------
def probe_clock_times():
    from junction import format_time, parse_time, wall_time
    out = [[parse_time(t) for t in ("0:00", "00:01", "9:05", " 23:59 ", "24:00", "47:59", 0, 2879)],
           [_error(parse_time, t) for t in ("48:00", "8:60", "8.40", "", "123:00", "8:5", -1, 2880, True, None, 7.5)],
           [format_time(m) for m in (0, 59, 60, 520, 1439, 1440, 1480, 2879)],
           [wall_time(m) for m in (0, 520, 1439, 1440, 1480, 2879)], _error(format_time, 2880), _error(wall_time, -5)]
    return out


def probe_clock_durations_dates_weekdays():
    from junction.clock import format_duration, parse_date, parse_duration, parse_weekdays, weekday_text
    out = [[parse_duration(t) for t in ("0", "45", "45m", "2h", "1h05m", "1h05", " 24h ", "1440", "1h59m", 30, 0, 1440)],
           [_error(parse_duration, t) for t in ("", "h", "1h60m", "25h", "1441", "-5", "5s", True, 2.5, 1441, -1)],
           [format_duration(m) for m in (0, 5, 59, 60, 65, 600, 1440)],
           [str(parse_date(t)) for t in ("2026-03-02", " 2028-02-29 ", D(2026, 1, 1))],
           [_error(parse_date, t) for t in ("2026-02-30", "2026-3-02", "02-03-2026", 20260302, datetime.datetime(2026, 3, 2))],
           [list(parse_weekdays(t)) for t in ("daily", "mon-fri", "sat,sun", "fri-mon", "SUN-TUE", "wed", "mon,mon-tue", "mon-sun", "tue-mon")],
           [_error(parse_weekdays, t) for t in ("", "mon-", "monday", "mon,,tue", 5, "mon-xyz")],
           [weekday_text(d) for d in ((0, 1, 2, 3, 4), (5, 6), (0, 2, 4), (0, 1, 2, 3, 4, 5, 6), (0, 1, 3, 4, 5), (6,), (0, 1), (4, 5, 6, 0))]]
    return out


def probe_service_calendar():
    from junction import Network, Timetable
    timetable = Timetable(Network())
    service = timetable.add_service("WK", "mon-fri", "2026-03-02", "2026-03-31", ["2026-03-27", "2026-03-24", "2026-03-19", "2026-03-13", "2026-03-04", "2026-03-04", "2026-03-03"],
                                    ["2026-04-11", "2026-04-04", "2026-03-28", "2026-03-21", "2026-03-14"])
    single = timetable.add_service("ONE", "tue", "2026-03-03", "2026-03-03")
    days = [D(2026, 3, 1) + datetime.timedelta(days=n) for n in range(33)]
    out = [[day.day for day in days if service.runs_on(day)], [day.day for day in days if single.runs_on(day)],
           service.describe(), single.describe(), list(service.weekdays),
           _error(timetable.add_service, "WK", "daily", "2026-01-01", "2026-01-02"),
           _error(timetable.add_service, "X", "daily", "2026-02-02", "2026-02-01"),
           _error(timetable.add_service, "bad id", "daily", "2026-02-01", "2026-02-02"),
           _error(timetable.add_service, "Y", "noday", "2026-02-01", "2026-02-02"), _error(timetable.service, "NOPE")]
    return out


# --- network ----------------------------------------------------------------------------
def probe_network_stations():
    from junction import Network
    network = Network()
    first = network.add_station("KRK", "  Krakow   Glowny ", zone=1, transfer=5)
    network.add_station("A1", "Airport", zone=2, transfer=0)
    network.add_station("KRB", "Krakow Bus", zone=1, transfer=30)
    network.add_station("ZAK", "Zakopane", zone=99)
    network.add_station("HEL", "Hel", zone=16)
    network.add_station("ORL", "Orlik", zone=3)
    out = [[first.code, first.name, first.zone, first.transfer], [s.code for s in network.stations()],
           [s.code for s in network.stations(zone=1)], [s.code for s in network.find("KRAKOW")], [s.code for s in network.find("o")],
           "KRK" in network, "XXX" in network, 5 in network, network.transfer_minutes("ZAK"), network.zones(["ZAK", "KRK", "KRB", "A1"]), network.zones(["HEL", "ORL", "KRK"])]
    out.append([_error(network.add_station, *args) for args in (("KRK", "Again"), ("k1", "x"), ("K", "x"), ("KRAKOWX", "x"),
                                                                  ("1AB", "x"), ("ABC", "  "), ("ABC", "x", 0), ("ABC", "x", 100),
                                                                  ("ABC", "x", 1, 31), ("ABC", "x", 1, -1), ("ABC", "x", True))])
    out += [_error(network.station, "NOPE"), _error(network.station, None), _error(network.find, " "), _error(network.find, 3),
            _error(network.transfer_minutes, "NOPE"), _error(network.zones, ["KRK", "NOPE"])]
    return out


def probe_network_footpaths():
    from junction import Network, walking_minutes
    network = Network()
    for code in ("AAA", "BBB", "CCC", "DDD"):
        network.add_station(code, code.title())
    paths = [network.add_footpath("AAA", "CCC", 160), network.add_footpath("AAA", "BBB", 480), network.add_footpath("DDD", "AAA", 400)]
    out = [[[p.start, p.end, p.metres, p.minutes] for p in paths], [[p.end, p.minutes] for p in network.footpaths("AAA")],
           [[p.end, p.minutes] for p in network.footpaths("BBB")], [network.footpath("CCC", "AAA").minutes],
           [walking_minutes(m) for m in (80, 160, 240, 800, 2400)]]
    out.append([_error(network.add_footpath, *args) for args in (("AAA", "BBB", 80), ("BBB", "AAA", 80), ("AAA", "AAA", 80),
                                                                   ("AAA", "XXX", 80), ("BBB", "CCC", 0), ("BBB", "CCC", 3001),
                                                                   ("BBB", "CCC", 8.0), ("BBB", "CCC", True))])
    out += [_error(network.footpath, "BBB", "CCC"), _error(network.footpaths, "XXX"), network.footpaths("CCC")[0].end]
    return out


def probe_walking_minutes_round_up():
    from junction import Network, walking_minutes
    network = Network()
    for code in ("PL1", "PL2", "PL3"):
        network.add_station(code, code)
    first = network.add_footpath("PL1", "PL2", 520)
    second = network.add_footpath("PL3", "PL1", 90)
    return [[walking_minutes(m) for m in (1, 40, 79, 81, 120, 200, 250, 360, 440, 2999, 3000)],
            [first.minutes, network.footpath("PL2", "PL1").minutes, second.minutes],
            [[p.end, p.minutes] for p in network.footpaths("PL1")]]


# --- timetable --------------------------------------------------------------------------
def probe_trip_validation():
    from junction import Network, Timetable
    network = Network()
    for code in ("AAA", "BBB", "CCC"):
        network.add_station(code, code.title())
    timetable = Timetable(network)
    timetable.add_service("S", "daily", "2026-01-01", "2026-12-31")
    trip = timetable.add_trip("X-1", "L1", "S", [("AAA", None, "08:00"), ("BBB", "08:05", "08:05"), ("CCC", 490, None)])
    out = [[[s.station, s.arrival, s.departure] for s in trip.stops], trip.origin, trip.terminus, trip.stop_index("BBB"),
           _error(trip.stop_index, "XXX")]
    bad = [("Y", "L", "S", [("AAA", None, "08:00"), ("BBB", "08:00", None)]),
           ("Y", "L", "S", [("AAA", None, "08:00"), ("BBB", "08:01", "08:00"), ("CCC", "08:05", None)]),
           ("Y", "L", "S", [("AAA", None, "08:00"), ("BBB", "08:01", None), ("AAA", "08:05", None)]),
           ("Y", "L", "S", [("AAA", None, "08:00")]), ("Y", "L", "S", [("AAA", None, "08:00"), ("XXX", "08:05", None)]),
           ("Y", "L", "NOPE", [("AAA", None, "08:00"), ("BBB", "08:05", None)]),
           ("X-1", "L", "S", [("AAA", None, "08:00"), ("BBB", "08:05", None)]),
           ("Y", "L 2", "S", [("AAA", None, "08:00"), ("BBB", "08:05", None)]),
           ("Y", "L", "S", [("AAA", None, "08:00"), ("BBB", "08:05")]), ("Y", "L", "S", [("AAA", None, None), ("BBB", "08:05", None)]),
           ("Y", "L", "S", [("AAA", "07:59", "08:00"), ("BBB", "48:00", None)])]
    out.append([_error(timetable.add_trip, *args) for args in bad])
    late = timetable.add_trip("Y", "L", "S", [("AAA", "07:50", "08:00"), ("BBB", "08:01", "08:02"), ("CCC", "08:03", "08:09")])
    out += [[[s.arrival, s.departure] for s in late.stops], [t.trip_id for t in timetable.trips()], timetable.lines(),
            [t.trip_id for t in timetable.trips("L1")], _error(timetable.trip, "NOPE"), _error(timetable.trip, 5)]
    return out


def probe_trips_on_and_stop_times():
    junction = _base()
    timetable = junction.timetable
    out = [timetable.lines()] + [timetable.trips_on(day) for day in ("2026-03-02", "2026-03-07", "2026-03-13", "2026-03-14", "2026-04-04", "2026-03-31", "2026-04-01")]
    timetable.delay("T1", "2026-03-02", 6, "BCH")
    timetable.delay("T2", "2026-03-02", 3)
    out += [timetable.stop_times("T1", "2026-03-02"), timetable.stop_times("T2", "2026-03-02"), timetable.stop_times("T1", "2026-03-03"),
            _error(timetable.stop_times, "T1", "2026-03-07"), _error(timetable.stop_times, "NOPE", "2026-03-02")]
    return out


def probe_delays_and_cancellations():
    junction = _base()
    timetable = junction.timetable
    timetable.delay("T1", "2026-03-02", 9, "TRN")
    timetable.delay("T1", "2026-03-02", 4, "BCH")
    timetable.delay("T2", D(2026, 3, 3), 15)
    timetable.cancel("S1", "2026-03-02")
    timetable.cancel("N1", "2026-03-05")
    out = [timetable.disruptions(), timetable.stop_times("T1", "2026-03-02"), timetable.is_cancelled("S1", "2026-03-02"),
           timetable.is_cancelled("S1", "2026-03-03")]
    out.append([_error(timetable.delay, *args) for args in (("T1", "2026-03-07", 5), ("T1", "2026-03-02", -1),
                                                             ("T1", "2026-03-02", 721), ("T1", "2026-03-02", 5, "NSC"),
                                                             ("T1", "2026-03-02", True), ("NOPE", "2026-03-02", 5),
                                                             ("N1", "2026-03-02", 720))])
    out += [_error(timetable.cancel, "S1", "2026-03-02"), _error(timetable.reinstate, "S1", "2026-03-03"),
            _error(timetable.cancel, "S1", "2026-03-07")]
    timetable.delay("T1", "2026-03-02", 0)
    timetable.delay("N1", "2026-03-04", 719, "TRN")
    timetable.reinstate("S1", "2026-03-02")
    out += [timetable.disruptions(), timetable.is_cancelled("S1", "2026-03-02"), timetable.stop_times("N1", "2026-03-04")[-1]]
    timetable.add_trip("L1", "N9", "NT", [("KRK", "35:00", "35:10"), ("TRN", "36:00", None)])
    out += [_error(timetable.delay, "L1", "2026-03-04", 719), _error(timetable.delay, "L1", "2026-03-04", 720),
            timetable.stop_times("L1", "2026-03-04")]
    return out


def probe_listing_contents():
    junction = _base()
    timetable = junction.timetable
    timetable.add_trip("N2", "N7", "NT", [("KRK", None, "23:40"), ("BCH", "24:05", "24:06"), ("TRN", "24:35", None)])
    timetable.add_trip("N3", "N7", "NT", [("KRK", None, "23:30"), ("BCH", "23:59", "24:00"), ("TRN", "24:20", None)])
    timetable.add_trip("N4", "N7", "WK", [("TRN", None, "23:58"), ("BCH", "24:20", "24:21"), ("KRK", "24:45", None)])
    first = timetable.connections("2026-03-02")
    out = [_hops(first), _hops(timetable.connections("2026-03-03")), _hops(timetable.connections(D(2026, 3, 1))),
           timetable.connections("2026-03-02") is first, len(timetable.connections("2026-03-07")),
           _hops(timetable.connections("2026-03-14"))[:2], _hops(timetable.connections("2026-03-16"))[:3]]
    return out


def probe_listing_follows_same_day_changes():
    junction = _base()
    timetable = junction.timetable
    before = [c.departure for c in timetable.connections("2026-03-02") if c.trip_id == "T2"]
    timetable.delay("T2", "2026-03-02", 8, "BCH")
    after = _hops([c for c in timetable.connections("2026-03-02") if c.trip_id == "T2"])
    timetable.cancel("T1", "2026-03-02")
    gone = [c.trip_id for c in timetable.connections("2026-03-02")]
    timetable.reinstate("T1", "2026-03-02")
    back = sorted({c.trip_id for c in timetable.connections("2026-03-02")})
    other = [c.trip_id for c in timetable.connections("2026-03-03")]
    timetable.cancel("N1", "2026-03-03")
    other_after = [c.trip_id for c in timetable.connections("2026-03-03")]
    timetable.add_trip("Z9", "R1", "WK", [("RZE", None, "06:00"), ("DEB", "06:20", None)])
    added = [c.trip_id for c in timetable.connections("2026-03-02")][:1]
    timetable.add_service("XT", "daily", "2026-03-02", "2026-03-02")
    timetable.add_trip("Z8", "R1", "XT", [("RZE", None, "05:00"), ("DEB", "05:20", None)])
    service_added = [c.trip_id for c in timetable.connections("2026-03-02")][:2]
    return [before, after, gone, back, other, other_after, added, service_added]


# --- planner ----------------------------------------------------------------------------
def probe_plan_direct_and_errors():
    from junction import Planner
    junction = _base()
    out = [_plan(junction, "KRK", "RZE", "2026-03-02", "07:30"), _plan(junction, "KRK", "RZE", "2026-03-02", "08:02"),
           _plan(junction, "KRK", "RZE", "2026-03-02", "08:03"), _plan(junction, "KRK", "TRN", "2026-03-07", "06:00"),
           _plan(junction, "TRN", "KRK", "2026-03-02", "06:00"), _plan(junction, "KRK", "TRN", "2026-03-02", "08:05")]
    out.append([_error(junction.plan, *args) for args in (("KRK", "KRK", "2026-03-02"), ("KRK", "NOPE", "2026-03-02"),
                                                           ("KRK", "RZE", "2026-03-02", "25:61"), ("KRK", "RZE", "02.03.2026"),
                                                           ("KRK", "RZE", "2026-03-02", "07:00", 0), ("KRK", "RZE", "2026-03-02", "07:00", 9))])
    planner = Planner(junction.timetable)
    out.append(planner.plan("KRK", "BCH", D(2026, 3, 2), 480, 1).summary())
    return out


def probe_plan_transfers_and_walks():
    junction = _base()
    out = [_plan(junction, "WIE", "TRN", "2026-03-02", "07:00"), _plan(junction, "WIE", "RZE", "2026-03-02", "07:00"),
           _plan(junction, "KRK", "NSC", "2026-03-02", "07:00"), _plan(junction, "BCH", "DEB", "2026-03-02", "08:00"),
           _plan(junction, "WIE", "NSC", "2026-03-02", "07:00"), _plan(junction, "WIE", "NSC", "2026-03-02", "07:00", 2),
           _plan(junction, "KRB", "RZE", "2026-03-02", "07:00")]
    journey = junction.plan("WIE", "DEB", "2026-03-02", "07:35")
    out.append([journey.origin, journey.destination, journey.departure, journey.arrival, journey.duration, journey.transfers,
                journey.walking, journey.waits(), journey.stations(), len(journey.rides)])
    return out


def probe_plan_tie_breaks():
    from junction import Junction
    text = BASE + """
trip E1 R1 WK
  WIE 07:00
  KRK 07:20
trip E2 R1 WK
  WIE 07:10
  KRK 07:30
trip F1 R3 WK
  KRK 07:36
  BCH 07:50
trip F2 IC5 WK
  KRK 07:40
  TRN 08:41
trip F3 R4 WK
  BCH 07:55
  TRN 08:41
"""
    junction = Junction.from_text(text)
    out = [_plan(junction, "WIE", "TRN", "2026-03-02", "06:30"), _plan(junction, "KRK", "TRN", "2026-03-02", "07:00"),
           _plan(junction, "WIE", "BCH", "2026-03-02", "06:30"), _plan(junction, "WIE", "BCH", "2026-03-02", "07:05")]
    out.append([j.summary() for j in junction.journeys("WIE", "TRN", "2026-03-02", "06:30", count=4)])
    out.append([j.summary() for j in junction.journeys("KRK", "BCH", "2026-03-02", "07:00", count=20)])
    out.append([j.summary() for j in junction.journeys("KRK", "BCH", "2026-03-02", "07:00", count=2)])
    out.append(_error(junction.journeys, "KRK", "BCH", "2026-03-02", "07:00", 0))
    return out


def probe_plan_after_midnight():
    junction = _base()
    junction.timetable.add_trip("N2", "N7", "NT", [("KRK", None, "23:40"), ("BCH", "24:05", "24:06"), ("TRN", "24:35", None)])
    junction.timetable.add_trip("N5", "N8", "NT", [("TRN", None, "24:45"), ("DEB", "25:10", None)])
    out = [_plan(junction, "KRK", "TRN", "2026-03-02", "23:00"), _plan(junction, "BCH", "TRN", "2026-03-03", "00:00"),
           _plan(junction, "KRK", "DEB", "2026-03-02", "23:00"), _plan(junction, "BCH", "DEB", "2026-03-03", "00:00"),
           _plan(junction, "KRK", "TRN", "2026-03-02", "24:00"), _plan(junction, "BCH", "TRN", "2026-03-03", "00:07")]
    return out


# --- journeys and fares -----------------------------------------------------------------
def probe_journey_objects():
    from junction import Journey, JunctionError, Ride, Walk
    first = Ride("T1", "IC31", ("KRK", "BCH", "TRN"), 482, 521)
    walk = Walk("TRN", "DEB", 521, 541, 1600)
    second = Ride("S2", "R9", ("DEB", "RZE"), 1441, 1470)
    journey = Journey([first, walk, second])
    single = Journey([Ride("X", "L", ("AAA", "BBB"), 0, 1439)])
    out = [journey.summary(), journey.describe().splitlines(), journey.stations(), journey.waits(), journey.walking,
           journey.transfers, journey.duration, single.summary(), single.waits(), single.walking,
           journey == Journey([first, walk, second]), journey == single, journey == "x",
           len({journey, Journey([first, walk, second])}), repr(single), first.minutes, walk.minutes, first.start, first.end]
    double = Journey([first, Ride("S9", "R9", ("TRN", "DEB"), 530, 545), Ride("S8", "R8", ("DEB", "RZE"), 545, 600)])
    out += [double.summary(), double.waits(), double.stations()]
    out.append([_error(Journey, legs) for legs in ([], [walk], [first, walk], [walk, second], [second, first],
                                                   [first, Ride("Q", "L", ("KRK", "RZE"), 530, 600)])])
    return out


def probe_fare_rules():
    from junction.fares import CONCESSIONS, day_total, format_money, is_night, reduce, zone_price
    out = [[zone_price(n) for n in (1, 2, 3, 4, 5, 10, 99)], [_error(zone_price, n) for n in (0, 100, True, 1.0)],
           [is_night(m) for m in (0, 239, 240, 1379, 1380, 1439, 1440, 1679, 1680, 2819, 2820)],
           [[reduce(c, k) for k in ("full", "senior", "student")] for c in (400, 560, 720, 870, 1600, 1150, 650, 950, 15, 0)],
           _error(reduce, 400, "child"), sorted(CONCESSIONS),
           [format_money(c) for c in (0, 5, 99, 100, 560, 123456)], [_error(format_money, c) for c in (-1, 1.5, True)]]
    junction = _base()
    journey = junction.plan("KRK", "TRN", "2026-03-02", "07:00")
    out.append([day_total(junction.network, [journey] * n, k) for n in (0, 1, 2, 3) for k in ("full", "student")])
    return out


def probe_journey_fares():
    junction = _base()
    junction.timetable.add_trip("N2", "N7", "NT", [("KRK", None, "23:40"), ("BCH", "24:05", "24:06"), ("TRN", "24:35", None)])
    plans = [junction.plan("KRK", "BCH", "2026-03-02", "07:00"), junction.plan("WIE", "DEB", "2026-03-02", "07:35"),
             junction.plan("KRK", "NSC", "2026-03-02", "07:00"), junction.plan("KRK", "TRN", "2026-03-02", "22:00"),
             junction.plan("KRK", "TRN", "2026-03-02", "23:00"), junction.plan("BCH", "TRN", "2026-03-03", "00:00"),
             junction.plan("WIE", "RZE", "2026-03-02", "07:00")]
    out = [[p.summary(), junction.fare(p), junction.fare(p, "senior"), junction.fare(p, "student")] for p in plans]
    out.append(_error(junction.fare, plans[0], "child"))
    return out


# --- boards and summaries ---------------------------------------------------------------
def probe_boards():
    from junction import format_board
    junction = _base()
    junction.timetable.add_trip("T9", "IC31", "WK", [("WIE", None, "07:50"), ("KRK", "08:01", "08:02"), ("NSC", "10:00", None)])
    junction.timetable.add_trip("T8", "AR1", "WK", [("KRB", None, "07:45"), ("KRK", "07:55", "08:02"), ("TRN", "09:00", None)])
    junction.timetable.delay("T2", "2026-03-02", 3, "BCH")
    day = "2026-03-02"
    out = [_rows(junction.departures("KRK", day)), _rows(junction.arrivals("KRK", day)), _rows(junction.departures("BCH", day)),
           _rows(junction.arrivals("BCH", day)), _rows(junction.departures("KRK", day, "08:02", "08:10")),
           _rows(junction.departures("KRK", day, limit=2)), _rows(junction.departures("RZE", day)), _rows(junction.arrivals("WIE", day)),
           junction.board("BCH", day).splitlines(), junction.board("RZE", day), format_board(junction.network, [], "Empty")]
    out.append([_error(junction.departures, *args) for args in (("NOPE", day), ("KRK", day, "9"), ("KRK", day, "00:00", "49:00"),
                                                                ("KRK", day, "00:00", "47:59", 0), ("KRK", "2026/03/02"))])
    return out


def probe_line_summaries():
    from junction import line_summary
    junction = _base()
    junction.timetable.add_trip("T7", "IC31", "WK", [("KRK", None, "06:02"), ("TRN", "06:41", None)])
    junction.timetable.add_trip("T0", "IC31", "WK", [("KRK", None, "06:02"), ("TRN", "06:45", None)])
    junction.apply("delay T1 2026-03-02 +4 from TRN\ncancel T7 2026-03-02\n")
    return [line_summary(junction.timetable, "IC31", day) for day in ("2026-03-02", "2026-03-03", "2026-03-07", "2026-03-13")] + \
           [line_summary(junction.timetable, "N9", "2026-03-02"), line_summary(junction.timetable, "NONE", "2026-03-02")]


# --- text formats -----------------------------------------------------------------------
def probe_text_format():
    from junction import load
    timetable = load(BASE + "# trailing comment\nstation XY1 \"Spaced  Name\"   transfer 7 zone 3 # note\n")
    out = [[[s.code, s.name, s.zone, s.transfer] for s in timetable.network.stations()],
           [[p.end, p.minutes] for p in timetable.network.footpaths("TRN")],
           [timetable.service(s).describe() for s in ("WK", "NT", "SA")],
           [[t.trip_id, t.line, t.service_id, [[s.station, s.arrival, s.departure] for s in t.stops]] for t in timetable.trips()]]
    return out


def probe_text_errors():
    from junction import ParseError, load
    texts = ['station KRK "K"\nstation KRK "Again"\n', 'station KRK K\n', 'station KRK "K" zone 1 zone 2\n',
             'station KRK "K"\n  KRK 08:00\n', 'station KRK "K"\nfootpath KRK\n', 'station KRK "K"\nfootpath KRK ABC 1x\n',
             'service S daily 2026-01-01\n', 'service S daily 2026-01-01..2026-01-05 except\n',
             'station A1 "A"\nstation B1 "B"\nservice S daily 2026-01-01..2026-01-05\ntrip T L S\n  A1 08:00\n  B1 07:00\n',
             'station A1 "A"\nservice S daily 2026-01-01..2026-01-05\ntrip T L S\n  A1 08:00 08:01 08:02\n',
             'station A1 "A"\nstation B1 "B"\nservice S daily 2026-01-01..2026-01-05\ntrip T L S\n  A1 08:00\n  B1 08:30\nbogus\n',
             'station A1 "A"\nservice S daily 2026-01-01..2026-01-05\ntrip T L S\n  A1 08:00\n\n# c\n',
             'station A1 "A" zone 0\n', "trip T L\n", 12]
    out = []
    for text in texts:
        try:
            load(text)
            out.append(None)
        except ParseError as exc:
            out.append(["ParseError", exc.line])
        except Exception as exc:  # observation only
            out.append(type(exc).__name__)
    return out


def probe_disruption_feed():
    from junction import ParseError, apply_disruptions
    junction = _base()
    feed = "# morning\ndelay T1 2026-03-02 +5 from BCH\n\ncancel S1 2026-03-02\ndelay T2 2026-03-02 +12\n"
    out = [junction.apply(feed), junction.timetable.disruptions()]
    for bad in ("delay T1 2026-03-02 5\n", "delay T1 2026-03-02 +5 from\n", "cancel S1 2026-03-02\n", "reinstate T2 2026-03-02\n",
                "delay T1 2026-03-02 +5\nhold T1\n", "cancel T1\n", "cancel W1 2026-03-02\n", "delay T1 2026-03-02 +5 from NSC\n"):
        try:
            out.append(["applied", apply_disruptions(junction.timetable, bad)])
        except ParseError as exc:
            out.append(["ParseError", exc.line])
    out += [junction.timetable.disruptions(), _error(junction.apply, 7)]
    return out


# --- minimum transfer time is inclusive -------------------------------------------------
def _describe(planner, origin, destination, day, after):
    from junction import JunctionError
    try:
        return planner.plan(origin, destination, day, after).describe().splitlines()
    except JunctionError as exc:
        return type(exc).__name__


def probe_change_exact_transfer_time():
    from junction import Network, Planner, Timetable, can_change
    network = Network()
    network.add_station("ALF", "Alfa", transfer=0)
    network.add_station("BET", "Beta", transfer=4)
    network.add_station("GAM", "Gamma", zone=2)
    network.add_station("DEL", "Delta", zone=3)
    network.add_station("EPS", "Epsilon", transfer=7)
    timetable = Timetable(network)
    timetable.add_service("D", "daily", "2026-01-01", "2026-12-31")
    for trip_id, line, stops in (("X1", "A", [("ALF", None, "09:00"), ("BET", "09:20", None)]),
                                 ("X2", "B", [("BET", None, "09:24"), ("GAM", "10:00", None)]),
                                 ("X3", "B", [("BET", None, "09:30"), ("GAM", "10:10", None)]),
                                 ("Y1", "C", [("EPS", None, "09:00"), ("ALF", "09:10", None)]),
                                 ("Y2", "C", [("ALF", None, "09:10"), ("DEL", "09:50", None)]),
                                 ("Z1", "E", [("GAM", None, "11:00"), ("EPS", "11:30", None)]),
                                 ("Z2", "E", [("EPS", None, "11:37"), ("BET", "12:00", None)]),
                                 ("Z3", "E", [("EPS", None, "11:45"), ("BET", "12:10", None)])):
        timetable.add_trip(trip_id, line, "D", stops)
    planner = Planner(timetable)
    out = [[can_change(network, code, 600, 600 + gap) for code, gap in (("ALF", 0), ("BET", 4), ("BET", 3), ("EPS", 7), ("EPS", 6))]]
    out += [_describe(planner, *args) for args in (("ALF", "GAM", "2026-05-05", "08:30"), ("EPS", "DEL", "2026-05-05", "08:30"),
                                                    ("GAM", "BET", "2026-05-05", "10:30"))]
    return out


def probe_change_exact_text_plan():
    from junction import Junction
    junction = Junction.from_text(BASE + "trip T4 R6 WK\n  NSC 06:30\n  BCH 08:21\ntrip T5 R5 WK\n  WIE 07:45\n  KRK 07:57\n")
    return [_plan(junction, "NSC", "RZE", "2026-03-02", "06:00"), _plan(junction, "WIE", "RZE", "2026-03-02", "07:00"),
            _plan(junction, "WIE", "TRN", "2026-03-03", "07:42")]


def probe_change_exact_journeys():
    from junction import Junction
    junction = Junction.from_text("""
station GDA "Gdansk Glowny" zone 1 transfer 6
station SOP "Sopot" zone 1 transfer 2
station GDY "Gdynia Glowna" zone 2 transfer 3
station HEL "Hel" zone 4
service ALL daily 2026-06-01..2026-08-31
trip K1 SKM ALL
  GDA 12:00
  SOP 12:12
  GDY 12:25
trip K2 SKM ALL
  GDA 12:20
  SOP 12:32
  GDY 12:45
trip H1 R88 ALL
  GDY 12:28
  HEL 14:00
trip H2 R88 ALL
  GDY 13:30
  HEL 15:00
trip P1 R70 ALL
  SOP 12:14
  HEL 14:30
""")
    found = junction.journeys("GDA", "HEL", "2026-07-04", "11:30")
    return [[j.summary() for j in found], [junction.fare(j) for j in found], _plan(junction, "SOP", "HEL", "2026-07-04", "12:00")]


# --- walking time is rounded up ---------------------------------------------------------
def probe_walk_transfer_rounding_plan():
    from junction import Network, Planner, Timetable
    network = Network()
    for code, name, zone in (("PL1", "Plac", 1), ("PL2", "Rynek", 1), ("PL3", "Dworzec", 1), ("LOT", "Lotnisko", 3),
                             ("MST", "Most", 2), ("SKY", "Skansen", 2)):
        network.add_station(code, name, zone=zone)
    network.add_footpath("PL2", "PL3", 250)
    network.add_footpath("MST", "PL2", 200)
    timetable = Timetable(network)
    timetable.add_service("D", "daily", "2026-01-01", "2026-12-31")
    for trip_id, stops in (("R1", [("PL1", None, "08:00"), ("PL2", "08:12", None)]),
                           ("R2", [("PL3", None, "08:15"), ("LOT", "08:40", None)]),
                           ("R3", [("PL3", None, "08:20"), ("LOT", "08:50", None)]),
                           ("R4", [("MST", None, "08:14"), ("SKY", "08:45", None)]),
                           ("R5", [("MST", None, "08:30"), ("SKY", "09:05", None)])):
        timetable.add_trip(trip_id, "M1", "D", stops)
    planner = Planner(timetable)
    return [_describe(planner, "PL1", "LOT", "2026-02-02", "07:50"), _describe(planner, "PL1", "SKY", "2026-02-02", "07:50")]


def probe_walk_text_journey():
    from junction import Junction
    junction = Junction.from_text("""
station LOD "Lodz Fabryczna" zone 1 transfer 4
station LOK "Lodz Kaliska" zone 1 transfer 4
station LDW "Lodz Widzew" zone 2
station SIE "Sieradz" zone 4
footpath LOD LOK 520
service ALL daily 2026-04-01..2026-04-30
trip A1 R1 ALL
  LDW 06:50
  LOD 07:03
trip A2 R2 ALL
  LOK 07:09
  SIE 08:10
trip A3 R2 ALL
  LOK 07:25
  SIE 08:30
""")
    journey = junction.plan("LDW", "SIE", "2026-04-15", "06:30")
    return [journey.describe().splitlines(), journey.walking, journey.waits(), junction.network.footpath("LOK", "LOD").minutes]


# --- disruptions reach the next day's listing -------------------------------------------
def probe_night_delay_after_board():
    from junction import arrivals, departures
    junction = _base()
    timetable = junction.timetable
    timetable.add_trip("N2", "N7", "NT", [("KRK", None, "23:40"), ("BCH", "24:05", "24:06"), ("TRN", "24:35", None)])
    timetable.add_trip("N6", "N7", "NT", [("TRN", None, "23:52"), ("BCH", "24:15", None)])
    before = _rows(departures(timetable, "BCH", "2026-03-03", "00:00", "01:00"))
    timetable.delay("N2", "2026-03-02", 12, "BCH")
    timetable.delay("N6", "2026-03-02", 9)
    return [before, _rows(departures(timetable, "BCH", "2026-03-03", "00:00", "01:00")),
            _rows(departures(timetable, "TRN", "2026-03-03", "00:00", "01:00")),
            _rows(arrivals(timetable, "BCH", "2026-03-03", "00:00", "01:00")),
            _rows(departures(timetable, "TRN", "2026-03-02", "23:00", "47:59"))]


def probe_night_cancel_feed_plan():
    junction = _base()
    junction.timetable.add_trip("N2", "N7", "NT", [("KRK", None, "23:40"), ("BCH", "24:05", "24:06"), ("TRN", "24:35", None)])
    first = _plan(junction, "BCH", "TRN", "2026-03-03", "00:00")
    junction.apply("cancel N2 2026-03-02\n")
    second = _plan(junction, "BCH", "TRN", "2026-03-03", "00:00")
    junction.apply("reinstate N2 2026-03-02\ndelay N2 2026-03-02 +20 from KRK\n")
    third = _plan(junction, "KRK", "TRN", "2026-03-02", "23:00")
    return [first, second, third, _plan(junction, "BCH", "TRN", "2026-03-03", "00:00")]


def probe_night_reinstate_arrivals():
    from junction import line_summary
    junction = _base()
    junction.timetable.add_trip("N8", "N8", "SA", [("RZE", None, "23:30"), ("DEB", "24:05", "24:06"), ("TRN", "24:40", None)])
    junction.timetable.cancel("N8", "2026-03-07")
    before = _rows(junction.arrivals("TRN", "2026-03-08"))
    junction.timetable.reinstate("N8", "2026-03-07")
    after = _rows(junction.arrivals("TRN", "2026-03-08"))
    junction.timetable.delay("N8", "2026-03-07", 5, "TRN")
    return [before, after, _rows(junction.arrivals("TRN", "2026-03-08")), line_summary(junction.timetable, "N8", "2026-03-07")]
