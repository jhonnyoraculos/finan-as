"""Deterministic cash-balance forecasting from explicit future events."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Hashable

from services.finance_service import (
    CANCELLED_STATUSES,
    EXPENSE_TYPES,
    INCOME_TYPES,
    TRANSFER_TYPES,
    transfer_effect,
)
from utils.currency import MoneyLike, ZERO, parse_brl_currency
from utils.dates import DateLike, add_months, month_end, parse_date
from utils.helpers import as_bool, get_value, normalize_token


FORECAST_INCOME_TYPES = INCOME_TYPES | {
    "future_income",
    "receita_futura",
    "salary",
    "salario",
    "refund",
    "reembolso",
}
FORECAST_EXPENSE_TYPES = EXPENSE_TYPES | {
    "bill",
    "boleto",
    "invoice",
    "fatura",
    "installment",
    "parcela",
    "subscription",
    "assinatura",
    "recurring_expense",
    "despesa_recorrente",
    "conta",
    "liability",
    "loan",
    "emprestimo",
}
OUTSTANDING_STATUSES = {
    "pending",
    "pendente",
    "open",
    "aberto",
    "aberta",
    "closed",
    "fechado",
    "fechada",
    "overdue",
    "atrasado",
    "atrasada",
    "unpaid",
    "posted",
}


@dataclass(frozen=True, slots=True)
class ForecastEvent:
    event_date: date
    signed_amount: Decimal
    kind: str
    description: str = ""
    event_id: Hashable | None = None
    source: str | None = None
    outstanding: bool = False

    @property
    def inflow(self) -> Decimal:
        return self.signed_amount if self.signed_amount > ZERO else ZERO

    @property
    def outflow(self) -> Decimal:
        return abs(self.signed_amount) if self.signed_amount < ZERO else ZERO


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    point_date: date
    balance: Decimal
    inflows: Decimal = ZERO
    outflows: Decimal = ZERO
    net_change: Decimal = ZERO


def normalize_forecast_event(
    event: Any,
    *,
    default_kind: str | None = None,
    source: str | None = None,
    account_id: Hashable | None = None,
) -> ForecastEvent | None:
    """Convert a dict/ORM-like future item to a signed forecast event."""

    if isinstance(event, ForecastEvent):
        return event
    if get_value(event, "deleted_at", "excluido_em") is not None:
        return None
    if not as_bool(
        get_value(event, "is_active", "active", "ativo", default=True), default=True
    ):
        return None
    if not as_bool(get_value(event, "affects_cash", "afeta_saldo", default=True), default=True):
        return None
    status = normalize_token(get_value(event, "status", default=""))
    if status in CANCELLED_STATUSES or status in {"paid", "pago", "paga"}:
        return None

    raw_date = get_value(
        event,
        "event_date",
        "due_date",
        "data_vencimento",
        "vencimento",
        "payment_date",
        "data_pagamento",
        "competence_date",
        "data_competencia",
        "occurrence_date",
        "next_charge_date",
        "next_run_date",
        "transaction_date",
        "transfer_date",
        "date",
        "data",
    )
    if raw_date is None:
        raise ValueError("Evento de previsao sem data.")

    kind = normalize_token(
        get_value(event, "kind", "transaction_type", "type", "tipo", default=default_kind or "")
    )
    if not kind and (
        get_value(event, "source_account_id", "conta_origem_id") is not None
        or get_value(event, "destination_account_id", "conta_destino_id") is not None
    ):
        kind = "transferencia"
    if not kind:
        class_kind = normalize_token(type(event).__name__)
        inferred = {
            "bill": "bill",
            "installment": "installment",
            "credit_card_invoice": "invoice",
            "subscription": "subscription",
            "recurrence_occurrence": "despesa_recorrente",
        }
        kind = inferred.get(class_kind, kind)
    explicit_effect = get_value(event, "signed_amount", "cash_effect", "impacto_saldo")
    if kind in TRANSFER_TYPES:
        signed_amount = transfer_effect(event, account_id=account_id)
    elif explicit_effect is not None:
        signed_amount = parse_brl_currency(explicit_effect)
    else:
        raw_amount = get_value(
            event,
            "amount",
            "total_amount",
            "value",
            "valor",
            "total",
            default=ZERO,
        )
        amount = abs(parse_brl_currency(raw_amount))
        if kind in FORECAST_INCOME_TYPES:
            signed_amount = amount
        elif kind in FORECAST_EXPENSE_TYPES:
            signed_amount = -amount
        else:
            direction = normalize_token(get_value(event, "direction", "direcao", default=""))
            if direction in {"entrada", "in", "income", "receita"}:
                signed_amount = amount
            elif direction in {"saida", "out", "expense", "despesa"}:
                signed_amount = -amount
            else:
                raise ValueError(f"Tipo de evento de previsao desconhecido: {kind!r}")

    return ForecastEvent(
        event_id=get_value(event, "event_id", "id"),
        event_date=parse_date(raw_date),
        signed_amount=parse_brl_currency(signed_amount),
        kind=kind or normalize_token(default_kind) or "evento",
        description=str(get_value(event, "description", "descricao", "name", "nome", default="")),
        source=source or get_value(event, "source", "origem"),
        outstanding=status in OUTSTANDING_STATUSES,
    )


def build_forecast_events(
    *event_groups: Iterable[Any],
    account_id: Hashable | None = None,
) -> tuple[ForecastEvent, ...]:
    """Normalize and deduplicate arbitrary collections of future events."""

    result: list[ForecastEvent] = []
    seen: set[tuple[str, str]] = set()
    for group in event_groups:
        for raw_event in group:
            event = normalize_forecast_event(raw_event, account_id=account_id)
            if event is None or event.signed_amount == ZERO:
                continue
            if event.event_id is not None:
                key = (event.source or event.kind, str(event.event_id))
                if key in seen:
                    continue
                seen.add(key)
            result.append(event)
    return tuple(sorted(result, key=lambda item: item.event_date))


def build_financial_forecast_events(
    *,
    future_incomes: Iterable[Any] = (),
    bills: Iterable[Any] = (),
    installments: Iterable[Any] = (),
    invoices: Iterable[Any] = (),
    recurring: Iterable[Any] = (),
    subscriptions: Iterable[Any] = (),
    account_id: Hashable | None = None,
) -> tuple[ForecastEvent, ...]:
    """Build forecast events from the main financial source collections."""

    income_items = tuple(future_incomes)
    bill_items = tuple(bills)
    installment_items = tuple(installments)
    invoice_items = tuple(invoices)
    recurring_items = tuple(recurring)
    subscription_items = tuple(subscriptions)

    # An invoice total already contains its linked installments. Keeping both
    # would charge the same obligation twice in the forecast.
    included_invoice_ids = {
        str(invoice_id)
        for invoice in invoice_items
        if (invoice_id := get_value(invoice, "id", "invoice_id")) is not None
    }
    unbilled_installments = tuple(
        item
        for item in installment_items
        if (
            (linked_invoice := get_value(item, "invoice_id", "credit_card_invoice_id"))
            is None
            or str(linked_invoice) not in included_invoice_ids
        )
    )

    configured_groups = (
        (income_items, "receita", "future_income"),
        (bill_items, "bill", "bill"),
        (unbilled_installments, "installment", "installment"),
        (invoice_items, "invoice", "invoice"),
        (recurring_items, "despesa_recorrente", "recurring"),
        (subscription_items, "subscription", "subscription"),
    )
    events: list[ForecastEvent] = []
    for group, default_kind, source in configured_groups:
        for item in group:
            normalized = normalize_forecast_event(
                item,
                default_kind=default_kind,
                source=source,
                account_id=account_id,
            )
            if normalized is not None and normalized.signed_amount != ZERO:
                events.append(normalized)

    # IDs from different sources are independent; duplicates inside a source are not.
    seen: set[tuple[str, str]] = set()
    unique: list[ForecastEvent] = []
    for event in sorted(events, key=lambda item: item.event_date):
        if event.event_id is None:
            unique.append(event)
            continue
        key = (event.source or event.kind, str(event.event_id))
        if key not in seen:
            seen.add(key)
            unique.append(event)
    return tuple(unique)


def forecast_balance_at(
    current_balance: MoneyLike,
    events: Iterable[Any],
    target_date: DateLike,
    *,
    as_of: DateLike | None = None,
    account_id: Hashable | None = None,
) -> Decimal:
    """Return projected balance at a target date.

    The current balance is assumed to already include all movements through
    ``as_of``, therefore only events strictly after it are added.
    """

    reference = parse_date(as_of or date.today())
    target = parse_date(target_date)
    if target < reference:
        raise ValueError("target_date nao pode ser anterior a as_of.")
    balance = parse_brl_currency(current_balance)
    for raw_event in events:
        event = normalize_forecast_event(raw_event, account_id=account_id)
        if event is not None and (
            reference < event.event_date <= target
            or (
                target > reference
                and event.outstanding
                and event.event_date <= reference
            )
        ):
            balance += event.signed_amount
    return parse_brl_currency(balance)


def project_balance(
    current_balance: MoneyLike,
    events: Iterable[Any],
    *,
    as_of: DateLike | None = None,
    horizon_months: int = 3,
    account_id: Hashable | None = None,
) -> tuple[ForecastPoint, ...]:
    """Create points for today, month end and each of the next N month ends."""

    if horizon_months < 0:
        raise ValueError("horizon_months nao pode ser negativo.")
    reference = parse_date(as_of or date.today())
    normalized_events = build_forecast_events(events, account_id=account_id)
    balance = parse_brl_currency(current_balance)
    points: list[ForecastPoint] = [ForecastPoint(reference, balance)]
    previous_cutoff = reference

    for offset in range(horizon_months + 1):
        target = month_end(add_months(reference, offset))
        if target <= reference:
            continue
        inflows = ZERO
        outflows = ZERO
        for event in normalized_events:
            if _event_in_bucket(event, previous_cutoff, target, reference):
                inflows += event.inflow
                outflows += event.outflow
        net = inflows - outflows
        balance += net
        points.append(
            ForecastPoint(
                target,
                parse_brl_currency(balance),
                parse_brl_currency(inflows),
                parse_brl_currency(outflows),
                parse_brl_currency(net),
            )
        )
        previous_cutoff = target
    return tuple(points)


def project_daily_balance(
    current_balance: MoneyLike,
    events: Iterable[Any],
    end_date: DateLike,
    *,
    as_of: DateLike | None = None,
    account_id: Hashable | None = None,
) -> tuple[ForecastPoint, ...]:
    """Create a daily series, useful for a compact forecast chart."""

    reference = parse_date(as_of or date.today())
    limit = parse_date(end_date)
    if limit < reference:
        raise ValueError("end_date nao pode ser anterior a as_of.")
    normalized = build_forecast_events(events, account_id=account_id)
    by_date: dict[date, list[ForecastEvent]] = {}
    for event in normalized:
        if reference < event.event_date <= limit:
            by_date.setdefault(event.event_date, []).append(event)
        elif limit > reference and event.outstanding and event.event_date <= reference:
            by_date.setdefault(reference + timedelta(days=1), []).append(event)

    balance = parse_brl_currency(current_balance)
    result = [ForecastPoint(reference, balance)]
    current = reference + timedelta(days=1)
    while current <= limit:
        daily = by_date.get(current, ())
        inflows = sum((event.inflow for event in daily), ZERO)
        outflows = sum((event.outflow for event in daily), ZERO)
        net = inflows - outflows
        balance += net
        result.append(
            ForecastPoint(
                current,
                parse_brl_currency(balance),
                parse_brl_currency(inflows),
                parse_brl_currency(outflows),
                parse_brl_currency(net),
            )
        )
        current += timedelta(days=1)
    return tuple(result)


def _event_in_bucket(
    event: ForecastEvent,
    lower_exclusive: date,
    upper_inclusive: date,
    reference: date,
) -> bool:
    if lower_exclusive < event.event_date <= upper_inclusive:
        return True
    return (
        lower_exclusive == reference
        and event.outstanding
        and event.event_date <= reference
        and upper_inclusive > reference
    )


# Descriptive alias for UI code.
generate_balance_forecast = project_balance
