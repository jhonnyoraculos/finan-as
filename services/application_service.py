"""Casos de uso que coordenam repositório e regras financeiras puras."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from database.models import Bill, Installment, RecurringTransaction
from services.installment_service import generate_card_installments
from services.recurring_service import (
    generate_recurrence_occurrences,
    next_recurrence_date,
)
from utils.dates import add_months, month_end


def post_card_purchase(
    repository: Any,
    *,
    user_id: Any,
    card: Any,
    description: str,
    total_amount: Decimal,
    purchase_date: date,
    category_id: Any | None = None,
    installment_count: int = 1,
    notes: str | None = None,
) -> tuple[Any, ...]:
    """Post one card purchase across invoices without duplicating its total.

    Each generated transaction contains only its installment amount. Banking
    cash is unaffected until ``FinanceRepository.pay_invoice`` is called.
    """

    group_id = uuid.uuid4()
    schedule = generate_card_installments(
        total_amount,
        installment_count,
        purchase_date,
        card.closing_day,
        card.due_day,
        description=description,
        group_id=group_id,
    )
    transactions: list[Any] = []
    touched_invoices: set[Any] = set()
    for part in schedule:
        invoice = repository.get_or_create_invoice(
            user_id,
            card.id,
            part.competence_date,
            closing_date=part.closing_date,
            due_date=part.due_date,
        )
        transaction = repository.create_transaction(
            user_id,
            description,
            part.amount,
            "expense",
            purchase_date,
            competence_date=part.competence_date,
            category_id=category_id,
            credit_card_id=card.id,
            invoice_id=invoice.id,
            payment_method="credit",
            notes=notes,
            status="pending",
            installment_number=part.number,
            installment_count=part.total_installments,
            installment_group_id=group_id,
            source="card",
        )
        repository.create(
            Installment,
            user_id=user_id,
            installment_group_id=group_id,
            transaction_id=transaction.id,
            credit_card_id=card.id,
            invoice_id=invoice.id,
            description=description.strip(),
            amount=part.amount,
            installment_number=part.number,
            installment_count=part.total_installments,
            purchase_date=purchase_date,
            due_date=part.due_date,
            competence_date=part.competence_date,
            status="posted",
        )
        transactions.append(transaction)
        touched_invoices.add(invoice.id)
    for invoice_id in touched_invoices:
        repository.recalculate_invoice_total(invoice_id, user_id=user_id)
    return tuple(transactions)


def post_quick_transaction(
    repository: Any,
    *,
    user_id: Any,
    transaction_type: str,
    description: str,
    amount: Decimal,
    transaction_date: date,
    account_id: Any | None = None,
    destination_account_id: Any | None = None,
    category_id: Any | None = None,
    payment_method: str | None = None,
    credit_card: Any | None = None,
    installment_count: int = 1,
    notes: str | None = None,
    is_refund: bool = False,
    refunded_transaction_id: Any | None = None,
) -> tuple[Any, ...]:
    """Route quick-entry data through the appropriate atomic use case."""

    if transaction_type == "transfer":
        if account_id is None or destination_account_id is None:
            raise ValueError("Selecione as contas de origem e destino.")
        return repository.create_transfer(
            user_id,
            account_id,
            destination_account_id,
            amount,
            transaction_date,
            description=description or "Transferência",
            notes=notes,
        )
    if payment_method == "credit":
        if transaction_type != "expense" or credit_card is None:
            raise ValueError("Crédito exige uma despesa e um cartão.")
        return post_card_purchase(
            repository,
            user_id=user_id,
            card=credit_card,
            description=description,
            total_amount=amount,
            purchase_date=transaction_date,
            category_id=category_id,
            installment_count=installment_count,
            notes=notes,
        )
    record = repository.create_transaction(
        user_id,
        description,
        amount,
        transaction_type,
        transaction_date,
        category_id=category_id,
        account_id=account_id,
        payment_method=payment_method,
        notes=notes,
        is_refund=is_refund,
        refunded_transaction_id=refunded_transaction_id,
    )
    return (record,)


def materialize_recurring_items(
    repository: Any,
    user_id: Any,
    *,
    as_of: date | None = None,
    horizon_months: int = 3,
) -> int:
    """Generate missing recurring bills/incomes with deterministic keys."""

    today = as_of or date.today()
    through = month_end(add_months(today, horizon_months))
    rules = list(
        repository.session.scalars(
            select(RecurringTransaction).where(
                RecurringTransaction.user_id == user_id,
                RecurringTransaction.deleted_at.is_(None),
                RecurringTransaction.is_active.is_(True),
                RecurringTransaction.next_run_date <= through,
            )
        )
    )
    created = 0
    for rule in rules:
        existing = set(
            repository.session.scalars(
                select(Bill.recurrence_key).where(
                    Bill.recurring_transaction_id == rule.id,
                    Bill.deleted_at.is_(None),
                )
            )
        )
        occurrences = generate_recurrence_occurrences(
            {
                "recurrence_id": rule.id,
                "start_date": rule.start_date,
                "frequency": rule.frequency,
                "end_date": rule.end_date,
                "amount": rule.amount,
                "description": rule.description,
                "transaction_type": rule.transaction_type,
                "account_id": rule.account_id,
                "category_id": rule.category_id,
                "payment_method": rule.payment_method,
                "active": rule.is_active,
            },
            max(today, rule.next_run_date),
            through,
        )
        for occurrence in occurrences:
            record_key = f"{occurrence.recurrence_key}:{occurrence.occurrence_date.isoformat()}"
            if record_key in existing:
                continue
            if rule.transaction_type == "income":
                repository.create_transaction(
                    user_id,
                    rule.description,
                    rule.amount,
                    "income",
                    occurrence.occurrence_date,
                    competence_date=occurrence.occurrence_date,
                    category_id=rule.category_id,
                    account_id=rule.account_id,
                    payment_method=rule.payment_method,
                    status="pending",
                    is_recurring=True,
                    source="recurring",
                )
            else:
                repository.create_bill(
                    user_id,
                    rule.description,
                    rule.amount,
                    occurrence.occurrence_date,
                    category_id=rule.category_id,
                    account_id=rule.account_id,
                    recurring_transaction_id=rule.id,
                    recurrence_key=record_key,
                )
            created += 1
        next_date = next_recurrence_date(
            {
                "recurrence_id": rule.id,
                "start_date": rule.start_date,
                "frequency": rule.frequency,
                "end_date": rule.end_date,
                "amount": rule.amount,
                "description": rule.description,
                "active": rule.is_active,
            },
            through,
        )
        if next_date is not None:
            rule.next_run_date = next_date
        elif rule.end_date is not None and rule.end_date <= through:
            rule.is_active = False
    repository.session.flush()
    return created


def refresh_invoice_statuses(repository: Any, user_id: Any, *, as_of: date | None = None) -> int:
    """Move open invoices through closed/overdue states without touching paid ones."""

    today = as_of or date.today()
    changed = 0
    for invoice in repository.list_invoices(
        user_id, statuses=("open", "closed", "overdue"), limit=120
    ):
        expected = "open" if today <= invoice.closing_date else "closed"
        if today > invoice.due_date:
            expected = "overdue"
        if invoice.status != expected:
            invoice.status = expected
            changed += 1
    if changed:
        repository.session.flush()
    return changed


__all__ = [
    "materialize_recurring_items",
    "post_card_purchase",
    "post_quick_transaction",
    "refresh_invoice_statuses",
]
