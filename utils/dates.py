"""Date utilities shared by financial business rules."""

from __future__ import annotations

import calendar
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import TypeAlias


DateLike: TypeAlias = date | datetime | str


def parse_date(value: DateLike) -> date:
    """Return a date from a date/datetime, ISO string or ``DD/MM/YYYY`` string."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError as exc:
        raise ValueError(f"Data invalida: {value!r}") from exc


def days_in_month(year: int, month: int) -> int:
    """Return the number of days in a calendar month."""

    if not 1 <= month <= 12:
        raise ValueError("month deve estar entre 1 e 12.")
    return calendar.monthrange(year, month)[1]


def date_with_day(year: int, month: int, day: int) -> date:
    """Build a date, clamping the requested day to the end of the month."""

    if not 1 <= day <= 31:
        raise ValueError("day deve estar entre 1 e 31.")
    return date(year, month, min(day, days_in_month(year, month)))


def add_months(value: DateLike, months: int, *, preferred_day: int | None = None) -> date:
    """Add calendar months while preserving (and, when needed, clamping) the day."""

    original = parse_date(value)
    month_index = original.year * 12 + (original.month - 1) + months
    year, zero_based_month = divmod(month_index, 12)
    if not 1 <= year <= 9999:
        raise ValueError("Resultado fora do intervalo de datas suportado.")
    month = zero_based_month + 1
    day = original.day if preferred_day is None else preferred_day
    return date_with_day(year, month, day)


def add_years(value: DateLike, years: int) -> date:
    """Add calendar years, mapping leap day to the last day of February."""

    original = parse_date(value)
    return date_with_day(original.year + years, original.month, original.day)


def month_start(value: DateLike) -> date:
    parsed = parse_date(value)
    return parsed.replace(day=1)


def month_end(value: DateLike) -> date:
    parsed = parse_date(value)
    return parsed.replace(day=days_in_month(parsed.year, parsed.month))


def month_key(value: DateLike) -> str:
    """Return a stable ``YYYY-MM`` key."""

    return parse_date(value).strftime("%Y-%m")


def iter_month_starts(start: DateLike, end: DateLike) -> Iterator[date]:
    """Yield every month start in the inclusive interval."""

    current = month_start(start)
    limit = month_start(end)
    while current <= limit:
        yield current
        current = add_months(current, 1, preferred_day=1)


def format_brl_date(value: DateLike) -> str:
    return parse_date(value).strftime("%d/%m/%Y")


def inclusive_days(start: DateLike, end: DateLike) -> Iterator[date]:
    """Yield each day in an inclusive interval."""

    current = parse_date(start)
    limit = parse_date(end)
    if current > limit:
        raise ValueError("start deve ser anterior ou igual a end.")
    while current <= limit:
        yield current
        current += timedelta(days=1)


ensure_date = parse_date
