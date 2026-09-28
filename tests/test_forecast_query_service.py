from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from services.forecast_query_service import collect_forecast_events


class _QueuedSession:
    def __init__(self, *results):
        self.results = list(results)

    def scalars(self, _query):
        return self.results.pop(0)


class _Repository:
    def __init__(self, transactions, subscriptions, recurring_rules=()):
        self.session = _QueuedSession(transactions, subscriptions, recurring_rules)

    def list_upcoming_events(self, *_args, **_kwargs):
        loan = SimpleNamespace(id="loan-part-1", status="pending")
        return [
            {
                "kind": "loan",
                "date": date(2026, 10, 5),
                "description": "Empréstimo · parcela 2/12",
                "amount": Decimal("200.00"),
                "record": loan,
            }
        ]


def test_collects_direct_transactions_loans_and_recurring_subscriptions():
    future_income = SimpleNamespace(
        id="income-1",
        transaction_type="income",
        transaction_date=date(2026, 10, 1),
        amount=Decimal("1500.00"),
        description="Salário",
        account_id="account-1",
        source="manual",
    )
    subscription = SimpleNamespace(
        id="subscription-1",
        name="Streaming",
        amount=Decimal("35.00"),
        frequency="monthly",
        next_charge_date=date(2026, 9, 15),
    )
    repository = _Repository([future_income], [subscription])

    events = collect_forecast_events(
        repository,
        "user-1",
        as_of=date(2026, 9, 1),
        end_date=date(2026, 11, 30),
    )

    assert [event["kind"] for event in events] == [
        "subscription",
        "income",
        "loan",
        "subscription",
        "subscription",
    ]
    assert events[1]["status"] == "pending"
    assert events[-1]["event_date"] == date(2026, 11, 15)


def test_generates_recurring_events_beyond_materialized_window():
    recurring = SimpleNamespace(
        id="recurring-1",
        description="Aluguel",
        amount=Decimal("900.00"),
        transaction_type="expense",
        frequency="monthly",
        start_date=date(2026, 9, 10),
        end_date=None,
        account_id="account-1",
        category_id=None,
        payment_method="pix",
        credit_card_id=None,
        is_active=True,
    )
    repository = _Repository([], [], [recurring])

    events = collect_forecast_events(
        repository,
        "user-1",
        as_of=date(2026, 9, 1),
        end_date=date(2026, 12, 31),
    )

    recurring_events = [event for event in events if event["kind"] == "expense"]
    assert [event["event_date"] for event in recurring_events] == [
        date(2026, 9, 10),
        date(2026, 10, 10),
        date(2026, 11, 10),
        date(2026, 12, 10),
    ]
