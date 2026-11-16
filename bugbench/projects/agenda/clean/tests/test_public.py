"""The project's own regression tests (visible to everyone)."""
import datetime
import unittest

from agenda import (Calendar, InvalidTime, Interval, NotAnOccurrence, Rule, ScheduleError, busy_minutes, free_slots,
                    parse_duration, replay)
from agenda import reports
from agenda.timeutil import add_months, format_duration

D = datetime.datetime
MIN = datetime.timedelta(minutes=1)


def stamp(items):
    return [item.start.strftime("%m-%d %H:%M") for item in items]


class TimeTests(unittest.TestCase):
    def test_durations(self):
        self.assertEqual(parse_duration("1h30m"), 90 * MIN)
        self.assertEqual(format_duration(135 * MIN), "2h15m")
        with self.assertRaises(InvalidTime):
            parse_duration("0m")

    def test_add_months_clamps(self):
        self.assertEqual(add_months(datetime.date(2026, 1, 31), 1), datetime.date(2026, 2, 28))
        self.assertEqual(add_months(datetime.date(2026, 1, 15), 13, -1), datetime.date(2027, 2, 28))

    def test_intervals_are_half_open(self):
        morning = Interval(D(2026, 3, 2, 10), D(2026, 3, 2, 11))
        self.assertFalse(morning.overlaps(Interval(D(2026, 3, 2, 11), D(2026, 3, 2, 12))))
        self.assertTrue(morning.overlaps(Interval(D(2026, 3, 2, 10, 59), D(2026, 3, 2, 12))))


class RuleTests(unittest.TestCase):
    def test_weekly_on_days(self):
        rule = Rule("weekly", weekdays=[0, 2], count=4)
        self.assertEqual([d.day for d in rule.starts(D(2026, 3, 2, 9))], [2, 4, 9, 11])
        self.assertEqual(rule.describe(), "every week on mon, wed; 4 times")

    def test_until_is_inclusive(self):
        rule = Rule("daily", interval=2, until=datetime.date(2026, 3, 7))
        self.assertEqual([d.day for d in rule.starts(D(2026, 3, 1, 8))], [1, 3, 5, 7])

    def test_monthly_last_day(self):
        rule = Rule("monthly", count=3)
        self.assertEqual([d.date() for d in rule.starts(D(2026, 1, 31, 12))],
                         [datetime.date(2026, 1, 31), datetime.date(2026, 2, 28), datetime.date(2026, 3, 31)])


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.cal = Calendar()
        self.cal.add_event("SYNC", "Sync", D(2026, 3, 2, 10), 30 * MIN, Rule("daily", count=5), room="R1",
                           attendees=["ann", "bob"])
        self.cal.add_event("LUNCH", "Lunch", D(2026, 3, 3, 10), 60 * MIN, attendees=["ann"])

    def test_listing_is_sorted_and_half_open(self):
        items = self.cal.occurrences(D(2026, 3, 2), D(2026, 3, 4))
        self.assertEqual([(item.event_id, item.start.day) for item in items], [("SYNC", 2), ("LUNCH", 3), ("SYNC", 3)])
        self.assertEqual(len(self.cal.occurrences(D(2026, 3, 2), D(2026, 3, 2, 10))), 0)

    def test_cancel_and_move(self):
        self.cal.cancel("SYNC", D(2026, 3, 3, 10))
        self.cal.move("SYNC", D(2026, 3, 4, 10), D(2026, 3, 4, 15))
        self.assertEqual(stamp(self.cal.series("SYNC")), ["03-02 10:00", "03-04 15:00", "03-05 10:00", "03-06 10:00"])
        with self.assertRaises(NotAnOccurrence):
            self.cal.cancel("SYNC", D(2026, 3, 9, 10))

    def test_split_keeps_dates(self):
        new = self.cal.split("SYNC", D(2026, 3, 4, 10), "SYNC-2", room="R2")
        self.assertEqual(stamp(self.cal.series("SYNC")), ["03-02 10:00", "03-03 10:00"])
        self.assertEqual(stamp(self.cal.series("SYNC-2")), ["03-04 10:00", "03-05 10:00", "03-06 10:00"])
        self.assertEqual((new.room, new.rule.count), ("R2", 3))


class AvailabilityTests(unittest.TestCase):
    def test_free_slots_hourly(self):
        cal = Calendar()
        cal.add_event("M", "Meeting", D(2026, 3, 3, 10), 90 * MIN, attendees=["ann"])
        slots = free_slots(cal, ["ann"], datetime.date(2026, 3, 3), 60 * MIN, step=60)
        self.assertEqual([slot.hour for slot in slots], [9, 12, 13, 14, 15, 16])
        self.assertEqual(free_slots(cal, ["ann"], datetime.date(2026, 3, 7), 60 * MIN), [])
        self.assertEqual(busy_minutes(cal, "ann", datetime.date(2026, 3, 3)), 90)


class ReportTests(unittest.TestCase):
    def test_agenda_hours_conflicts(self):
        cal = Calendar()
        cal.add_event("A", "Plan", D(2026, 3, 3, 9), 60 * MIN, room="R1", attendees=["ann"])
        cal.add_event("B", "Call", D(2026, 3, 3, 9, 30), 30 * MIN, attendees=["ann", "cy"])
        cal.add_event("C", "Demo", D(2026, 3, 3, 10), 30 * MIN, room="R1", attendees=["cy"])
        self.assertEqual(reports.day_agenda(cal, datetime.date(2026, 3, 3))[0], "09:00-10:00 A Plan @R1 [ann]")
        self.assertEqual(reports.week_hours(cal, datetime.date(2026, 3, 5)), [["ann", "1h30m"], ["cy", "1h"]])
        self.assertEqual(reports.conflicts(cal, D(2026, 3, 3), D(2026, 3, 4)),
                         [["A", "2026-03-03 09:00", "B", "2026-03-03 09:30", "attendee ann"]])


class ScheduleTests(unittest.TestCase):
    def test_replay(self):
        cal, results = replay('event X "Weekly review" at 2026-03-02 16:00 for 1h repeat weekly on mon,thu count 3 with ann\n'
                              "agenda 2026-03-05\n")
        self.assertEqual(results[-1]["lines"], ["16:00-17:00 X Weekly review [ann]"])
        self.assertEqual(reports.series_dates(cal, "X")[-1], "2026-03-09 16:00")

    def test_error_line(self):
        with self.assertRaises(ScheduleError) as caught:
            replay('event X "x" at 2026-03-02 16:00 for 1h\n\ncancel X 2026-03-03 16:00\n')
        self.assertEqual(caught.exception.line, 3)


if __name__ == "__main__":
    unittest.main()
