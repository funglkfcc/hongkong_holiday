"""hongkong_holiday - Hong Kong public holidays from GovHK open data.

Quick start::

    from hongkong_holiday import HKHolidays

    hk = HKHolidays(lang="en")
    hk.is_holiday("2026-07-01")        # True (HKSAR Establishment Day)
    hk.get_date("2026-07-05")          # DateInfo(weekday=0, is_holiday=True, ...)
    hk.get_holidays(2026)              # list of Holiday objects
"""

from .core import (
    API_URLS,
    SOURCE_ESTIMATED,
    SOURCE_GOVHK,
    DateInfo,
    HKHolidays,
    HKHolidaysError,
    Holiday,
)
from .utils import ensure_date, export_csv, parse_ical_date, weekday_number

__version__ = "1.0.1"

__all__ = [
    "HKHolidays",
    "HKHolidaysError",
    "Holiday",
    "DateInfo",
    "API_URLS",
    "SOURCE_GOVHK",
    "SOURCE_ESTIMATED",
    "ensure_date",
    "export_csv",
    "parse_ical_date",
    "weekday_number",
    "__version__",
]
