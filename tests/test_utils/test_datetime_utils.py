# SPDX-License-Identifier: MIT
"""Unit tests for app.utils.datetime.DateTimeUtils.

Covers the timezone maths (to_utc / anchor_to_utc / combine_in_tz_to_utc /
resolve_tz / apply_tz), ISO formatting & parsing (fmt_dt / parse_iso /
today_iso), partial-date (vCard reduced accuracy) handling
(normalize_partial_date / partial_date_to_basic), calendar month arithmetic
(add_months) and vacation-datetime parsing (parse_vacation_datetime).

Pure-python module: no external systems touched, fully hermetic.
"""
from __future__ import annotations

import pytest
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from app.utils.datetime.DateTimeUtils import (
    add_months,
    anchor_to_utc,
    apply_tz,
    combine_in_tz_to_utc,
    fmt_dt,
    normalize_partial_date,
    parse_iso,
    parse_vacation_datetime,
    partial_date_to_basic,
    resolve_tz,
    to_utc,
    today_iso,
)

_UTC = timezone.utc


class TestToUtc:
    """to_utc: normalise datetime/date to a UTC-aware datetime."""

    def test_naive_datetime_assumed_utc(self):
        result = to_utc(datetime(2026, 6, 15, 14, 30, 0))
        assert result == datetime(2026, 6, 15, 14, 30, 0, tzinfo=_UTC)
        assert result.tzinfo is _UTC

    def test_utc_aware_unchanged(self):
        dt = datetime(2026, 6, 15, 14, 30, 0, tzinfo=_UTC)
        assert to_utc(dt) == dt

    def test_non_utc_aware_converted(self):
        dt = datetime(2026, 6, 15, 14, 30, 0, tzinfo=ZoneInfo("Europe/Paris"))
        # 14:30 Paris (CEST, +02) = 12:30 UTC
        assert to_utc(dt) == datetime(2026, 6, 15, 12, 30, 0, tzinfo=_UTC)

    def test_date_only_becomes_midnight_utc(self):
        result = to_utc(date(2026, 6, 15))
        assert result == datetime(2026, 6, 15, 0, 0, 0, tzinfo=_UTC)
        assert isinstance(result, datetime)


class TestTodayIso:
    """today_iso: current UTC date in ISO-8601 extended form."""

    def test_returns_extended_iso_within_todays_boundary(self):
        before = datetime.now(_UTC).date()
        iso = today_iso()
        after = datetime.now(_UTC).date()
        # Guard against a midnight rollover between the boundary reads.
        assert before <= date.fromisoformat(iso) <= after

    def test_format_is_yyyy_mm_dd(self):
        iso = today_iso()
        assert len(iso) == 10
        assert iso[4] == "-" and iso[7] == "-"
        date.fromisoformat(iso)  # must be a real calendar date


class TestResolveTz:
    """resolve_tz: IANA zone lookup with UTC fallback."""

    def test_valid_iana_zone_roundtrip(self):
        z = resolve_tz("Europe/Berlin")
        assert isinstance(z, ZoneInfo)
        assert z == ZoneInfo("Europe/Berlin")

    def test_unknown_zone_falls_back_to_utc(self):
        z = resolve_tz("Mars/Olympus")
        assert isinstance(z, ZoneInfo)
        assert z == ZoneInfo("UTC")

    def test_unknown_zone_key_error_variant(self):
        # Both ZoneInfoNotFoundError and KeyError are swallowed by the fallback.
        assert resolve_tz("Obviously/Not/AZone") == ZoneInfo("UTC")

    def test_fallback_zone_has_zero_utc_offset(self):
        z = resolve_tz("Nope/Nope")
        assert z.utcoffset(datetime(2026, 6, 1, tzinfo=_UTC)) == timezone.utc.utcoffset(None)


class TestAnchorToUtc:
    """anchor_to_utc: convert to UTC, anchoring naive values in a default zone."""

    def test_naive_anchored_in_summer_default_tz(self):
        naive = datetime(2026, 6, 1, 10, 0, 0)
        # 10:00 Paris in June (CEST, +02) = 08:00 UTC
        assert anchor_to_utc(naive, "Europe/Paris") == datetime(2026, 6, 1, 8, 0, 0, tzinfo=_UTC)

    def test_naive_anchored_in_winter_default_tz(self):
        naive = datetime(2026, 1, 15, 10, 0, 0)
        # 10:00 Paris in January (CET, +01) = 09:00 UTC
        assert anchor_to_utc(naive, "Europe/Paris") == datetime(2026, 1, 15, 9, 0, 0, tzinfo=_UTC)

    def test_aware_value_ignores_default_tz(self):
        aware = datetime(2026, 6, 1, 10, 0, 0, tzinfo=_UTC)
        assert anchor_to_utc(aware, "America/New_York") == aware

    def test_naive_without_default_tz_assumes_utc(self):
        naive = datetime(2026, 6, 1, 10, 0, 0)
        assert anchor_to_utc(naive, None) == datetime(2026, 6, 1, 10, 0, 0, tzinfo=_UTC)

    def test_non_utc_aware_converted(self):
        aware = datetime(2026, 6, 1, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        # 10:00 EDT (summer, -04) = 14:00 UTC
        assert anchor_to_utc(aware, "UTC") == datetime(2026, 6, 1, 14, 0, 0, tzinfo=_UTC)

    def test_unknown_default_tz_falls_back_to_utc(self):
        naive = datetime(2026, 6, 1, 10, 0, 0)
        assert anchor_to_utc(naive, "Mars/Olympus") == datetime(2026, 6, 1, 10, 0, 0, tzinfo=_UTC)


class TestCombineInTzToUtc:
    """combine_in_tz_to_utc: join a date + wall-clock in tz, output UTC."""

    def test_summer_dst_offset_applied(self):
        # 09:00 wall-clock Paris in June (CEST, +02) = 07:00 UTC
        result = combine_in_tz_to_utc(date(2026, 6, 1), time(9, 0, 0), ZoneInfo("Europe/Paris"))
        assert result == datetime(2026, 6, 1, 7, 0, 0, tzinfo=_UTC)

    def test_winter_offset_differs(self):
        # Same wall-clock in January (CET, +01) = 08:00 UTC
        result = combine_in_tz_to_utc(date(2026, 1, 1), time(9, 0, 0), ZoneInfo("Europe/Paris"))
        assert result == datetime(2026, 1, 1, 8, 0, 0, tzinfo=_UTC)

    def test_utc_zone_passthrough(self):
        result = combine_in_tz_to_utc(date(2026, 6, 1), time(23, 59, 59), ZoneInfo("UTC"))
        assert result == datetime(2026, 6, 1, 23, 59, 59, tzinfo=_UTC)

    def test_day_boundary_rollover(self):
        # 23:30 wall-clock Paris in June (+02) = 21:30 UTC same day (no date flip)
        result = combine_in_tz_to_utc(date(2026, 6, 15), time(23, 30, 0), ZoneInfo("Europe/Paris"))
        assert result == datetime(2026, 6, 15, 21, 30, 0, tzinfo=_UTC)


class TestFmtDt:
    """fmt_dt: ISO-8601 UTC rendering with millisecond precision ending in Z."""

    def test_naive_assumed_utc(self):
        assert fmt_dt(datetime(2026, 6, 15, 14, 30, 0)) == "2026-06-15T14:30:00.000Z"

    def test_millisecond_precision(self):
        assert fmt_dt(datetime(2026, 6, 15, 14, 30, 0, 123456, tzinfo=_UTC)) == "2026-06-15T14:30:00.123Z"

    def test_sub_millisecond_truncated_not_rounded(self):
        # 500 microseconds -> 0 ms (truncation, not rounding)
        assert fmt_dt(datetime(2026, 6, 15, 14, 30, 0, 500, tzinfo=_UTC)) == "2026-06-15T14:30:00.000Z"

    def test_non_utc_converted_to_utc(self):
        # 16:30 Paris CEST (+02) = 14:30 UTC
        paris = datetime(2026, 6, 15, 16, 30, 0, tzinfo=ZoneInfo("Europe/Paris"))
        assert fmt_dt(paris) == "2026-06-15T14:30:00.000Z"

    def test_utc_zoneinfo_object_is_not_reconverted(self):
        # ZoneInfo("UTC") is a different object from timezone.utc yet must not shift the value.
        dt = datetime(2026, 6, 15, 14, 30, 0, tzinfo=ZoneInfo("UTC"))
        assert fmt_dt(dt) == "2026-06-15T14:30:00.000Z"

    def test_always_ends_in_z(self):
        for dt in (datetime(2026, 6, 15, 0, 0, 0, tzinfo=_UTC),
                   datetime(2026, 12, 31, 23, 59, 59, 999999, tzinfo=_UTC)):
            assert fmt_dt(dt).endswith("Z")


class TestAddMonths:
    """add_months: calendar month-shift with last-day clamping."""

    def test_forward_within_and_across_years(self):
        assert add_months(datetime(2026, 6, 15, 9, tzinfo=_UTC), 9) == datetime(2027, 3, 15, 9, tzinfo=_UTC)
        assert add_months(datetime(2026, 11, 15, tzinfo=_UTC), 3) == datetime(2027, 2, 15, tzinfo=_UTC)

    def test_backward(self):
        assert add_months(datetime(2026, 6, 15, 9, tzinfo=_UTC), -3) == datetime(2026, 3, 15, 9, tzinfo=_UTC)
        assert add_months(datetime(2026, 2, 15, tzinfo=_UTC), -3) == datetime(2025, 11, 15, tzinfo=_UTC)

    def test_zero_months_unchanged(self):
        dt = datetime(2026, 6, 15, 9, 30, 15, tzinfo=_UTC)
        assert add_months(dt, 0) == dt

    def test_clamps_non_leap_february(self):
        # 2026 is not a leap year: Jan 31 + 1 month -> Feb 28
        assert add_months(datetime(2026, 1, 31, tzinfo=_UTC), 1) == datetime(2026, 2, 28, tzinfo=_UTC)

    def test_clamps_to_leap_february(self):
        # 2024 is a leap year: Jan 31 + 1 month -> Feb 29
        assert add_months(datetime(2024, 1, 31, tzinfo=_UTC), 1) == datetime(2024, 2, 29, tzinfo=_UTC)

    def test_clamps_short_month_backward(self):
        # Mar 31 - 1 month -> Feb 28 (2026)
        assert add_months(datetime(2026, 3, 31, tzinfo=_UTC), -1) == datetime(2026, 2, 28, tzinfo=_UTC)

    def test_clamp_across_multi_year_leap(self):
        # Jan 31 2024 + 13 months = Feb 2025 (non-leap) -> Feb 28 2025
        assert add_months(datetime(2024, 1, 31, tzinfo=_UTC), 13) == datetime(2025, 2, 28, tzinfo=_UTC)

    def test_day_and_time_preserved_when_not_clamped(self):
        dt = datetime(2026, 6, 15, 9, 30, 15, tzinfo=_UTC)
        assert add_months(dt, 1) == datetime(2026, 7, 15, 9, 30, 15, tzinfo=_UTC)


class TestApplyTz:
    """apply_tz: render a datetime in an IANA zone, None on unknown zones."""

    def test_summer_offset(self):
        utc = datetime(2026, 6, 15, 12, 0, 0, tzinfo=_UTC)
        assert apply_tz(utc, "Europe/Paris") == "2026-06-15T14:00:00+02:00"

    def test_winter_offset(self):
        utc = datetime(2026, 1, 15, 12, 0, 0, tzinfo=_UTC)
        assert apply_tz(utc, "America/New_York") == "2026-01-15T07:00:00-05:00"

    def test_utc_zone(self):
        utc = datetime(2026, 6, 15, 12, 0, 0, tzinfo=_UTC)
        assert apply_tz(utc, "UTC") == "2026-06-15T12:00:00+00:00"

    def test_unknown_zone_returns_none(self):
        utc = datetime(2026, 6, 15, 12, 0, 0, tzinfo=_UTC)
        assert apply_tz(utc, "Bogus/Zone") is None
        assert apply_tz(utc, "Mars/Olympus") is None


class TestParseIso:
    """parse_iso: ISO strings -> tz-aware UTC datetime, None when absent."""

    def test_naive_assumed_utc(self):
        assert parse_iso("2026-06-15T14:30:00") == datetime(2026, 6, 15, 14, 30, 0, tzinfo=_UTC)

    def test_z_suffix(self):
        assert parse_iso("2026-06-15T14:30:00Z") == datetime(2026, 6, 15, 14, 30, 0, tzinfo=_UTC)

    def test_numeric_offset_converted_to_utc(self):
        assert parse_iso("2026-06-15T14:30:00+02:00") == datetime(2026, 6, 15, 12, 30, 0, tzinfo=_UTC)

    def test_negative_offset(self):
        assert parse_iso("2026-06-15T10:30:00-04:00") == datetime(2026, 6, 15, 14, 30, 0, tzinfo=_UTC)

    def test_empty_or_none_returns_none(self):
        assert parse_iso("") is None
        assert parse_iso(None) is None

    def test_garbage_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_iso("not-a-date")


class TestNormalizePartialDate:
    """normalize_partial_date: vCard reduced-accuracy date normalising."""

    def test_full_extended(self):
        assert normalize_partial_date("1985-04-12") == "1985-04-12"

    def test_full_basic_to_extended(self):
        assert normalize_partial_date("19850412") == "1985-04-12"

    def test_full_with_surrounding_whitespace(self):
        assert normalize_partial_date("  1985-04-12 ") == "1985-04-12"

    def test_yearless_basic_to_extended(self):
        assert normalize_partial_date("--0412") == "--04-12"

    def test_yearless_extended_passthrough(self):
        assert normalize_partial_date("--04-12") == "--04-12"

    def test_rejects_impossible_calendar_date(self):
        assert normalize_partial_date("1985-13-40") is None
        assert normalize_partial_date("1985-02-30") is None  # Feb 30

    def test_rejects_text_and_unsupported_shapes(self):
        assert normalize_partial_date("circa 1800") is None
        assert normalize_partial_date("1985") is None  # year only, not modelled
        assert normalize_partial_date("1985-04") is None  # year+month only, not modelled

    def test_yearless_range_validation(self):
        assert normalize_partial_date("--13-01") is None  # month out of range
        assert normalize_partial_date("--00-10") is None  # zero month
        assert normalize_partial_date("--04-32") is None  # day out of range


class TestPartialDateToBasic:
    """partial_date_to_basic: canonical -> basic form (compact digits)."""

    def test_full_date(self):
        assert partial_date_to_basic("1985-04-12") == "19850412"

    def test_yearless_date(self):
        assert partial_date_to_basic("--04-12") == "--0412"

    def test_roundtrip_with_normalize(self):
        for source in ("1985-04-12", "19850412", "--0412", "--04-12"):
            canonical = normalize_partial_date(source)
            assert canonical is not None
            assert normalize_partial_date(partial_date_to_basic(canonical)) == canonical


class TestParseVacationDatetime:
    """parse_vacation_datetime: split vacation strings into (date, time, tz)."""

    def test_date_only(self):
        assert parse_vacation_datetime("2026-06-15") == ("2026-06-15", None, "UTC")

    def test_date_only_with_iana_default_tz(self):
        assert parse_vacation_datetime("2026-06-15", "Europe/Paris") == ("2026-06-15", None, "Europe/Paris")

    def test_datetime_uses_default_tz(self):
        assert parse_vacation_datetime("2026-06-15T14:30:00") == ("2026-06-15", "14:30:00", "UTC")

    def test_datetime_two_part_time(self):
        assert parse_vacation_datetime("2026-06-15T14:30") == ("2026-06-15", "14:30", "UTC")

    def test_z_suffix_maps_to_utc(self):
        assert parse_vacation_datetime("2026-06-15T14:30:00Z") == ("2026-06-15", "14:30:00", "UTC")

    def test_positive_offset_hhmm(self):
        assert parse_vacation_datetime("2026-06-15T14:30:00+0100") == ("2026-06-15", "14:30:00", "+0100")

    def test_positive_offset_hh_mm(self):
        assert parse_vacation_datetime("2026-06-15T14:30:00+01:00") == ("2026-06-15", "14:30:00", "+01:00")

    def test_negative_offset_hhmm(self):
        assert parse_vacation_datetime("2026-06-15T14:30:00-0500") == ("2026-06-15", "14:30:00", "-0500")

    def test_named_zone_colon_form(self):
        assert parse_vacation_datetime("2026-06-15T14:30:00:Europe/Paris") == (
            "2026-06-15", "14:30:00", "Europe/Paris")

    def test_named_zone_gmt_prefix(self):
        assert parse_vacation_datetime("2026-06-15T14:30:00:GMT") == ("2026-06-15", "14:30:00", "GMT")

    def test_zone_with_plus_suffix_is_parsed_as_offset(self):
        # "GMT+3" hits the "+" offset branch BEFORE the named-zone branch:
        # the time keeps "14:30:00:GMT" and the offset "+3" becomes the tz.
        assert parse_vacation_datetime("2026-06-15T14:30:00:GMT+3") == (
            "2026-06-15", "14:30:00:GMT", "+3")

    def test_colon_suffix_without_valid_zone_kept_in_time(self):
        # A trailing ":NoZone" doesn't look like a zone -> the whole time string is kept.
        assert parse_vacation_datetime("2026-06-15T14:30:00:NoZone") == (
            "2026-06-15", "14:30:00:NoZone", "UTC")

    def test_invalid_date_only(self):
        assert parse_vacation_datetime("2026-13-45") == (None, None, "UTC")

    def test_invalid_date_part_in_datetime(self):
        assert parse_vacation_datetime("2026-13-01T10:00:00") == (None, None, "UTC")

    def test_empty_and_none_input(self):
        assert parse_vacation_datetime("") == (None, None, "UTC")
        assert parse_vacation_datetime(None) == (None, None, "UTC")

    def test_non_date_text(self):
        assert parse_vacation_datetime("hello world") == (None, None, "UTC")

    def test_non_string_input(self):
        assert parse_vacation_datetime(12345) == (None, None, "UTC")

    def test_tz_converter_receives_date_for_dst(self):
        calls: list[tuple[str | None, str | None]] = []

        def recorder(tz, dt=None):
            calls.append((tz, dt))
            return f"<{tz}|{dt}>"

        assert parse_vacation_datetime("2026-06-15T14:30:00Z", tz_converter=recorder) == (
            "2026-06-15", "14:30:00", "<UTC|2026-06-15>")
        assert calls == [("UTC", "2026-06-15")]

    def test_tz_converter_applied_to_default_tz_on_failure(self):
        def upper(tz, dt=None):
            return str(tz).upper()

        # Invalid input: converter is still applied to the default tz.
        assert parse_vacation_datetime("garbage", "Europe/Paris", tz_converter=upper) == (
            None, None, "EUROPE/PARIS")
