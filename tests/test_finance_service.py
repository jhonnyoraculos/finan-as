from datetime import date
from decimal import Decimal

from services.finance_service import (
    calculate_account_balance,
    calculate_account_balances,
    calculate_period_totals,
    create_transfer,
    create_transfer_movements,
    transfer_effect,
)


def test_balance_ignores_open_card_purchase_and_applies_transfer_per_account():
    transfer = create_transfer(
        "200,00", 1, 2, date(2026, 8, 20), transfer_id="transfer-1"
    )
    transactions = [
        {"tipo": "receita", "valor": "500,00", "conta_id": 1, "data": "2026-08-01"},
        {
            "tipo": "despesa",
            "valor": "100,00",
            "conta_id": 1,
            "forma_pagamento": "PIX",
            "data": "2026-08-10",
        },
        {
            "tipo": "despesa",
            "valor": "300,00",
            "conta_id": 1,
            "cartao_id": 9,
            "forma_pagamento": "credito",
            "status": "aberta",
            "data": "2026-08-12",
        },
        transfer,
    ]

    balances = calculate_account_balances(
        {1: "1000,00", 2: "50,00"}, transactions, as_of="2026-08-24"
    )

    assert balances == {1: Decimal("1200.00"), 2: Decimal("250.00")}


def test_paid_invoice_deducts_cash_once():
    transaction = {
        "tipo": "pagamento_fatura",
        "valor": "300,00",
        "conta_id": 1,
        "cartao_id": 9,
        "pagamento_de_fatura": True,
        "status": "pago",
        "data_pagamento": "2026-08-20",
    }

    assert calculate_account_balance("1000,00", [transaction], account_id=1) == Decimal(
        "700.00"
    )


def test_transfer_is_globally_neutral_and_movements_are_linked():
    transfer = create_transfer("500,00", "A", "B", "2026-08-24", transfer_id="x")
    outgoing, incoming = create_transfer_movements(transfer)

    assert transfer_effect(transfer) == Decimal("0.00")
    assert transfer_effect(transfer, account_id="A") == Decimal("-500.00")
    assert transfer_effect(transfer, account_id="B") == Decimal("500.00")
    assert outgoing.cash_effect + incoming.cash_effect == Decimal("0.00")
    assert outgoing.transfer_id == incoming.transfer_id == "x"


def test_repository_style_transfer_pair_affects_each_account_once():
    pair = [
        {
            "transaction_type": "transfer",
            "amount": "200,00",
            "account_id": 1,
            "destination_account_id": 2,
            "transfer_direction": "out",
            "transaction_date": "2026-08-20",
            "status": "paid",
        },
        {
            "transaction_type": "transfer",
            "amount": "200,00",
            "account_id": 2,
            "destination_account_id": 1,
            "transfer_direction": "in",
            "transaction_date": "2026-08-20",
            "status": "paid",
        },
    ]

    assert calculate_account_balances({1: 500, 2: 100}, pair) == {
        1: Decimal("300.00"),
        2: Decimal("300.00"),
    }


def test_pending_transfer_does_not_change_realized_balance():
    pending = {
        "transaction_type": "transfer",
        "amount": "200,00",
        "account_id": 1,
        "destination_account_id": 2,
        "transfer_direction": "out",
        "transaction_date": "2026-08-30",
        "status": "pending",
    }

    assert calculate_account_balance(500, [pending], account_id=1) == Decimal("500.00")


def test_period_totals_do_not_count_transfer_as_income_or_expense():
    transfer = create_transfer("500,00", "A", "B", "2026-08-24")
    totals = calculate_period_totals(
        [
            {"tipo": "receita", "valor": "1000,00", "data": "2026-08-01"},
            {"tipo": "despesa", "valor": "250,00", "data": "2026-08-02"},
            transfer,
        ],
        "2026-08-01",
        "2026-08-31",
    )

    assert totals.income == Decimal("1000.00")
    assert totals.expenses == Decimal("250.00")
    assert totals.net == Decimal("750.00")
