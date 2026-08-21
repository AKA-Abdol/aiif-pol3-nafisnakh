import pandas as pd
import pytest

from nafisnakh.io.normalize import (
    customer_universe,
    jalali_to_gregorian,
    normalize_customer_id,
    normalize_fa,
    parse_date_any,
    to_datetime_mixed,
)


@pytest.mark.parametrize(
    "jalali,gregorian",
    [
        ((1395, 8, 12), (2016, 11, 2)),
        ((1394, 1, 1), (2015, 3, 21)),
        ((1399, 12, 30), (2021, 3, 20)),   # leap year in the Jalali calendar
        ((1403, 1, 1), (2024, 3, 20)),
        ((1404, 1, 31), (2025, 4, 20)),    # the date form seen in universe B prose
    ],
)
def test_jalali_conversion(jalali, gregorian):
    assert jalali_to_gregorian(*jalali) == gregorian


def test_parse_date_any_handles_both_calendars():
    assert parse_date_any("2020-07-20") == pd.Timestamp(2020, 7, 20)
    assert parse_date_any("1395/08/12") == pd.Timestamp(2016, 11, 2)
    assert parse_date_any("۱۴۰۴/۰۱/۳۱") == pd.Timestamp(2025, 4, 20)
    assert pd.isna(parse_date_any(None))
    assert pd.isna(parse_date_any(""))


def test_to_datetime_mixed_column():
    s = pd.Series(["2020-07-20", "1395/08/12", None])
    out = to_datetime_mixed(s)
    assert out.iloc[0] == pd.Timestamp(2020, 7, 20)
    assert out.iloc[1] == pd.Timestamp(2016, 11, 2)
    assert pd.isna(out.iloc[2])


def test_normalize_fa_collapses_orthographic_noise():
    assert normalize_fa("سيمي") == normalize_fa("سیمی")
    assert normalize_fa("مي‌باشد") == "می باشد"
    assert normalize_fa("۱۲۳") == "123"
    assert normalize_fa(None) == ""


def test_customer_id_namespace():
    assert customer_universe("C_009817") == "A"
    assert customer_universe("CUST-001") == "B"
    assert customer_universe("junk") == "unknown"
    assert normalize_customer_id("cust-7") == "CUST-007"
    assert normalize_customer_id("C_009817") == "C_009817"
