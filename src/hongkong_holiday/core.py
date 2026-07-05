"""Core logic for hongkong_holiday.

Fetches Hong Kong general (public) holidays from the GovHK 1823 open data
feed, caches them in memory, and falls back to algorithmic estimation (the
``holidays`` package plus the Sundays-are-general-holidays rule) for years
outside the API's roughly two-year window.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple, Union

from .utils import ensure_date, parse_ical_date, weekday_number

logger = logging.getLogger(__name__)

DateLike = Union[str, _dt.date, _dt.datetime]

#: Feed URLs published by the 1823 Contact Centre, HKSARG.
API_URLS = {
    "en": "https://www.1823.gov.hk/common/ical/en.json",
    "tc": "https://www.1823.gov.hk/common/ical/tc.json",
    "sc": "https://www.1823.gov.hk/common/ical/sc.json",
}

SOURCE_GOVHK = "govhk"
SOURCE_ESTIMATED = "estimated"

# Language codes understood by the `holidays` fallback package.
_FALLBACK_LANGUAGES = {"en": "en_HK", "tc": "zh_HK", "sc": "zh_CN"}

_USER_AGENT = "hongkong_holiday/1.0 (+https://pypi.org/project/hongkong_holiday/)"

# Hong Kong gazettes 17 general holidays per year. A feed year with far
# fewer events is a partial spillover (e.g. only 1 Jan of the year after
# the window) and must not be treated as authoritative.
_MIN_EVENTS_FULL_YEAR = 10

_SATURDAY = 5  # datetime.date.weekday() values (Monday=0)
_SUNDAY = 6


@dataclass(frozen=True)
class Holiday:
    """A single Hong Kong holiday."""

    date: _dt.date
    name: str
    source: str  # SOURCE_GOVHK or SOURCE_ESTIMATED

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"{self.date.isoformat()} {self.name} [{self.source}]"


@dataclass(frozen=True)
class DateInfo:
    """Full description of a single calendar date.

    ``weekday`` uses the Sunday-first convention: Sunday is ``0``,
    Monday is ``1`` ... Saturday is ``6``.
    """

    date: _dt.date
    weekday: int
    is_holiday: bool
    holiday_name: Optional[str]

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        label = self.holiday_name or ("holiday" if self.is_holiday else "working day")
        return f"{self.date.isoformat()} (weekday={self.weekday}) {label}"


class HKHolidaysError(Exception):
    """Raised when holiday data cannot be obtained from any provider."""


class HKHolidays:
    """Hong Kong public holiday checker.

    Parameters
    ----------
    lang:
        Feed language: ``"en"`` (English), ``"tc"`` (Traditional Chinese)
        or ``"sc"`` (Simplified Chinese).
    timeout:
        Per-request HTTP timeout in seconds.
    retries:
        Number of HTTP attempts before giving up on the API.
    use_fallback:
        If ``True`` (default), years outside the API window are estimated
        with the ``holidays`` package. If ``False``, such queries raise
        :class:`HKHolidaysError`.

    The GovHK feed is fetched lazily on first query and cached in memory
    for the lifetime of the instance; call :meth:`refresh` to re-fetch.

    All query methods accept ``include_sundays`` / ``include_saturdays``
    flags controlling whether plain Sundays and Saturdays count as
    holidays. Sundays are general holidays under Hong Kong's General
    Holidays Ordinance (Cap. 149); Saturdays are not, but many
    organisations treat them as non-working days.
    """

    def __init__(
        self,
        lang: str = "en",
        timeout: float = 10.0,
        retries: int = 3,
        use_fallback: bool = True,
    ) -> None:
        if lang not in API_URLS:
            raise ValueError(f"lang must be one of {sorted(API_URLS)}, got {lang!r}")
        self.lang = lang
        self.timeout = timeout
        self.retries = max(1, retries)
        self.use_fallback = use_fallback

        self._api_holidays: Dict[_dt.date, Holiday] = {}
        self._api_years: set[int] = set()
        self._fetched = False
        self._fetch_failed = False

    # ------------------------------------------------------------------
    # Fetching / caching
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Force a re-fetch of the GovHK feed on the next query."""
        self._api_holidays.clear()
        self._api_years.clear()
        self._fetched = False
        self._fetch_failed = False

    @property
    def api_years(self) -> List[int]:
        """Years covered by the live GovHK feed (empty until first fetch)."""
        self._ensure_fetched()
        return sorted(self._api_years)

    def _ensure_fetched(self) -> None:
        if self._fetched or self._fetch_failed:
            return
        try:
            payload = self._download(API_URLS[self.lang])
            self._api_holidays = self._parse_feed(payload)
            counts: Dict[int, int] = {}
            for day in self._api_holidays:
                counts[day.year] = counts.get(day.year, 0) + 1
            self._api_years = {
                year for year, n in counts.items() if n >= _MIN_EVENTS_FULL_YEAR
            }
            self._fetched = True
            logger.info(
                "Loaded %d holidays from GovHK for years %s",
                len(self._api_holidays),
                sorted(self._api_years),
            )
        except Exception as exc:
            self._fetch_failed = True
            if not self.use_fallback:
                raise HKHolidaysError(
                    f"Could not fetch GovHK holiday feed: {exc}"
                ) from exc
            logger.warning(
                "GovHK feed unavailable (%s); using estimated holidays.", exc
            )

    def _download(self, url: str) -> dict:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    # The feed is served with a UTF-8 BOM.
                    return json.loads(response.read().decode("utf-8-sig"))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(0.5 * attempt)
        raise HKHolidaysError(f"Failed to download {url}: {last_error}") from last_error

    @staticmethod
    def _parse_feed(payload: dict) -> Dict[_dt.date, Holiday]:
        holidays_by_date: Dict[_dt.date, Holiday] = {}
        calendars = payload.get("vcalendar") or []
        for calendar in calendars:
            for event in calendar.get("vevent") or []:
                dtstart = event.get("dtstart")
                # dtstart is ["YYYYMMDD", {"value": "DATE"}]
                if isinstance(dtstart, (list, tuple)) and dtstart:
                    raw = dtstart[0]
                else:
                    raw = dtstart
                try:
                    day = parse_ical_date(raw)
                except (TypeError, ValueError):
                    logger.debug("Skipping unparseable vevent: %r", event)
                    continue
                name = str(event.get("summary", "")).strip() or "Public Holiday"
                holidays_by_date[day] = Holiday(day, name, SOURCE_GOVHK)
        if not holidays_by_date:
            raise HKHolidaysError("GovHK feed contained no holiday events")
        return holidays_by_date

    # ------------------------------------------------------------------
    # Fallback estimation
    # ------------------------------------------------------------------
    def _fallback_holidays(self, year: int) -> Dict[_dt.date, Holiday]:
        try:
            import holidays as holidays_lib
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise HKHolidaysError(
                "Year outside the GovHK API window and the 'holidays' package "
                "is not installed. Install it with: pip install holidays"
            ) from exc

        language = _FALLBACK_LANGUAGES.get(self.lang)
        try:
            provider = holidays_lib.country_holidays(
                "HK", years=year, language=language
            )
        except Exception:
            # Older `holidays` releases may not accept this language code.
            provider = holidays_lib.country_holidays("HK", years=year)

        return {
            day: Holiday(day, str(name), SOURCE_ESTIMATED)
            for day, name in sorted(provider.items())
            if day.year == year
        }

    def _holidays_for_year(self, year: int) -> Dict[_dt.date, Holiday]:
        self._ensure_fetched()
        if year in self._api_years:
            return {
                day: hol
                for day, hol in self._api_holidays.items()
                if day.year == year
            }
        if not self.use_fallback:
            raise HKHolidaysError(
                f"Year {year} is outside the GovHK API window "
                f"({sorted(self._api_years) or 'feed unavailable'}) and "
                "fallback estimation is disabled."
            )
        return self._fallback_holidays(year)

    def _source_for_year(self, year: int) -> str:
        return SOURCE_GOVHK if year in self._api_years else SOURCE_ESTIMATED

    # ------------------------------------------------------------------
    # Public query interface
    # ------------------------------------------------------------------
    def get_holidays(
        self,
        year: int,
        include_sundays: bool = False,
        include_saturdays: bool = False,
    ) -> List[Holiday]:
        """Return the holidays for ``year``, sorted by date.

        With ``include_sundays=True`` every Sunday of the year is added as
        a general holiday (per Cap. 149); with ``include_saturdays=True``
        every Saturday is added too. Dates that already carry a named
        holiday keep their name.
        """
        result = dict(self._holidays_for_year(year))
        source = self._source_for_year(year)
        weekend: List[Tuple[int, str]] = []
        if include_sundays:
            weekend.append((_SUNDAY, "Sunday"))
        if include_saturdays:
            weekend.append((_SATURDAY, "Saturday"))
        for weekday, label in weekend:
            for day in _weekdays_of_year(year, weekday):
                result.setdefault(day, Holiday(day, label, source))
        return [result[day] for day in sorted(result)]

    def get_holiday(
        self,
        date: DateLike,
        include_sundays: bool = False,
        include_saturdays: bool = False,
    ) -> Optional[Holiday]:
        """Return the :class:`Holiday` on ``date``, or ``None``.

        Named holidays always win; plain Sundays/Saturdays are only
        reported when the corresponding flag is set.
        """
        day = ensure_date(date)
        holiday = self._holidays_for_year(day.year).get(day)
        if holiday is not None:
            return holiday
        if include_sundays and day.weekday() == _SUNDAY:
            return Holiday(day, "Sunday", self._source_for_year(day.year))
        if include_saturdays and day.weekday() == _SATURDAY:
            return Holiday(day, "Saturday", self._source_for_year(day.year))
        return None

    def is_public_holiday(
        self,
        date: DateLike,
        include_sundays: bool = False,
        include_saturdays: bool = False,
    ) -> bool:
        """True if ``date`` is a gazetted public holiday.

        By default plain Sundays and Saturdays are excluded (unless the
        day itself carries a named holiday); set the flags to count them.
        """
        return self.get_holiday(date, include_sundays, include_saturdays) is not None

    def is_holiday(
        self,
        date: DateLike,
        include_sundays: bool = True,
        include_saturdays: bool = False,
    ) -> bool:
        """True if ``date`` is a general holiday.

        Defaults follow Hong Kong law: any Sunday or gazetted public
        holiday counts. Set ``include_saturdays=True`` to also treat
        Saturdays as holidays, or ``include_sundays=False`` to check
        named holidays only.
        """
        return self.get_holiday(date, include_sundays, include_saturdays) is not None

    def holiday_name(
        self,
        date: DateLike,
        include_sundays: bool = True,
        include_saturdays: bool = False,
    ) -> Optional[str]:
        """The holiday name for ``date``, or ``None`` if it is a working day.

        Plain Sundays/Saturdays are reported as ``"Sunday"``/``"Saturday"``
        when the corresponding flag is set.
        """
        holiday = self.get_holiday(date, include_sundays, include_saturdays)
        return holiday.name if holiday is not None else None

    def get_date(
        self,
        date: DateLike,
        include_sundays: bool = True,
        include_saturdays: bool = False,
    ) -> DateInfo:
        """Describe a single date: date, weekday, is_holiday, holiday_name.

        ``weekday`` is Sunday-first: Sunday ``0``, Monday ``1`` ...
        Saturday ``6``. The flags control whether plain Sundays/Saturdays
        count as holidays (named holidays always do).
        """
        day = ensure_date(date)
        holiday = self.get_holiday(day, include_sundays, include_saturdays)
        return DateInfo(
            date=day,
            weekday=weekday_number(day),
            is_holiday=holiday is not None,
            holiday_name=holiday.name if holiday is not None else None,
        )

    def get_dates(
        self,
        year: int,
        include_sundays: bool = True,
        include_saturdays: bool = False,
    ) -> List[DateInfo]:
        """Return a :class:`DateInfo` for every day of ``year``, in order."""
        named = self._holidays_for_year(year)
        infos: List[DateInfo] = []
        day = _dt.date(year, 1, 1)
        one_day = _dt.timedelta(days=1)
        while day.year == year:
            holiday = named.get(day)
            name: Optional[str] = holiday.name if holiday is not None else None
            if name is None:
                if include_sundays and day.weekday() == _SUNDAY:
                    name = "Sunday"
                elif include_saturdays and day.weekday() == _SATURDAY:
                    name = "Saturday"
            infos.append(
                DateInfo(
                    date=day,
                    weekday=weekday_number(day),
                    is_holiday=name is not None,
                    holiday_name=name,
                )
            )
            day += one_day
        return infos

    def next_holiday(
        self,
        date: Optional[DateLike] = None,
        include_sundays: bool = False,
        include_saturdays: bool = False,
    ) -> Holiday:
        """The next holiday strictly after ``date`` (default: today).

        By default only named public holidays are considered; set the
        flags to let plain Sundays/Saturdays qualify too.
        """
        day = ensure_date(date) if date is not None else _dt.date.today()
        for year in (day.year, day.year + 1):
            for holiday in self.get_holidays(year, include_sundays, include_saturdays):
                if holiday.date > day:
                    return holiday
        raise HKHolidaysError(f"No holiday found after {day.isoformat()}")


def _weekdays_of_year(year: int, weekday: int) -> Iterable[_dt.date]:
    """All dates in ``year`` falling on ``weekday`` (datetime convention,
    Monday=0 ... Sunday=6)."""
    day = _dt.date(year, 1, 1)
    day += _dt.timedelta(days=(weekday - day.weekday()) % 7)
    one_week = _dt.timedelta(weeks=1)
    while day.year == year:
        yield day
        day += one_week
