# hongkong_holiday

Hong Kong public holidays from official [GovHK open data](https://data.gov.hk/en-data/dataset/hk-effo-statistic-cal), with an algorithmic fallback for historical and far-future years.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)

## Why this package?

The official 1823 GovHK feed is authoritative — it reflects the actual gazetted
general holidays, including one-off substitutions — but it only covers roughly a
**two-year window** (the current year and the next). `hongkong_holiday` combines:

1. **Primary — GovHK API (cached in memory):** authoritative data from
   `https://www.1823.gov.hk/common/ical/{en,tc,sc}.json`, fetched lazily once
   per instance with retries.
2. **Fallback — algorithmic estimation:** for years outside the API window,
   dates are computed with the well-maintained
   [`holidays`](https://pypi.org/project/holidays/) package, and **every Sunday
   is treated as a general holiday** per Hong Kong's General Holidays Ordinance
   (Cap. 149).

Every result is tagged with its `source` (`"govhk"` or `"estimated"`) so you
always know whether you are looking at gazetted or computed data.

## Installation

```bash
pip install hongkong_holiday
```

## Quick start

```python
from hongkong_holiday import HKHolidays

hk = HKHolidays(lang="en")   # "en", "tc" (繁體) or "sc" (简体)

# Is a given date a holiday?
hk.is_holiday("2026-07-01")          # True  — HKSAR Establishment Day
hk.is_holiday("2026-07-05")          # True  — Sunday (general holiday)
hk.is_public_holiday("2026-07-05")   # False — plain Sunday, not gazetted
hk.holiday_name("2026-12-25")        # "Christmas Day"

# Historical year (outside the API window) — automatic fallback:
hk.is_public_holiday("2020-07-01")   # True, computed by the fallback provider

# Describe a single date (weekday: Sunday=0, Monday=1 ... Saturday=6)
info = hk.get_date("2026-07-05")
# DateInfo(date=datetime.date(2026, 7, 5), weekday=0,
#          is_holiday=True, holiday_name='Sunday')

# Describe every day of a year
for day in hk.get_dates(2026):
    print(day.date, day.weekday, day.is_holiday, day.holiday_name)

# List just the holidays of a year
for holiday in hk.get_holidays(2026):
    print(holiday.date, holiday.name, holiday.source)

# Next upcoming holiday
print(hk.next_holiday())             # e.g. 2026-09-26 The day following ...
```

### Counting Saturdays and Sundays as holidays

Every query method takes `include_sundays` / `include_saturdays` flags.
Sundays are general holidays under Hong Kong law, so `is_holiday`,
`holiday_name`, `get_date` and `get_dates` include them **by default**;
Saturdays are opt-in for organisations on a 5-day week:

```python
hk.is_holiday("2026-07-04")                            # False (a Saturday)
hk.is_holiday("2026-07-04", include_saturdays=True)    # True
hk.is_holiday("2026-07-05", include_sundays=False)     # False (named holidays only)

# Year listing with weekends included
hk.get_holidays(2026, include_sundays=True, include_saturdays=True)

# Full-year calendar treating Saturday + Sunday as non-working days
days_off = [d for d in hk.get_dates(2026, include_saturdays=True) if d.is_holiday]
```

### Export to CSV

```python
from hongkong_holiday import HKHolidays, export_csv

hk = HKHolidays(lang="tc")
export_csv(hk.get_holidays(2026), "hk_holidays_2026.csv")
# Written as UTF-8 with BOM so Chinese names open correctly in Excel.
```

## API overview

| Member | Description |
| --- | --- |
| `HKHolidays(lang="en", timeout=10.0, retries=3, use_fallback=True)` | Main entry point. |
| `is_holiday(date, include_sundays=True, include_saturdays=False)` | `True` for a general holiday — named holidays and (by default) Sundays. |
| `is_public_holiday(date, include_sundays=False, include_saturdays=False)` | `True` for gazetted/named holidays; weekends only when flagged. |
| `holiday_name(date, include_sundays=True, include_saturdays=False)` | Holiday name, `"Sunday"`/`"Saturday"` for flagged weekend days, else `None`. |
| `get_holiday(date, include_sundays=False, include_saturdays=False)` | The `Holiday` object on that date, or `None`. |
| `get_holidays(year, include_sundays=False, include_saturdays=False)` | Sorted list of `Holiday` objects for a year. |
| `get_date(date, include_sundays=True, include_saturdays=False)` | A `DateInfo` — date, weekday (Sun=0, Mon=1 … Sat=6), is_holiday, holiday_name. |
| `get_dates(year, include_sundays=True, include_saturdays=False)` | A `DateInfo` for **every** day of the year, in order. |
| `next_holiday(date=None, include_sundays=False, include_saturdays=False)` | Next holiday after the given date (default today). |
| `api_years` | Years currently covered by the live GovHK feed. |
| `refresh()` | Discard the in-memory cache and re-fetch on next query. |
| `export_csv(holidays, path)` | Write holidays to a CSV file. |
| `weekday_number(date)` | Sunday-first weekday number: Sunday=0, Monday=1 … Saturday=6. |

`date` arguments accept `datetime.date`, `datetime.datetime`, ISO strings
(`"2026-07-01"`) and compact iCal strings (`"20260701"`).

> **Note on weekday numbering:** `DateInfo.weekday` and `weekday_number()`
> use Sunday=0, Monday=1 … Saturday=6 — this differs from Python's
> `date.weekday()` (Monday=0) and `date.isoweekday()` (Monday=1, Sunday=7).

### Behaviour details

- **Caching:** the feed is downloaded at most once per `HKHolidays` instance
  and kept in memory. Long-running services should call `refresh()`
  periodically (e.g. daily) to pick up newly gazetted holidays.
- **Offline resilience:** if the feed cannot be reached, the module logs a
  warning and serves *all* years from the fallback provider instead of
  failing (set `use_fallback=False` to fail loudly instead).
- **Estimated data caveat:** lunar-calendar holidays and one-off government
  substitutions in `"estimated"` results may differ from what is eventually
  gazetted. Treat far-future estimates as provisional.

## Development

```bash
git clone https://github.com/funglkfcc/hongkong_holiday
cd hongkong_holiday
pip install -e .[dev]
pytest
```

The test suite is fully offline — the GovHK feed is mocked.

## Publishing to PyPI

```bash
pip install build twine
python -m build
twine upload dist/*
```

## License

[MIT](LICENSE). Holiday data © HKSAR Government, provided via
[DATA.GOV.HK](https://data.gov.hk/) under its terms of use.
