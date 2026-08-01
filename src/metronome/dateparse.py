from __future__ import annotations

from datetime import date

FULL_MONTHS: dict[str, int] = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
}

ABBREV_MONTHS: dict[str, int] = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def month_year_to_date(month_name: str, year: int, month_names: dict[str, int]) -> date:
    """Convert a month name + year into the first-of-month date."""
    try:
        month_number = month_names[month_name]
    except KeyError:
        raise ValueError(f"unrecognized month name: {month_name!r}") from None
    return date(year, month_number, 1)
