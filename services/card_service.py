"""Pure credit-card invoice rules.

The purchase date, invoice closing date, due date and competence are kept as
separate concepts. This module does not read or write the database.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from datetime import timedelta
from decimal import Decimal
from typing import Any

from utils.currency import MoneyLike, ZERO, parse_brl_currency
from utils.dates import DateLike, add_months, date_with_day, month_start, parse_date
from utils.helpers import as_bool, get_value, normalize_token


@dataclass(frozen=True, slots=True)
class InvoiceCycle:
    """Calendar dates assigned to one credit-card purchase."""

    purchase_date: date
    closing_date: date
    due_date: date
    competence_date: date

    @property
    def competence(self) -> date:
        """Backward-friendly alias for the first day of the due month."""

        return self.competence_date


@dataclass(frozen=True, slots=True)
class InvoiceSummary:
    total: Decimal
    item_count: int
    competence_date: date
    closing_date: date | None = None
    due_date: date | None = None


def calculate_invoice_dates(
    purchase_date: DateLike,
    closing_day: int,
    due_day: int,
) -> InvoiceCycle:
    """Assign a purchase to its invoice cycle.

    A purchase made on the closing day still belongs to the invoice that is
    closing. A later purchase belongs to the following invoice. The invoice
    competence is the first day of its *due month*, which is the label users
    normally see for a card bill.
    """

    _validate_card_day(closing_day, "closing_day")
    _validate_card_day(due_day, "due_day")
    purchase = parse_date(purchase_date)

    closing = date_with_day(purchase.year, purchase.month, closing_day)
    if purchase > closing:
        next_month = add_months(closing, 1, preferred_day=1)
        closing = date_with_day(next_month.year, next_month.month, closing_day)

    due = calculate_due_date(closing, due_day)
    return InvoiceCycle(
        purchase_date=purchase,
        closing_date=closing,
        due_date=due,
        competence_date=month_start(due),
    )


def calculate_due_date(closing_date: DateLike, due_day: int) -> date:
    """Return the first configured due day strictly after a closing date."""

    _validate_card_day(due_day, "due_day")
    closing = parse_date(closing_date)
    due = date_with_day(closing.year, closing.month, due_day)
    if due <= closing:
        next_month = add_months(closing, 1, preferred_day=1)
        due = date_with_day(next_month.year, next_month.month, due_day)
    return due


def calculate_invoice_competence(
    purchase_date: DateLike,
    closing_day: int,
    due_day: int,
) -> date:
    """Return the first day of the invoice due month for a purchase."""

    return calculate_invoice_dates(purchase_date, closing_day, due_day).competence_date


def calculate_invoice_period(
    closing_date: DateLike,
    closing_day: int,
) -> tuple[date, date]:
    """Return the inclusive purchase interval covered by an invoice."""

    _validate_card_day(closing_day, "closing_day")
    closing = parse_date(closing_date)
    previous_month = add_months(closing, -1, preferred_day=1)
    previous_closing = date_with_day(previous_month.year, previous_month.month, closing_day)
    return previous_closing + timedelta(days=1), closing


def get_invoice_status(
    closing_date: DateLike,
    due_date: DateLike,
    *,
    paid: bool = False,
    paid_at: DateLike | None = None,
    as_of: DateLike | None = None,
) -> str:
    """Return ``aberta``, ``fechada``, ``atrasada`` or ``paga``."""

    if paid or paid_at is not None:
        return "paga"
    reference = parse_date(as_of or date.today())
    closing = parse_date(closing_date)
    due = parse_date(due_date)
    if reference <= closing:
        return "aberta"
    if reference <= due:
        return "fechada"
    return "atrasada"


def get_invoice_status_code(
    closing_date: DateLike,
    due_date: DateLike,
    *,
    paid: bool = False,
    paid_at: DateLike | None = None,
    as_of: DateLike | None = None,
) -> str:
    """Return the canonical database status: open/closed/overdue/paid."""

    localized = get_invoice_status(
        closing_date,
        due_date,
        paid=paid,
        paid_at=paid_at,
        as_of=as_of,
    )
    return {
        "aberta": "open",
        "fechada": "closed",
        "atrasada": "overdue",
        "paga": "paid",
    }[localized]


def calculate_available_limit(
    total_limit: MoneyLike,
    committed_amounts: Iterable[MoneyLike],
) -> Decimal:
    """Calculate card limit after open invoices and future installments."""

    limit = parse_brl_currency(total_limit)
    used = sum((abs(parse_brl_currency(value)) for value in committed_amounts), ZERO)
    return limit - used


def summarize_invoice(
    items: Iterable[Any],
    competence_date: DateLike,
) -> InvoiceSummary:
    """Summarize non-deleted items belonging to one invoice competence."""

    competence = month_start(competence_date)
    total = ZERO
    count = 0
    closing: date | None = None
    due: date | None = None
    for item in items:
        if get_value(item, "deleted_at", "excluido_em") is not None:
            continue
        item_competence = get_value(
            item,
            "competence_date",
            "data_competencia",
            "competence",
        )
        if item_competence is None or month_start(item_competence) != competence:
            continue
        status = normalize_token(get_value(item, "status", default=""))
        if status in {"cancelada", "cancelado", "cancelled", "estornada", "estornado"}:
            continue
        total += abs(parse_brl_currency(get_value(item, "amount", "valor", default=ZERO)))
        count += 1
        item_closing = get_value(item, "closing_date", "data_fechamento")
        item_due = get_value(item, "due_date", "data_vencimento", "vencimento")
        if item_closing is not None:
            closing = parse_date(item_closing)
        if item_due is not None:
            due = parse_date(item_due)
    return InvoiceSummary(total, count, competence, closing, due)


def group_purchases_by_invoice(
    purchases: Iterable[Any],
    closing_day: int,
    due_day: int,
) -> dict[date, list[Any]]:
    """Group arbitrary purchase objects/dicts by due-month competence."""

    grouped: defaultdict[date, list[Any]] = defaultdict(list)
    for purchase in purchases:
        if get_value(purchase, "deleted_at", "excluido_em") is not None:
            continue
        purchase_date = get_value(purchase, "purchase_date", "date", "data")
        if purchase_date is None:
            raise ValueError("Compra sem data.")
        cycle = calculate_invoice_dates(purchase_date, closing_day, due_day)
        grouped[cycle.competence_date].append(purchase)
    return dict(grouped)


def invoice_is_paid(invoice: Any) -> bool:
    """Recognize the common invoice payment fields used by persistence layers."""

    status = normalize_token(get_value(invoice, "status", default=""))
    return (
        status in {"paid", "paga", "pago"}
        or as_bool(get_value(invoice, "paid", "pago", default=False))
        or get_value(invoice, "paid_at", "data_pagamento") is not None
    )


def _validate_card_day(day: int, field_name: str) -> None:
    if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 31:
        raise ValueError(f"{field_name} deve estar entre 1 e 31.")


# Names commonly used by views/repositories.
invoice_dates_for_purchase = calculate_invoice_dates
invoice_competence_for_purchase = calculate_invoice_competence
