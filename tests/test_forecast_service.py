from datetime import date
from decimal import Decimal

from services.finance_service import create_transfer
from services.forecast_service import (
    build_financial_forecast_events,
    forecast_balance_at,
    project_balance,
)


def test_forecast_combines_future_income_and_expenses_by_month_end():
    events = [
        {"id": 1, "tipo": "boleto", "valor": "100,00", "vencimento": "2026-08-30"},
        {"id": 2, "tipo": "receita", "valor": "500,00", "data": "2026-09-01"},
    ]

    points = project_balance(
        "1000,00", events, as_of="2026-08-24", horizon_months=1
    )

    assert [point.point_date for point in points] == [
        date(2026, 8, 24),
        date(2026, 8, 31),
        date(2026, 9, 30),
    ]
    assert [point.balance for point in points] == [
        Decimal("1000.00"),
        Decimal("900.00"),
        Decimal("1400.00"),
    ]


def test_global_forecast_ignores_internal_transfer():
    transfer = create_transfer("200,00", 1, 2, "2026-08-30")

    assert forecast_balance_at(
        "1000,00", [transfer], "2026-08-31", as_of="2026-08-24"
    ) == Decimal("1000.00")
    assert forecast_balance_at(
        "1000,00",
        [transfer],
        "2026-08-31",
        as_of="2026-08-24",
        account_id=1,
    ) == Decimal("800.00")


def test_invoice_total_amount_is_recognized_by_forecast():
    invoice = {
        "id": "invoice-1",
        "status": "open",
        "due_date": "2026-09-10",
        "total_amount": "345,67",
        "type": "invoice",
    }

    assert forecast_balance_at(
        "1000,00", [invoice], "2026-09-30", as_of="2026-08-24"
    ) == Decimal("654.33")


def test_linked_installment_is_not_counted_again_when_invoice_is_present():
    invoice = {
        "id": "invoice-1",
        "status": "open",
        "due_date": "2026-09-10",
        "total_amount": "300,00",
    }
    installment = {
        "id": "part-1",
        "status": "posted",
        "due_date": "2026-09-10",
        "amount": "300,00",
        "invoice_id": "invoice-1",
    }

    events = build_financial_forecast_events(
        invoices=[invoice], installments=[installment]
    )

    assert len(events) == 1
    assert events[0].signed_amount == Decimal("-300.00")


def test_overdue_unpaid_bill_remains_in_future_projection():
    overdue_bill = {
        "id": "bill-1",
        "tipo": "boleto",
        "valor": "125,00",
        "vencimento": "2026-08-20",
        "status": "overdue",
    }

    assert forecast_balance_at(
        "1000,00", [overdue_bill], "2026-08-31", as_of="2026-08-24"
    ) == Decimal("875.00")
