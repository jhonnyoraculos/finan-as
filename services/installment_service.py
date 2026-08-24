"""Installment splitting and scheduling rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_DOWN

from services.card_service import calculate_invoice_dates
from utils.currency import MoneyLike, ZERO, parse_brl_currency, quantize_money
from utils.dates import DateLike, add_months, month_start, parse_date


@dataclass(frozen=True, slots=True)
class Installment:
    number: int
    total_installments: int
    amount: Decimal
    purchase_date: date
    competence_date: date
    due_date: date | None = None
    closing_date: date | None = None
    description: str = ""
    group_id: str | int | None = None

    @property
    def label(self) -> str:
        return f"{self.number}/{self.total_installments}"

    @property
    def installment_number(self) -> int:
        return self.number


def split_installment_amounts(
    total_amount: MoneyLike,
    installment_count: int,
) -> tuple[Decimal, ...]:
    """Split an amount into cents, placing the rounding remainder in the last part.

    The returned values always satisfy ``sum(parts) == total_amount``.
    """

    if isinstance(installment_count, bool) or not isinstance(installment_count, int):
        raise TypeError("installment_count deve ser inteiro.")
    if installment_count < 1:
        raise ValueError("installment_count deve ser maior que zero.")

    total = parse_brl_currency(total_amount)
    base = (total / installment_count).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    values = [base] * max(installment_count - 1, 0)
    last = quantize_money(total - sum(values, ZERO))
    values.append(last)
    if sum(values, ZERO) != total:  # Defensive invariant against Decimal context changes.
        raise ArithmeticError("A soma das parcelas nao corresponde ao valor original.")
    return tuple(values)


def generate_installment_schedule(
    total_amount: MoneyLike,
    installment_count: int,
    purchase_date: DateLike,
    *,
    closing_day: int | None = None,
    due_day: int | None = None,
    first_due_date: DateLike | None = None,
    description: str = "",
    group_id: str | int | None = None,
) -> tuple[Installment, ...]:
    """Create immutable monthly installments for cash or credit-card purchases.

    Pass ``closing_day`` and ``due_day`` for card purchases. Alternatively pass
    ``first_due_date`` for a non-card schedule whose first competence is known.
    """

    if (closing_day is None) != (due_day is None):
        raise ValueError("closing_day e due_day devem ser informados juntos.")
    if first_due_date is not None and closing_day is not None:
        raise ValueError("Use datas do cartao ou first_due_date, nao ambos.")

    purchase = parse_date(purchase_date)
    amounts = split_installment_amounts(total_amount, installment_count)

    first_closing: date | None = None
    due_preferred_day: int | None = None
    closing_preferred_day: int | None = None
    if closing_day is not None and due_day is not None:
        first_cycle = calculate_invoice_dates(purchase, closing_day, due_day)
        first_competence = first_cycle.competence_date
        first_due = first_cycle.due_date
        first_closing = first_cycle.closing_date
        due_preferred_day = due_day
        closing_preferred_day = closing_day
    elif first_due_date is not None:
        first_due = parse_date(first_due_date)
        first_competence = month_start(first_due)
        due_preferred_day = first_due.day
    else:
        first_due = None
        first_competence = month_start(purchase)

    result: list[Installment] = []
    for index, amount in enumerate(amounts):
        competence = add_months(first_competence, index, preferred_day=1)
        due = (
            add_months(first_due, index, preferred_day=due_preferred_day)
            if first_due is not None
            else None
        )
        closing = (
            add_months(first_closing, index, preferred_day=closing_preferred_day)
            if first_closing is not None
            else None
        )
        result.append(
            Installment(
                number=index + 1,
                total_installments=installment_count,
                amount=amount,
                purchase_date=purchase,
                competence_date=competence,
                due_date=due,
                closing_date=closing,
                description=description,
                group_id=group_id,
            )
        )
    return tuple(result)


def generate_card_installments(
    total_amount: MoneyLike,
    installment_count: int,
    purchase_date: DateLike,
    closing_day: int,
    due_day: int,
    **metadata: object,
) -> tuple[Installment, ...]:
    """Convenience wrapper for a credit-card installment schedule."""

    return generate_installment_schedule(
        total_amount,
        installment_count,
        purchase_date,
        closing_day=closing_day,
        due_day=due_day,
        description=str(metadata.get("description", "")),
        group_id=metadata.get("group_id"),
    )


split_installments = split_installment_amounts
