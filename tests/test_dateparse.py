from datetime import date

import pytest

from metronome.dateparse import ABBREV_MONTHS, FULL_MONTHS, month_year_to_date


def test_month_year_to_date_full_month_name():
    assert month_year_to_date("January", 2026, FULL_MONTHS) == date(2026, 1, 1)


def test_month_year_to_date_abbreviated_month_name():
    assert month_year_to_date("Feb", 2026, ABBREV_MONTHS) == date(2026, 2, 1)


def test_month_year_to_date_unrecognized_month_name_raises_value_error_with_context():
    with pytest.raises(ValueError, match="Blorptember"):
        month_year_to_date("Blorptember", 2026, FULL_MONTHS)
