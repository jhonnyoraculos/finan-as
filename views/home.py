"""Página inicial hierárquica e mobile-first."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import streamlit as st

from components.cards import (
    render_account_card,
    render_bill_card,
    render_credit_card,
    render_metric_card,
    render_progress_card,
    render_section_header,
    render_transaction_card,
)
from components.charts import render_chart, sparkline_chart
from components.navigation import navigate_to
from utils.dates import add_months, format_brl_date, month_end, month_start
from views.common import ACCOUNT_TYPES, PAYMENT_METHODS, privacy_enabled, status_label


MONTHS_PT = (
    "jan",
    "fev",
    "mar",
    "abr",
    "mai",
    "jun",
    "jul",
    "ago",
    "set",
    "out",
    "nov",
    "dez",
)


def _greeting() -> str:
    hour = datetime.now().hour
    if hour < 12:
        return "Bom dia"
    if hour < 18:
        return "Boa tarde"
    return "Boa noite"


def _month_label(value: date) -> str:
    return f"{MONTHS_PT[value.month - 1]}/{str(value.year)[2:]}"


def _cashflow_series(repository: Any, user_id: Any, today: date) -> tuple[list[str], list[Decimal]]:
    first = month_start(add_months(today, -5))
    rows = repository.monthly_cashflow(user_id, start_month=first, end_month=today)
    by_month = {item["month"]: item["balance"] for item in rows}
    months = [add_months(first, offset) for offset in range(6)]
    running = Decimal("0")
    values: list[Decimal] = []
    for month in months:
        running += by_month.get(month_start(month), Decimal("0"))
        values.append(running)
    return [_month_label(month) for month in months], values


def render(repository: Any, user: Any) -> None:
    today = date.today()
    private = privacy_enabled()
    summary = repository.monthly_summary(user.id, today)
    balances = repository.get_account_balances(user.id)
    available = sum((item.balance for item in balances), Decimal("0"))
    net_worth = repository.net_worth_summary(user.id)
    budget_rows = repository.budget_progress(user.id, today)
    budget_total = sum((row["budget"].amount for row in budget_rows), Decimal("0"))
    budget_spent = sum((row["spent"] for row in budget_rows), Decimal("0"))

    st.caption(f"{_greeting()}, {user.name.split()[0]} 👋")
    st.title("Minhas Finanças")

    render_metric_card(
        "Saldo disponível",
        available,
        icon="◉",
        tone="blue" if available >= 0 else "coral",
        hidden=private,
        caption="Contas e dinheiro, sem compras em fatura",
    )
    income_col, expense_col, economy_col = st.columns(3)
    with income_col:
        render_metric_card("Entradas", summary.income, icon="↗", tone="green", hidden=private)
    with expense_col:
        render_metric_card("Despesas", summary.expenses, icon="↘", tone="coral", hidden=private)
    with economy_col:
        render_metric_card(
            "Economia",
            summary.balance,
            icon="≈",
            tone="purple" if summary.balance >= 0 else "yellow",
            hidden=private,
        )

    labels, cashflow = _cashflow_series(repository, user.id, today)
    render_chart(sparkline_chart(cashflow, labels=labels), key="home_sparkline")

    render_section_header("Gastos do mês", subtitle="Acompanhamento tranquilo do seu limite")
    if budget_total > 0:
        render_progress_card(
            "Orçamento mensal",
            budget_spent,
            budget_total,
            tone="yellow" if budget_spent >= budget_total * Decimal("0.8") else "blue",
            subtitle="Soma das categorias planejadas",
            hidden=private,
        )
    else:
        reference = max(summary.income, summary.expenses, Decimal("1"))
        render_progress_card(
            "Despesas x entradas",
            summary.expenses,
            reference,
            tone="coral",
            subtitle="Crie orçamentos em Mais → Planejamento",
            hidden=private,
        )

    render_section_header("Contas", subtitle=f"{len(balances)} conta(s) ativa(s)")
    if balances:
        with st.container(key="finance_accounts_carousel"):
            columns = st.columns(min(3, len(balances)))
            for column, item in zip(columns, balances[:3]):
                account = item.account
                with column:
                    render_account_card(
                        account.name,
                        item.balance,
                        institution=account.institution,
                        account_type=ACCOUNT_TYPES.get(account.account_type),
                        icon=account.icon or "◉",
                        color=account.color,
                        hidden=private,
                    )
    else:
        st.info("Adicione sua primeira conta para ver o saldo disponível.")

    card_summaries = repository.list_card_summaries(user.id)
    if card_summaries:
        render_section_header("Fatura atual", subtitle="Compras ainda não reduzem o saldo da conta")
        card_summary = card_summaries[0]
        invoices = repository.list_invoices(
            user.id,
            credit_card_id=card_summary.card.id,
            statuses=("open", "closed", "overdue"),
            limit=1,
        )
        invoice = invoices[0] if invoices else None
        render_credit_card(
            card_summary.card.name,
            available=card_summary.available_limit,
            used=card_summary.open_amount,
            limit_total=card_summary.card.credit_limit,
            bank=card_summary.card.bank,
            closing_label=(f"Fecha {format_brl_date(invoice.closing_date)}" if invoice else None),
            due_label=(f"Vence {format_brl_date(invoice.due_date)}" if invoice else None),
            color=card_summary.card.color,
            hidden=private,
        )

    upcoming = repository.list_upcoming_events(
        user.id,
        start_date=today,
        end_date=month_end(add_months(today, 1)),
        limit=4,
    )
    render_section_header("Próximos pagamentos", subtitle="Boletos e faturas no radar")
    if upcoming:
        for event in upcoming:
            record = event["record"]
            render_bill_card(
                event["description"],
                event["amount"],
                due_label=f"Vence {format_brl_date(event['date'])}",
                status=status_label(getattr(record, "status", "pending")),
                icon="▣" if event["kind"] == "bill" else "▤",
                hidden=private,
            )
    else:
        st.caption("Nenhum pagamento previsto para os próximos dias.")

    recent = repository.list_transactions(user.id, page_size=5).items
    render_section_header("Últimas movimentações", subtitle="Seu histórico mais recente")
    if recent:
        for transaction in recent:
            render_transaction_card(
                transaction.description,
                transaction.amount,
                transaction_type=transaction.transaction_type,
                date_label=format_brl_date(transaction.transaction_date),
                method=PAYMENT_METHODS.get(transaction.payment_method or ""),
                category=getattr(transaction.category, "name", None),
                icon=getattr(transaction.category, "icon", None) or "•",
                installments=(
                    f"{transaction.installment_number}/{transaction.installment_count}"
                    if transaction.installment_count
                    else None
                ),
                hidden=private,
            )
        if st.button("Ver histórico completo", key="home_history", use_container_width=True):
            st.session_state["more_section"] = "Histórico"
            navigate_to("more")
            st.rerun()
    else:
        st.info("Sua primeira movimentação aparecerá aqui.")

    with st.expander("Patrimônio em resumo"):
        worth_col, debt_col = st.columns(2)
        with worth_col:
            render_metric_card("Patrimônio líquido", net_worth["net_worth"], tone="purple", hidden=private)
        with debt_col:
            render_metric_card("Passivos", net_worth["liabilities"], tone="yellow", hidden=private)
