"""Pure rules for monthly loan schedules and progress."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from services.installment_service import split_installment_amounts
from utils.dates import add_months


@dataclass(frozen=True, slots=True)
class LoanScheduleItem:
    number: int
    amount: Decimal
    due_date: date
    initially_paid: bool = False


def generate_loan_schedule(
    total_amount: Decimal,
    total_installments: int,
    first_due_date: date,
    *,
    paid_installments: int = 0,
) -> list[LoanScheduleItem]:
    """Split a loan total and generate stable monthly due dates."""

    if total_installments < 1:
        raise ValueError("O empréstimo precisa ter ao menos uma parcela.")
    if not 0 <= paid_installments <= total_installments:
        raise ValueError("A quantidade de parcelas pagas é inválida.")
    amounts = split_installment_amounts(total_amount, total_installments)
    return [
        LoanScheduleItem(
            number=index + 1,
            amount=amount,
            due_date=add_months(
                first_due_date,
                index,
                preferred_day=first_due_date.day,
            ),
            initially_paid=index < paid_installments,
        )
        for index, amount in enumerate(amounts)
    ]


__all__ = ["LoanScheduleItem", "generate_loan_schedule"]
