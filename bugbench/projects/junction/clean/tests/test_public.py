"""The project's own regression tests (visible to everyone)."""
import datetime
import unittest

from junction import (InvalidTime, Junction, JunctionError, Network, NoConnection, ParseError, Timetable, can_change,
                      line_summary, parse_time, wall_time, walking_minutes)
from junction.clock import parse_duration, parse_weekdays, weekday_text
from junction.fares import day_total, reduce, zone_price

TEXT = """
station KRK "Krakow Glowny" zone 1 transfer 5
station KRB "Krakow Bus Station" zone 1 transfer 2
station BCH "Bochnia" zone 2 transfer 0
station TRN "Tarnow" zone 3 transfer 4
station RZE "Rzeszow Glowny" zone 4
station WIE "Wieliczka" zone 2
footpath KRK KRB 240
service WK mon-fri 2026-03-02..2026-03-31 except 2026-03-13 add 2026-03-14
service NT daily 2026-03-01..2026-03-31
trip T1 IC31 WK
  KRK 08:02
  BCH 08:20 08:21
  TRN 08:41 08:43
  RZE 09:30
trip T3 R5 WK
  WIE 07:40
  KRK 07:52
trip B1 B7 WK
  WIE 07:30
  KRB 07:52
trip N1 N9 NT
  KRK 22:50
  BCH 23:10 23:11
  TRN 23:40
"""
DAY = "2026-03-02"


class ClockTests(unittest.TestCase):
    def test_times(self):
        self.assertEqual([parse_time(t) for t in ("0:00", "08:40", "24:40", "47:59")], [0, 520, 1480, 2879])
        self.assertEqual([wall_time(m) for m in (520, 1480)], ["08:40", "00:40+1"])
        for bad in ("48:00", "8:60", "8.40", -1):
            with self.assertRaises(InvalidTime):
                parse_time(bad)

    def test_durations_and_weekdays(self):
        self.assertEqual([parse_duration(t) for t in ("45", "45m", "2h", "1h05m")], [45, 45, 120, 65])
        self.assertEqual(parse_weekdays("fri-mon"), (0, 4, 5, 6))
        self.assertEqual(weekday_text((0, 1, 2, 3, 4)), "mon-fri")


class NetworkTests(unittest.TestCase):
    def test_walking_minutes(self):
        self.assertEqual([walking_minutes(m) for m in (80, 240, 400)], [1, 3, 5])
        with self.assertRaises(JunctionError):
            walking_minutes(0)

    def test_stations_and_footpaths(self):
        network = Network()
        network.add_station("AAA", "Alpha  Main", zone=2)
        network.add_station("BBB", "Beta", transfer=0)
        path = network.add_footpath("AAA", "BBB", 160)
        self.assertEqual((path.minutes, network.footpath("BBB", "AAA").minutes), (2, 2))
        self.assertEqual([s.name for s in network.find("main")], ["Alpha Main"])
        with self.assertRaises(JunctionError):
            network.add_station("AAA", "Again")

    def test_change_rule(self):
        network = Network()
        network.add_station("AAA", "Alpha", transfer=5)
        self.assertEqual([can_change(network, "AAA", 600, d) for d in (603, 610)], [False, True])


class TimetableTests(unittest.TestCase):
    def test_service_calendar(self):
        timetable = Junction.from_text(TEXT).timetable
        self.assertEqual(timetable.trips_on("2026-03-13"), ["N1"])
        self.assertEqual(timetable.trips_on("2026-03-14"), ["B1", "N1", "T1", "T3"])
        self.assertEqual(timetable.trips_on("2026-03-15"), ["N1"])

    def test_listing_and_delay(self):
        timetable = Junction.from_text(TEXT).timetable
        first = timetable.connections(DAY)
        self.assertEqual([(c.trip_id, c.start, c.departure) for c in first[:3]],
                         [("B1", "WIE", 450), ("T3", "WIE", 460), ("T1", "KRK", 482)])
        timetable.delay("T1", DAY, 7, "TRN")
        moved = [c for c in timetable.connections(DAY) if c.trip_id == "T1"]
        self.assertEqual([(c.departure, c.arrival, c.arrival_delay) for c in moved],
                         [(482, 500, 0), (501, 528, 7), (530, 577, 7)])
        self.assertEqual(timetable.disruptions(), ["2026-03-02 T1 +7 from TRN"])

    def test_bad_trips(self):
        timetable = Timetable(Network())
        timetable.network.add_station("AAA", "Alpha")
        timetable.network.add_station("BBB", "Beta")
        timetable.add_service("S", "daily", "2026-01-01", "2026-12-31")
        with self.assertRaises(JunctionError):
            timetable.add_trip("X", "L", "S", [("AAA", None, "08:00"), ("BBB", "08:00", None)])
        with self.assertRaises(JunctionError):
            timetable.add_trip("X", "L", "S", [("AAA", None, "08:00")])


class PlannerTests(unittest.TestCase):
    def test_direct(self):
        journey = Junction.from_text(TEXT).plan("KRK", "RZE", DAY, "07:30")
        self.assertEqual(journey.summary(), "08:02 KRK -> 09:30 RZE, 1h 28m, 0 transfers")

    def test_transfer_and_latest_departure(self):
        journey = Junction.from_text(TEXT).plan("WIE", "TRN", DAY, "07:00")
        self.assertEqual([leg.describe() for leg in journey.legs],
                         ["07:40 WIE -> 07:52 KRK  R5 T3", "08:02 KRK -> 08:41 TRN  IC31 T1"])

    def test_walk_between_rides(self):
        text = TEXT.replace("trip T3 R5 WK\n  WIE 07:40\n  KRK 07:52\n", "")
        journey = Junction.from_text(text).plan("WIE", "BCH", DAY, "07:00")
        self.assertEqual(journey.describe().splitlines()[1:],
                         ["  07:30 WIE -> 07:52 KRB  B7 B1", "  walk 3 min (240 m) KRB -> KRK", "  08:02 KRK -> 08:20 BCH  IC31 T1"])

    def test_no_connection(self):
        junction = Junction.from_text(TEXT)
        with self.assertRaises(NoConnection):
            junction.plan("KRK", "RZE", DAY, "09:00")
        self.assertEqual([j.departure for j in junction.journeys("KRK", "TRN", DAY, "07:00")], [482, 1370])


class BoardAndFareTests(unittest.TestCase):
    def test_board(self):
        junction = Junction.from_text(TEXT)
        junction.apply("delay T1 2026-03-02 +5\n")
        self.assertEqual(junction.board("KRK", DAY).splitlines(),
                         ["Krakow Glowny 2026-03-02", "08:07 +5    IC31   Rzeszow Glowny", "22:50       N9     Tarnow"])
        self.assertEqual([row.trip_id for row in junction.arrivals("TRN", DAY)], ["T1", "N1"])

    def test_line_summary_and_cancel(self):
        junction = Junction.from_text(TEXT)
        junction.apply("cancel T3 2026-03-02\n")
        self.assertEqual(line_summary(junction.timetable, "R5", DAY), [["T3", "WIE", "07:40", "KRK", "07:52", "cancelled"]])
        with self.assertRaises(ParseError) as caught:
            junction.apply("reinstate T3 2026-03-02\ncancel T3 2026-03-15\n")
        self.assertEqual(caught.exception.line, 2)

    def test_fares(self):
        junction = Junction.from_text(TEXT)
        journey = junction.plan("KRK", "TRN", DAY, "07:00")
        self.assertEqual([junction.fare(journey), junction.fare(journey, "student")], ["7.20", "3.50"])
        self.assertEqual([zone_price(n) for n in (1, 4, 5)], [400, 870, 1020])
        self.assertEqual(reduce(400, "senior"), 250)
        self.assertEqual(day_total(junction.network, [journey] * 3), 1600)

    def test_parse_errors(self):
        with self.assertRaises(ParseError) as caught:
            Junction.from_text('station KRK "K"\nfootpath KRK XYZ 100\n')
        self.assertEqual(caught.exception.line, 2)


if __name__ == "__main__":
    unittest.main()
