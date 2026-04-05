import unittest
from datetime import date

from treasurer_app.meeting_schedule import (
    next_occurrence_on_or_after,
    nth_weekday_in_month,
    weekdays_in_month,
)


class MeetingScheduleTests(unittest.TestCase):
    def test_nth_weekday_third_saturday_september_2026(self) -> None:
        # September 2026: 3rd Saturday is the 19th
        d = nth_weekday_in_month(2026, 9, 5, 3)
        self.assertEqual(d, date(2026, 9, 19))

    def test_next_occurrence_january_after_june(self) -> None:
        start = date(2026, 6, 1)
        d = next_occurrence_on_or_after(1, 5, 3, start)
        self.assertEqual(d, date(2027, 1, 16))

    def test_weekdays_in_month_count(self) -> None:
        # August 2026 has five Saturdays
        sat = weekdays_in_month(2026, 8, 5)
        self.assertEqual(len(sat), 5)


if __name__ == "__main__":
    unittest.main()
