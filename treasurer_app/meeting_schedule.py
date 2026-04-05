"""Repeating lodge meeting dates: nth weekday in a given calendar month (e.g. 3rd Saturday in September)."""
from __future__ import annotations

from datetime import date

MONTH_CHOICES: tuple[tuple[int, str], ...] = (
    (1, "January"),
    (2, "February"),
    (3, "March"),
    (4, "April"),
    (5, "May"),
    (6, "June"),
    (7, "July"),
    (8, "August"),
    (9, "September"),
    (10, "October"),
    (11, "November"),
    (12, "December"),
)

# Python Monday=0 … Sunday=6 (datetime.weekday())
WEEKDAY_LABELS: tuple[tuple[int, str], ...] = (
    (0, "Monday"),
    (1, "Tuesday"),
    (2, "Wednesday"),
    (3, "Thursday"),
    (4, "Friday"),
    (5, "Saturday"),
    (6, "Sunday"),
)

ORDINAL_LABELS: tuple[tuple[int, str], ...] = (
    (1, "1st"),
    (2, "2nd"),
    (3, "3rd"),
    (4, "4th"),
    (5, "5th (or last if fewer)"),
)


def weekdays_in_month(year: int, month: int, weekday: int) -> list[date]:
    """All dates in month that fall on `weekday` (0=Monday … 6=Sunday)."""
    out: list[date] = []
    for day in range(1, 32):
        try:
            d = date(year, month, day)
        except ValueError:
            break
        if d.weekday() == weekday:
            out.append(d)
    return out


def nth_weekday_in_month(year: int, month: int, weekday: int, ordinal: int) -> date:
    """
    `ordinal` is 1-based: 1 = first such weekday in the month, 3 = third.
    If ordinal is 5 but the month only has four (e.g. Saturdays), the last one is used.
    """
    if ordinal < 1 or ordinal > 5:
        raise ValueError("ordinal must be 1–5")
    days = weekdays_in_month(year, month, weekday)
    if not days:
        raise ValueError("no matching weekdays")
    idx = min(ordinal, len(days)) - 1
    return days[idx]


def next_occurrence_on_or_after(
    month: int,
    weekday: int,
    ordinal: int,
    on_or_after: date,
) -> date:
    """Smallest date >= on_or_after that matches the rule in some year."""
    for y in range(on_or_after.year, on_or_after.year + 6):
        try:
            d = nth_weekday_in_month(y, month, weekday, ordinal)
        except ValueError:
            continue
        if d >= on_or_after:
            return d
    raise ValueError("could not find next occurrence")


def iso_date(d: date) -> str:
    return d.isoformat()
