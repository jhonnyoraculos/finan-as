"""Load registered future cash events for the forecasting screens."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from database.models import RecurringTransaction, Subscription, Transaction
from services.recurring_service import generate_recurrence_occurrences
from utils.dates import add_months, add_years


def collect_forecast_events(
    repository: Any,
    user_id: Any,
    *,
    as_of: date,
    end_date: date,
) -> list[Any]:
    """Return future income and expenses from every registered source.

    Bills, card invoices and loan installments come from the repository's
    unified agenda. Direct future transactions and subscription occurrences
    are added here. Transactions linked to an invoice are excluded because
    the invoice already carries their total.
    """

    events = repository.list_upcoming_events(
        user_id,
        start_date=as_of,
        end_date=end_date,
        limit=200,
    )
    for event in events:
        record = event.get("record")
        event["event_id"] = f"{event['kind']}:{getattr(record, 'id', event['date'])}"
        event["status"] = getattr(record, "status", "pending")
    materialized_expenses = {
        (str(record.recurring_transaction_id), event["date"])
        for event in events
        if (record := event.get("record")) is not None
        and getattr(record, "recurring_transaction_id", None) is not None
    }

    transactions = list(
        repository.session.scalars(
            select(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.deleted_at.is_(None),
                Transaction.transaction_type.in_(("income", "expense")),
                Transaction.status.in_(("paid", "pending")),
                Transaction.transaction_date > as_of,
                Transaction.transaction_date <= end_date,
                Transaction.invoice_id.is_(None),
                Transaction.source.not_in(("invoice_payment", "loan_disbursement")),
            )
        )
    )
    materialized_incomes = {
        (
            transaction.description,
            transaction.transaction_date,
            transaction.amount,
            transaction.account_id,
        )
        for transaction in transactions
        if transaction.transaction_type == "income" and transaction.source == "recurring"
    }
    for transaction in transactions:
        events.append(
            {
                "kind": transaction.transaction_type,
                "event_date": transaction.transaction_date,
                "amount": transaction.amount,
                "description": transaction.description,
                "event_id": f"transaction:{transaction.id}",
                # A future transaction marked as paid is not part of today's
                # account balance yet, so it remains outstanding in forecast.
                "status": "pending",
            }
        )

    subscriptions = list(
        repository.session.scalars(
            select(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.deleted_at.is_(None),
                Subscription.is_active.is_(True),
                Subscription.recurring_transaction_id.is_(None),
                Subscription.next_charge_date <= end_date,
            )
        )
    )
    for subscription in subscriptions:
        charge = subscription.next_charge_date
        while charge <= as_of:
            if subscription.frequency == "weekly":
                charge += timedelta(weeks=1)
            elif subscription.frequency == "yearly":
                charge = add_years(charge, 1)
            else:
                charge = add_months(
                    charge,
                    1,
                    preferred_day=subscription.next_charge_date.day,
                )
        while charge <= end_date:
            events.append(
                {
                    "kind": "subscription",
                    "event_date": charge,
                    "amount": subscription.amount,
                    "description": subscription.name,
                    "event_id": f"subscription:{subscription.id}:{charge.isoformat()}",
                    "status": "pending",
                }
            )
            if subscription.frequency == "weekly":
                charge += timedelta(weeks=1)
            elif subscription.frequency == "yearly":
                charge = add_years(charge, 1)
            else:
                charge = add_months(
                    charge,
                    1,
                    preferred_day=subscription.next_charge_date.day,
                )

    recurring_rules = list(
        repository.session.scalars(
            select(RecurringTransaction).where(
                RecurringTransaction.user_id == user_id,
                RecurringTransaction.deleted_at.is_(None),
                RecurringTransaction.is_active.is_(True),
                RecurringTransaction.start_date <= end_date,
            )
        )
    )
    for rule in recurring_rules:
        occurrences = generate_recurrence_occurrences(
            rule,
            as_of + timedelta(days=1),
            end_date,
        )
        for occurrence in occurrences:
            if rule.transaction_type == "expense" and (
                str(rule.id),
                occurrence.occurrence_date,
            ) in materialized_expenses:
                continue
            if rule.transaction_type == "income" and (
                rule.description,
                occurrence.occurrence_date,
                rule.amount,
                rule.account_id,
            ) in materialized_incomes:
                continue
            events.append(
                {
                    "kind": rule.transaction_type,
                    "event_date": occurrence.occurrence_date,
                    "amount": occurrence.amount,
                    "description": occurrence.description,
                    "event_id": (
                        f"recurring:{rule.id}:{occurrence.occurrence_date.isoformat()}"
                    ),
                    "status": "pending",
                }
            )
    return sorted(
        events,
        key=lambda item: item.get("event_date", item.get("date", as_of)),
    )


__all__ = ["collect_forecast_events"]
