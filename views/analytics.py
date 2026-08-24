"""Análises, relatório mensal, insights e previsão financeira."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from components.cards import render_metric_card, render_section_header, render_transaction_card
from components.charts import (
    balance_line_chart,
    category_donut_chart,
    forecast_chart,
    income_expense_chart,
    ranking_bar_chart,
    render_chart,
)
from database.models import Subscription, Transaction
from services.analytics_service import generate_financial_insights, percentage_change
from services.forecast_service import project_balance
from utils.currency import format_brl_percentage
from utils.dates import add_months, format_brl_date, month_end, month_start
from utils.helpers import display_currency
from views.common import PAYMENT_METHODS, page_header, privacy_enabled


MONTH_NAMES = (
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
)


def _month_label(value: date, *, short: bool = True) -> str:
    name = MONTH_NAMES[value.month - 1]
    return f"{name[:3] if short else name} {str(value.year)[2:] if short else value.year}"


def _six_month_rows(repository: Any, user_id: Any, today: date) -> list[dict[str, Any]]:
    first = month_start(add_months(today, -5))
    fetched = repository.monthly_cashflow(user_id, start_month=first, end_month=today)
    by_month = {row["month"]: row for row in fetched}
    rows: list[dict[str, Any]] = []
    for offset in range(6):
        month = month_start(add_months(first, offset))
        rows.append(
            by_month.get(
                month,
                {"month": month, "income": Decimal("0"), "expenses": Decimal("0"), "balance": Decimal("0")},
            )
        )
    return rows


def _forecast_events(repository: Any, user_id: Any, today: date, end: date) -> list[Any]:
    events = repository.list_upcoming_events(
        user_id,
        start_date=today,
        end_date=end,
        limit=200,
    )
    future_income = list(
        repository.session.scalars(
            select(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.deleted_at.is_(None),
                Transaction.transaction_type == "income",
                Transaction.status == "pending",
                Transaction.transaction_date > today,
                Transaction.transaction_date <= end,
            )
        )
    )
    events.extend(future_income)
    subscriptions = list(
        repository.session.scalars(
            select(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.deleted_at.is_(None),
                Subscription.is_active.is_(True),
                Subscription.next_charge_date > today,
                Subscription.next_charge_date <= end,
            )
        )
    )
    for subscription in subscriptions:
        charge = subscription.next_charge_date
        while charge <= end:
            events.append(
                {
                    "kind": "subscription",
                    "event_date": charge,
                    "amount": subscription.amount,
                    "description": subscription.name,
                    "event_id": f"subscription:{subscription.id}:{charge.isoformat()}",
                }
            )
            if subscription.frequency == "weekly":
                from datetime import timedelta

                charge += timedelta(weeks=1)
            elif subscription.frequency == "yearly":
                from utils.dates import add_years

                charge = add_years(charge, 1)
            else:
                charge = add_months(charge, 1, preferred_day=subscription.next_charge_date.day)
    return events


def _insight_transactions(repository: Any, user_id: Any, today: date) -> list[Any]:
    return list(
        repository.session.scalars(
            select(Transaction)
            .options(joinedload(Transaction.category))
            .where(
                Transaction.user_id == user_id,
                Transaction.deleted_at.is_(None),
                Transaction.competence_date >= month_start(add_months(today, -1)),
                Transaction.competence_date <= month_end(today),
            )
        ).unique()
    )


def render(repository: Any, user: Any) -> None:
    today = date.today()
    private = privacy_enabled()
    page_header("Análises", "Clareza sobre o mês e os próximos passos.", eyebrow="Sem julgamentos, só contexto")
    rows = _six_month_rows(repository, user.id, today)
    current = repository.monthly_summary(user.id, today)
    previous = repository.monthly_summary(user.id, add_months(today, -1))
    available = repository.total_available_balance(user.id)

    average_income = sum((row["income"] for row in rows), Decimal("0")) / Decimal("6")
    average_expenses = sum((row["expenses"] for row in rows), Decimal("0")) / Decimal("6")
    income_col, expense_col, saving_col = st.columns(3)
    with income_col:
        render_metric_card("Média de receitas", average_income, tone="green", hidden=private)
    with expense_col:
        render_metric_card("Média de gastos", average_expenses, tone="coral", hidden=private)
    with saving_col:
        render_metric_card("Economia no mês", current.balance, tone="purple", hidden=private)

    overview_tab, forecast_tab, report_tab = st.tabs(("Dashboard", "Previsão", "Relatório"))
    with overview_tab:
        render_section_header("Entradas x despesas", subtitle="Últimos 6 meses")
        render_chart(
            income_expense_chart(
                [_month_label(row["month"]) for row in rows],
                [row["income"] for row in rows],
                [row["expenses"] for row in rows],
            ),
            key="analytics_income_expense",
        )
        starting_balance = available - sum((row["balance"] for row in rows), Decimal("0"))
        running = starting_balance
        balances: list[Decimal] = []
        for row in rows:
            running += row["balance"]
            balances.append(running)
        render_section_header("Evolução do saldo", subtitle="Fluxo acumulado do período")
        render_chart(
            balance_line_chart([_month_label(row["month"]) for row in rows], balances),
            key="analytics_balance",
        )

        category_rows = repository.expenses_by_category(
            user.id,
            start_date=month_start(today),
            end_date=month_end(today),
        )
        chart_col, ranking_col = st.columns(2)
        with chart_col:
            render_section_header("Gastos por categoria")
            render_chart(
                category_donut_chart(
                    [row["name"] for row in category_rows],
                    [row["amount"] for row in category_rows],
                ),
                key="analytics_categories",
            )
        largest = repository.largest_expenses(
            user.id,
            start_date=month_start(today),
            end_date=month_end(today),
            limit=5,
        )
        with ranking_col:
            render_section_header("Maiores gastos")
            render_chart(
                ranking_bar_chart(
                    [item.description for item in largest],
                    [item.amount for item in largest],
                ),
                key="analytics_ranking",
            )

    with forecast_tab:
        horizon_end = month_end(add_months(today, 3))
        events = _forecast_events(repository, user.id, today, horizon_end)
        points = project_balance(available, events, as_of=today, horizon_months=3)
        render_section_header(
            "Previsão financeira",
            subtitle="Saldo atual + contas, faturas, assinaturas e receitas futuras",
        )
        render_chart(
            forecast_chart(
                ["Hoje" if point.point_date == today else _month_label(point.point_date, short=False) for point in points],
                [point.balance for point in points],
            ),
            key="analytics_forecast",
        )
        columns = st.columns(min(4, len(points)))
        for column, point in zip(columns, points):
            with column:
                render_metric_card(
                    "Hoje" if point.point_date == today else format_brl_date(point.point_date),
                    point.balance,
                    tone="purple" if point.balance >= 0 else "coral",
                    hidden=private,
                    caption=(
                        None
                        if point.point_date == today
                        else (
                            f"Entradas +{display_currency(point.inflows, private=private)} · "
                            f"Saídas −{display_currency(point.outflows, private=private)}"
                        )
                    ),
                )

        budget_rows = repository.budget_progress(user.id, today)
        budgets = {row["category"].name: row["budget"].amount for row in budget_rows}
        subscriptions = repository.subscription_totals(user.id)
        tx_items = _insight_transactions(repository, user.id, today)
        insights = generate_financial_insights(
            tx_items,
            today,
            budgets=budgets,
            subscriptions_total=subscriptions["monthly"],
            forecast_end_balance=points[-1].balance if points else available,
            as_of=today,
        )
        render_section_header("Indicadores inteligentes", subtitle="Cálculos locais, sem IA ou envio de dados")
        for insight in insights[:5]:
            st.info(insight, icon="💡")
        if not insights:
            st.caption("Com mais alguns lançamentos, comparações úteis aparecerão aqui.")

    with report_tab:
        render_section_header(
            f"{MONTH_NAMES[today.month - 1]} {today.year}",
            subtitle="Resumo automático do mês",
        )
        income_delta = percentage_change(current.income, previous.income)
        expense_delta = percentage_change(current.expenses, previous.expenses)
        report_income, report_expense, report_saved = st.columns(3)
        with report_income:
            render_metric_card(
                "Receitas",
                current.income,
                delta=(f"{format_brl_percentage(income_delta)} vs mês anterior" if income_delta is not None else None),
                delta_tone="positive" if income_delta is not None and income_delta >= 0 else "negative",
                tone="green",
                hidden=private,
            )
        with report_expense:
            render_metric_card(
                "Despesas",
                current.expenses,
                delta=(f"{format_brl_percentage(expense_delta)} vs mês anterior" if expense_delta is not None else None),
                delta_tone="positive" if expense_delta is not None and expense_delta <= 0 else "negative",
                tone="coral",
                hidden=private,
            )
        with report_saved:
            render_metric_card("Economizado", current.balance, tone="purple", hidden=private)
        categories = repository.expenses_by_category(
            user.id, start_date=month_start(today), end_date=month_end(today), limit=1
        )
        largest = repository.largest_expenses(
            user.id, start_date=month_start(today), end_date=month_end(today), limit=1
        )
        st.markdown(
            f"**Categoria com maior gasto:** {categories[0]['name'] if categories else '—'}  \n"
            f"**Maior despesa:** {largest[0].description if largest else '—'}"
        )
        if largest:
            render_transaction_card(
                largest[0].description,
                largest[0].amount,
                transaction_type="expense",
                date_label=format_brl_date(largest[0].transaction_date),
                method=PAYMENT_METHODS.get(largest[0].payment_method or ""),
                category=getattr(largest[0].category, "name", None),
                hidden=private,
            )
