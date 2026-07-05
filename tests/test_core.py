"""Unit tests for hongkong_holiday. No network access is required: the
GovHK feed is replaced by a fixture payload via monkeypatching."""

import datetime as dt

import pytest

from hongkong_holiday import (
    DateInfo,
    HKHolidays,
    HKHolidaysError,
    Holiday,
    SOURCE_ESTIMATED,
    SOURCE_GOVHK,
    ensure_date,
    export_csv,
    parse_ical_date,
    weekday_number,
)

# The real 2026 holidays from the GovHK feed, plus a single 2027 spillover
# event: 2027 must NOT be treated as an API-covered year (partial data).
_EVENTS_2026 = [
    ("20260101", "The first day of January"),
    ("20260217", "Lunar New Year's Day"),
    ("20260218", "The second day of Lunar New Year"),
    ("20260219", "The third day of Lunar New Year"),
    ("20260403", "Good Friday"),
    ("20260404", "The day following Good Friday"),
    ("20260406", "The day following Ching Ming Festival"),
    ("20260407", "The day following Easter Monday"),
    ("20260501", "Labour Day"),
    ("20260525", "The day following the Birthday of the Buddha"),
    ("20260619", "Tuen Ng Festival"),
    ("20260701", "Hong Kong Special Administrative Region Establishment Day"),
    ("20260926", "The day following the Chinese Mid-Autumn Festival"),
    ("20261001", "National Day"),
    ("20261019", "The day following Chung Yeung Festival"),
    ("20261225", "Christmas Day"),
    ("20261226", "The first weekday after Christmas Day"),
    ("20270101", "The first day of January"),
]

FEED = {
    "vcalendar": [
        {
            "prodid": "-//1823//Hong Kong Public Holidays//EN",
            "vevent": [
                {"dtstart": [day, {"value": "DATE"}], "summary": name}
                for day, name in _EVENTS_2026
            ],
        }
    ]
}


@pytest.fixture
def hk(monkeypatch):
    """An HKHolidays instance wired to the fixture feed instead of HTTP."""
    monkeypatch.setattr(HKHolidays, "_download", lambda self, url: FEED)
    return HKHolidays(lang="en")


@pytest.fixture
def hk_offline(monkeypatch):
    """An HKHolidays instance whose feed download always fails."""

    def boom(self, url):
        raise HKHolidaysError("network down")

    monkeypatch.setattr(HKHolidays, "_download", boom)
    return HKHolidays(lang="en")


# ---------------------------------------------------------------------------
# API path (cached feed)
# ---------------------------------------------------------------------------
class TestApiPath:
    def test_known_holiday(self, hk):
        assert hk.is_public_holiday("2026-07-01")
        assert hk.is_holiday(dt.date(2026, 7, 1))
        assert hk.holiday_name("2026-07-01").startswith("Hong Kong Special")

    def test_working_day(self, hk):
        # 2026-07-02 is a Thursday and not a holiday in the fixture.
        assert not hk.is_holiday("2026-07-02")
        assert hk.holiday_name("2026-07-02") is None

    def test_source_is_govhk_inside_window(self, hk):
        holiday = hk.get_holiday("2026-12-25")
        assert holiday == Holiday(dt.date(2026, 12, 25), "Christmas Day", SOURCE_GOVHK)

    def test_api_years_detected(self, hk):
        # 2027 has only one spillover event, so it must not count as covered.
        assert hk.api_years == [2026]

    def test_partial_year_uses_fallback(self, hk):
        holidays_2027 = hk.get_holidays(2027)
        assert len(holidays_2027) > 10
        assert all(h.source == SOURCE_ESTIMATED for h in holidays_2027)

    def test_get_holidays_sorted(self, hk):
        days = [h.date for h in hk.get_holidays(2026)]
        assert days == sorted(days)
        assert all(d.year == 2026 for d in days)

    def test_include_sundays(self, hk):
        holidays = hk.get_holidays(2026, include_sundays=True)
        sundays = [h for h in holidays if h.name == "Sunday"]
        # 2026 has 52 Sundays.
        assert len(sundays) == 52
        assert all(h.date.weekday() == 6 for h in sundays)

    def test_next_holiday(self, hk):
        nxt = hk.next_holiday(dt.date(2026, 10, 20))
        assert nxt.date == dt.date(2026, 12, 25)

    def test_feed_fetched_once(self, monkeypatch):
        calls = []

        def fake_download(self, url):
            calls.append(url)
            return FEED

        monkeypatch.setattr(HKHolidays, "_download", fake_download)
        hk = HKHolidays()
        hk.is_holiday("2026-07-01")
        hk.is_holiday("2026-12-25")
        assert len(calls) == 1
        hk.refresh()
        hk.is_holiday("2026-07-01")
        assert len(calls) == 2


# ---------------------------------------------------------------------------
# Sundays are general holidays everywhere (API window or not)
# ---------------------------------------------------------------------------
class TestSundays:
    def test_sunday_inside_window(self, hk):
        assert hk.is_holiday("2026-07-05")  # a Sunday
        assert not hk.is_public_holiday("2026-07-05")
        assert hk.holiday_name("2026-07-05") == "Sunday"

    def test_sunday_outside_window(self, hk):
        assert hk.is_holiday("2020-01-05")  # a Sunday in 2020

    def test_sundays_can_be_excluded(self, hk):
        assert not hk.is_holiday("2026-07-05", include_sundays=False)


# ---------------------------------------------------------------------------
# include_sundays / include_saturdays options
# ---------------------------------------------------------------------------
class TestWeekendOptions:
    # 2026-07-04 is a Saturday, 2026-07-05 a Sunday, neither a named holiday.
    def test_is_holiday_saturday(self, hk):
        assert not hk.is_holiday("2026-07-04")
        assert hk.is_holiday("2026-07-04", include_saturdays=True)

    def test_is_public_holiday_flags(self, hk):
        assert not hk.is_public_holiday("2026-07-05")
        assert hk.is_public_holiday("2026-07-05", include_sundays=True)
        assert hk.is_public_holiday("2026-07-04", include_saturdays=True)

    def test_holiday_name_flags(self, hk):
        assert hk.holiday_name("2026-07-04") is None
        assert hk.holiday_name("2026-07-04", include_saturdays=True) == "Saturday"
        assert hk.holiday_name("2026-07-05") == "Sunday"
        assert hk.holiday_name("2026-07-05", include_sundays=False) is None

    def test_get_holiday_flags(self, hk):
        assert hk.get_holiday("2026-07-04") is None
        saturday = hk.get_holiday("2026-07-04", include_saturdays=True)
        assert saturday == Holiday(dt.date(2026, 7, 4), "Saturday", SOURCE_GOVHK)
        # A named holiday keeps its name even with the flags on.
        named = hk.get_holiday("2026-07-01", include_sundays=True, include_saturdays=True)
        assert named.name.startswith("Hong Kong Special")

    def test_get_holidays_with_saturdays(self, hk):
        holidays = hk.get_holidays(2026, include_saturdays=True)
        saturdays = [h for h in holidays if h.name == "Saturday"]
        # 2026 has 52 Saturdays; three (4 Apr, 26 Sep, 26 Dec) are named holidays.
        assert len(saturdays) == 49
        assert all(h.date.weekday() == 5 for h in saturdays)

    def test_next_holiday_with_sundays(self, hk):
        nxt = hk.next_holiday(dt.date(2026, 7, 1), include_sundays=True)
        assert nxt == Holiday(dt.date(2026, 7, 5), "Sunday", SOURCE_GOVHK)


# ---------------------------------------------------------------------------
# get_date / get_dates
# ---------------------------------------------------------------------------
class TestGetDate:
    def test_weekday_numbering(self):
        # Sunday-first convention: Sunday=0, Monday=1 ... Saturday=6.
        assert weekday_number(dt.date(2026, 7, 5)) == 0  # Sunday
        assert weekday_number(dt.date(2026, 7, 6)) == 1  # Monday
        assert weekday_number(dt.date(2026, 7, 4)) == 6  # Saturday

    def test_get_date_named_holiday(self, hk):
        info = hk.get_date("2026-07-01")  # a Wednesday
        assert info == DateInfo(
            date=dt.date(2026, 7, 1),
            weekday=3,
            is_holiday=True,
            holiday_name="Hong Kong Special Administrative Region Establishment Day",
        )

    def test_get_date_sunday_default(self, hk):
        info = hk.get_date("2026-07-05")
        assert info.weekday == 0
        assert info.is_holiday
        assert info.holiday_name == "Sunday"

    def test_get_date_flags(self, hk):
        assert not hk.get_date("2026-07-05", include_sundays=False).is_holiday
        info = hk.get_date("2026-07-04", include_saturdays=True)
        assert info.weekday == 6
        assert info.holiday_name == "Saturday"

    def test_get_date_working_day(self, hk):
        info = hk.get_date("2026-07-02")  # Thursday
        assert info == DateInfo(dt.date(2026, 7, 2), 4, False, None)

    def test_get_dates_full_year(self, hk):
        infos = hk.get_dates(2026)
        assert len(infos) == 365
        assert infos[0].date == dt.date(2026, 1, 1)
        assert infos[-1].date == dt.date(2026, 12, 31)
        # New Year's Day is a named holiday, not overwritten by weekday logic.
        assert infos[0].is_holiday and infos[0].holiday_name.startswith("The first")
        # Every entry's weekday matches the Sunday-first convention.
        assert all(i.weekday == weekday_number(i.date) for i in infos)
        # Default counts Sundays (52) + 17 named holidays.
        assert sum(1 for i in infos if i.is_holiday) == 52 + 17

    def test_get_dates_with_saturdays(self, hk):
        infos = hk.get_dates(2026, include_saturdays=True)
        # + 52 Saturdays, minus the 3 that are already named holidays.
        assert sum(1 for i in infos if i.is_holiday) == 52 + 17 + 49

    def test_get_dates_leap_year_fallback(self, hk):
        assert len(hk.get_dates(2020)) == 366


# ---------------------------------------------------------------------------
# Fallback path (years outside the feed window)
# ---------------------------------------------------------------------------
class TestFallback:
    def test_historical_year_uses_estimation(self, hk):
        holidays_2020 = hk.get_holidays(2020)
        assert holidays_2020, "fallback returned no holidays for 2020"
        assert all(h.source == SOURCE_ESTIMATED for h in holidays_2020)
        # 1 July 2020 (HKSAR Establishment Day) is a stable fixed-date holiday.
        assert hk.is_public_holiday("2020-07-01")

    def test_far_future_year(self, hk):
        assert hk.is_public_holiday(dt.date(2035, 7, 1))

    def test_fallback_disabled_raises(self, monkeypatch):
        monkeypatch.setattr(HKHolidays, "_download", lambda self, url: FEED)
        hk = HKHolidays(use_fallback=False)
        with pytest.raises(HKHolidaysError):
            hk.get_holidays(2020)

    def test_offline_falls_back_entirely(self, hk_offline):
        assert hk_offline.is_public_holiday("2026-07-01")
        holiday = hk_offline.get_holiday("2026-07-01")
        assert holiday.source == SOURCE_ESTIMATED

    def test_offline_without_fallback_raises(self, monkeypatch):
        def boom(self, url):
            raise HKHolidaysError("network down")

        monkeypatch.setattr(HKHolidays, "_download", boom)
        hk = HKHolidays(use_fallback=False)
        with pytest.raises(HKHolidaysError):
            hk.is_holiday("2026-07-01")


# ---------------------------------------------------------------------------
# Parsing and validation
# ---------------------------------------------------------------------------
class TestParsing:
    def test_parse_feed_skips_bad_events(self):
        payload = {
            "vcalendar": [
                {
                    "vevent": [
                        {"dtstart": ["20260101", {"value": "DATE"}], "summary": "OK"},
                        {"dtstart": ["not-a-date"], "summary": "Bad"},
                        {"summary": "Missing dtstart"},
                    ]
                }
            ]
        }
        parsed = HKHolidays._parse_feed(payload)
        assert list(parsed) == [dt.date(2026, 1, 1)]

    def test_parse_feed_empty_raises(self):
        with pytest.raises(HKHolidaysError):
            HKHolidays._parse_feed({"vcalendar": []})

    def test_invalid_lang_rejected(self):
        with pytest.raises(ValueError):
            HKHolidays(lang="fr")

    def test_parse_ical_date(self):
        assert parse_ical_date("20260701") == dt.date(2026, 7, 1)
        with pytest.raises(ValueError):
            parse_ical_date("2026-07-01")

    def test_ensure_date_variants(self):
        expected = dt.date(2026, 7, 1)
        assert ensure_date("2026-07-01") == expected
        assert ensure_date("20260701") == expected
        assert ensure_date(dt.datetime(2026, 7, 1, 9, 30)) == expected
        assert ensure_date(expected) == expected
        with pytest.raises(TypeError):
            ensure_date(20260701)


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------
class TestExport:
    def test_export_csv(self, hk, tmp_path):
        target = tmp_path / "holidays_2026.csv"
        written = export_csv(hk.get_holidays(2026), target)
        assert written == target
        lines = target.read_text(encoding="utf-8-sig").strip().splitlines()
        assert lines[0] == "date,weekday,name,source"
        assert len(lines) == 18  # header + 17 holidays in the 2026 fixture
        assert lines[1].startswith("2026-01-01,Thursday,")
