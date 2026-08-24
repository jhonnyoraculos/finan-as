"""Pure generation of recurring financial occurrences with deduplication."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Hashable, Literal

from utils.currency import ZERO, parse_brl_currency
from utils.dates import DateLike, add_months, date_with_day, parse_date
from utils.helpers import as_bool, get_value, normalize_token


Frequency = Literal["daily", "weekly", "monthly", "yearly"]
FREQUENCY_ALIASES: dict[str, Frequency] = {
    "daily": "daily",
    "diaria": "daily",
    "diario": "daily",
    "weekly": "weekly",
    "semanal": "weekly",
    "monthly": "monthly",
    "mensal": "monthly",
    "yearly": "yearly",
    "annual": "yearly",
    "anual": "yearly",
}


@dataclass(frozen=True, slots=True)
class RecurrenceRule:
    start_date: date
    frequency: Frequency
    amount: Decimal
    description: str
    recurrence_id: Hashable | None = None
    interval: int = 1
    end_date: date | None = None
    transaction_type: str = "despesa"
    account_id: Hashable | None = None
    category_id: Hashable | None = None
    payment_method: str | None = None
    credit_card_id: Hashable | None = None
    active: bool = True


@dataclass(frozen=True, slots=True)
class RecurrenceOccurrence:
    recurrence_id: Hashable | None
    recurrence_key: str
    occurrence_date: date
    amount: Decimal
    description: str
    sequence: int
    frequency: Frequency
    transaction_type: str
    account_id: Hashable | None = None
    category_id: Hashable | None = None
    payment_method: str | None = None
    credit_card_id: Hashable | None = None

    @property
    def due_date(self) -> date:
        return self.occurrence_date

    @property
    def deduplication_key(self) -> tuple[str, date]:
        return self.recurrence_key, self.occurrence_date

    @property
    def persistence_key(self) -> str:
        """Unique key suitable for the database ``bills.recurrence_key`` field."""

        return f"{self.recurrence_key}:{self.occurrence_date.isoformat()}"


def normalize_recurrence_rule(rule: RecurrenceRule | Mapping[str, Any] | Any) -> RecurrenceRule:
    """Convert a dict/ORM-like rule to the service's immutable representation."""

    if isinstance(rule, RecurrenceRule):
        return rule
    start = get_value(
        rule,
        "start_date",
        "data_inicio",
        "next_date",
        "proxima_data",
        "next_due_date",
        "due_date",
        "data_vencimento",
    )
    if start is None:
        raise ValueError("Regra recorrente sem data inicial.")
    frequency = normalize_frequency(
        get_value(rule, "frequency", "frequencia", default="monthly")
    )
    interval = int(get_value(rule, "interval", "intervalo", default=1))
    if interval < 1:
        raise ValueError("O intervalo da recorrencia deve ser maior que zero.")
    end = get_value(rule, "end_date", "data_fim", "until", "ate")
    return RecurrenceRule(
        recurrence_id=get_value(
            rule,
            "recurrence_id",
            "id",
            "recurring_transaction_id",
            "regra_id",
        ),
        start_date=parse_date(start),
        frequency=frequency,
        interval=interval,
        end_date=parse_date(end) if end is not None else None,
        amount=parse_brl_currency(get_value(rule, "amount", "value", "valor", default=ZERO)),
        description=str(get_value(rule, "description", "descricao", default="Recorrencia")),
        transaction_type=str(
            get_value(rule, "transaction_type", "type", "tipo", default="despesa")
        ),
        account_id=get_value(rule, "account_id", "conta_id"),
        category_id=get_value(rule, "category_id", "categoria_id"),
        payment_method=get_value(rule, "payment_method", "forma_pagamento"),
        credit_card_id=get_value(rule, "credit_card_id", "cartao_id"),
        active=as_bool(
            get_value(rule, "is_active", "active", "ativo", default=True), default=True
        ),
    )


def normalize_frequency(value: Any) -> Frequency:
    token = normalize_token(value)
    try:
        return FREQUENCY_ALIASES[token]
    except KeyError as exc:
        raise ValueError(f"Frequencia nao suportada: {value!r}") from exc


def generate_recurrence_dates(
    start_date: DateLike,
    end_date: DateLike,
    frequency: str,
    *,
    interval: int = 1,
    range_start: DateLike | None = None,
) -> tuple[date, ...]:
    """Generate recurrence dates in an inclusive window without month-day drift."""

    if interval < 1:
        raise ValueError("interval deve ser maior que zero.")
    anchor = parse_date(start_date)
    limit = parse_date(end_date)
    lower = parse_date(range_start) if range_start is not None else anchor
    if lower > limit:
        return ()
    normalized_frequency = normalize_frequency(frequency)

    dates: list[date] = []
    index = 0
    while True:
        occurrence = _occurrence_at(anchor, normalized_frequency, interval, index)
        if occurrence > limit:
            break
        if occurrence >= lower:
            dates.append(occurrence)
        index += 1
        if index > 1_000_000:
            raise OverflowError("Janela de recorrencia excessivamente grande.")
    return tuple(dates)


def generate_recurrence_occurrences(
    rule: RecurrenceRule | Mapping[str, Any] | Any,
    range_start: DateLike,
    range_end: DateLike,
    *,
    existing_occurrences: Iterable[Any] = (),
) -> tuple[RecurrenceOccurrence, ...]:
    """Generate only missing occurrences for one rule.

    Existing values may be occurrence objects, dicts/ORM instances, raw dates or
    ``(recurrence_id, date)`` tuples. No database mutation happens here.
    """

    normalized = normalize_recurrence_rule(rule)
    if not normalized.active:
        return ()
    lower = parse_date(range_start)
    upper = parse_date(range_end)
    if lower > upper:
        raise ValueError("range_start deve ser anterior ou igual a range_end.")
    if normalized.end_date is not None:
        upper = min(upper, normalized.end_date)
    if upper < normalized.start_date:
        return ()

    recurrence_key = _rule_key(normalized)
    existing_keys, wildcard_dates = _existing_keys(existing_occurrences)
    dates = generate_recurrence_dates(
        normalized.start_date,
        upper,
        normalized.frequency,
        interval=normalized.interval,
        range_start=lower,
    )

    result: list[RecurrenceOccurrence] = []
    for occurrence_date in dates:
        if occurrence_date in wildcard_dates or (recurrence_key, occurrence_date) in existing_keys:
            continue
        sequence = _sequence_for_date(normalized, occurrence_date)
        result.append(
            RecurrenceOccurrence(
                recurrence_id=normalized.recurrence_id,
                recurrence_key=recurrence_key,
                occurrence_date=occurrence_date,
                amount=normalized.amount,
                description=normalized.description,
                sequence=sequence,
                frequency=normalized.frequency,
                transaction_type=normalized.transaction_type,
                account_id=normalized.account_id,
                category_id=normalized.category_id,
                payment_method=normalized.payment_method,
                credit_card_id=normalized.credit_card_id,
            )
        )
    return tuple(result)


def next_recurrence_date(rule: RecurrenceRule | Mapping[str, Any] | Any, after: DateLike) -> date | None:
    """Return the first occurrence strictly after a reference date."""

    normalized = normalize_recurrence_rule(rule)
    if not normalized.active:
        return None
    reference = parse_date(after)
    index = 0
    while True:
        occurrence = _occurrence_at(
            normalized.start_date,
            normalized.frequency,
            normalized.interval,
            index,
        )
        if normalized.end_date is not None and occurrence > normalized.end_date:
            return None
        if occurrence > reference:
            return occurrence
        index += 1


def _occurrence_at(anchor: date, frequency: Frequency, interval: int, index: int) -> date:
    step = interval * index
    if frequency == "daily":
        return anchor + timedelta(days=step)
    if frequency == "weekly":
        return anchor + timedelta(weeks=step)
    if frequency == "monthly":
        return add_months(anchor, step, preferred_day=anchor.day)
    target_year = anchor.year + step
    return date_with_day(target_year, anchor.month, anchor.day)


def _sequence_for_date(rule: RecurrenceRule, target: date) -> int:
    if rule.frequency == "daily":
        units = (target - rule.start_date).days
    elif rule.frequency == "weekly":
        units = (target - rule.start_date).days // 7
    elif rule.frequency == "monthly":
        units = (target.year - rule.start_date.year) * 12 + target.month - rule.start_date.month
    else:
        units = target.year - rule.start_date.year
    return units // rule.interval + 1


def _rule_key(rule: RecurrenceRule) -> str:
    if rule.recurrence_id is not None:
        return str(rule.recurrence_id)
    description = normalize_token(rule.description)
    return f"{description}|{rule.start_date.isoformat()}|{rule.frequency}|{rule.interval}"


def _existing_keys(existing: Iterable[Any]) -> tuple[set[tuple[str, date]], set[date]]:
    keys: set[tuple[str, date]] = set()
    wildcard_dates: set[date] = set()
    for item in existing:
        if isinstance(item, (date, str)):
            try:
                wildcard_dates.add(parse_date(item))
                continue
            except ValueError:
                if isinstance(item, str) and ":" in item:
                    possible_rule, possible_date = item.rsplit(":", 1)
                    try:
                        keys.add((possible_rule, parse_date(possible_date)))
                        continue
                    except ValueError:
                        pass
        if isinstance(item, tuple) and len(item) == 2:
            recurrence_id, raw_date = item
            keys.add((str(recurrence_id), parse_date(raw_date)))
            continue
        raw_date = get_value(
            item,
            "occurrence_date",
            "due_date",
            "data_vencimento",
            "date",
            "data",
        )
        if raw_date is None:
            continue
        recurrence_id = get_value(
            item,
            "recurrence_id",
            "recurring_transaction_id",
            "regra_id",
        )
        parsed = parse_date(raw_date)
        if recurrence_id is not None:
            keys.add((str(recurrence_id), parsed))
            continue
        persisted_key = get_value(item, "recurrence_key")
        if persisted_key is not None:
            suffix = f":{parsed.isoformat()}"
            key_text = str(persisted_key)
            rule_key = key_text[: -len(suffix)] if key_text.endswith(suffix) else key_text
            keys.add((rule_key, parsed))
        else:
            wildcard_dates.add(parsed)
    return keys, wildcard_dates


# Short alias suitable for scheduled jobs.
generate_occurrences = generate_recurrence_occurrences
