"""Helper functions for hongkong_holiday: date parsing and CSV export."""

from __future__ import annotations

import csv
import datetime as _dt
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Union

if TYPE_CHECKING:  # pragma: no cover - import cycle guard for type checkers
    from .core import Holiday


def parse_ical_date(value: str) -> _dt.date:
    """Parse an iCal DATE value (``YYYYMMDD``) into a :class:`datetime.date`."""
    if not isinstance(value, str):
        raise TypeError(f"Expected iCal date string, got {type(value).__name__}")
    return _dt.datetime.strptime(value.strip(), "%Y%m%d").date()


def ensure_date(value: Union[str, _dt.date, _dt.datetime]) -> _dt.date:
    """Coerce a date-like value into a :class:`datetime.date`.

    Accepts ``date``, ``datetime``, ISO strings (``2026-07-01``) and
    compact iCal strings (``20260701``).
    """
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if len(text) == 8 and text.isdigit():
            return parse_ical_date(text)
        return _dt.date.fromisoformat(text)
    raise TypeError(f"Cannot interpret {value!r} as a date")


def weekday_number(value: Union[str, _dt.date, _dt.datetime]) -> int:
    """Weekday of a date using the Sunday-first convention.

    Sunday is ``0``, Monday is ``1`` ... Saturday is ``6`` — unlike
    Python's :meth:`datetime.date.weekday` (Monday=0) and
    :meth:`~datetime.date.isoweekday` (Monday=1, Sunday=7).
    """
    day = ensure_date(value)
    return (day.weekday() + 1) % 7


def export_csv(
    holidays: Iterable["Holiday"],
    path: Union[str, Path],
    encoding: str = "utf-8-sig",
) -> Path:
    """Write holidays to a CSV file with columns date, weekday, name, source.

    The default ``utf-8-sig`` encoding keeps Chinese holiday names readable
    when the file is opened in Microsoft Excel. Returns the written path.
    """
    target = Path(path)
    with target.open("w", newline="", encoding=encoding) as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "weekday", "name", "source"])
        for holiday in holidays:
            writer.writerow(
                [
                    holiday.date.isoformat(),
                    holiday.date.strftime("%A"),
                    holiday.name,
                    holiday.source,
                ]
            )
    return target
