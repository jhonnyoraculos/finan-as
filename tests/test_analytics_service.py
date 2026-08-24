from decimal import Decimal

from services.analytics_service import (
    calculate_monthly_summary,
    generate_financial_insights,
    spending_by_category,
)


def test_analytics_uses_competence_and_excludes_transfers():
    transactions = [
        {"tipo": "receita", "valor": "1000,00", "data_competencia": "2026-08-01"},
        {
            "tipo": "despesa",
            "valor": "250,00",
            "data_competencia": "2026-08-10",
            "categoria_nome": "Mercado",
            "cartao_id": 1,
        },
        {"tipo": "transferencia", "valor": "500,00", "data_competencia": "2026-08-10"},
    ]

    summary = calculate_monthly_summary(transactions, "2026-08-24")
    categories = spending_by_category(transactions, "2026-08-24")

    assert summary.income == Decimal("1000.00")
    assert summary.expenses == Decimal("250.00")
    assert summary.savings == Decimal("750.00")
    assert categories == {"Mercado": Decimal("250.00")}


def test_insights_are_generated_locally_and_are_non_empty():
    transactions = [
        {
            "tipo": "receita",
            "valor": "2000,00",
            "data_competencia": "2026-08-01",
        },
        {
            "tipo": "despesa",
            "valor": "100,00",
            "data_competencia": "2026-08-10",
            "categoria_nome": "Assinaturas",
        },
    ]

    insights = generate_financial_insights(
        transactions,
        "2026-08-24",
        subscriptions_total="100,00",
        forecast_end_balance="1500,00",
        as_of="2026-08-24",
    )

    assert any("assinaturas representam" in insight.lower() for insight in insights)
    assert any("saldo previsto" in insight.lower() for insight in insights)


def test_accrual_analytics_does_not_double_count_invoice_payment():
    transactions = [
        {
            "transaction_type": "expense",
            "amount": "300,00",
            "competence_date": "2026-08-01",
            "credit_card_id": 1,
            "payment_method": "credit",
            "status": "pending",
            "source": "card",
        },
        {
            "transaction_type": "expense",
            "amount": "300,00",
            "competence_date": "2026-08-20",
            "transaction_date": "2026-08-20",
            "payment_method": "boleto",
            "status": "paid",
            "source": "invoice_payment",
        },
    ]

    accrual = calculate_monthly_summary(transactions, "2026-08-01")
    cash = calculate_monthly_summary(
        transactions, "2026-08-01", date_basis="cash"
    )

    assert accrual.expenses == Decimal("300.00")
    assert cash.expenses == Decimal("300.00")
