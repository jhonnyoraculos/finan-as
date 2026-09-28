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
    render_sparkline,
    render_transaction_card,
)
from components.navigation import navigate_to
from services.forecast_query_service import collect_forecast_events
from services.forecast_service import build_forecast_events, project_balance
from utils.dates import add_months, format_brl_date, month_end, month_start
from utils.helpers import display_currency
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


def _render_future_months(points: list[Any], events: tuple[Any, ...], *, private: bool) -> None:
    render_section_header(
        "Próximos meses",
        subtitle="Ganhos, gastos e saldo projetado com base no que já foi cadastrado",
    )
    if not points:
        st.info("Cadastre ganhos, contas ou recorrências futuras para montar a previsão.")
        return

    for start in range(0, len(points), 3):
        group = points[start : start + 3]
        columns = st.columns(len(group))
        for column, point in zip(columns, group):
            with column:
                render_metric_card(
                    _month_label(point.point_date),
                    point.balance,
                    tone="purple" if point.balance >= 0 else "coral",
                    hidden=private,
                    caption=(
                        f"Ganhos {display_currency(point.inflows, private=private)} · "
                        f"Gastos {display_currency(point.outflows, private=private)}"
                    ),
                )

    with st.expander(f"Ver todos os lançamentos previstos ({len(events)})"):
        if events:
            st.dataframe(
                [
                    {
                        "Data": format_brl_date(event.event_date),
                        "Tipo": "Ganho" if event.signed_amount > 0 else "Gasto",
                        "Descrição": event.description or "Sem descrição",
                        "Valor": display_currency(abs(event.signed_amount), private=private),
                    }
                    for event in events
                ],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.caption("Nenhum lançamento futuro cadastrado neste período.")
    st.caption("A previsão muda automaticamente quando você cadastra, paga ou edita um lançamento.")


def render(repository: Any, user: Any) -> None:
    today = date.today()
    private = privacy_enabled()

    st.caption(f"{_greeting()}, {user.name.split()[0]} 👋")
    st.title("Minhas Finanças")
    show_future = st.toggle(
        "Ver gastos e ganhos futuros",
        key="home_show_future",
        help="Mostra o que está previsto em contas, faturas, parcelas, assinaturas e ganhos cadastrados.",
    )
    horizon_months = 3
    if show_future:
        horizon_label = st.segmented_control(
            "Período da previsão",
            ("3 meses", "6 meses", "12 meses", "Personalizado"),
            default="3 meses",
            key="home_future_horizon",
            selection_mode="single",
            width="stretch",
        ) or "3 meses"
        if horizon_label == "Personalizado":
            horizon_months = int(
                st.number_input(
                    "Quantos meses à frente?",
                    min_value=1,
                    max_value=60,
                    value=18,
                    step=1,
                    key="home_custom_future_months",
                    help="Escolha um período entre 1 e 60 meses.",
                )
            )
        else:
            horizon_months = {"3 meses": 3, "6 meses": 6, "12 meses": 12}[horizon_label]

    summary = repository.monthly_summary(user.id, today)
    balances = repository.get_account_balances(user.id)
    available = sum((item.balance for item in balances), Decimal("0"))
    net_worth = repository.net_worth_summary(user.id)
    budget_rows = repository.budget_progress(user.id, today)
    budget_total = sum((row["budget"].amount for row in budget_rows), Decimal("0"))
    budget_spent = sum((row["spent"] for row in budget_rows), Decimal("0"))

    forecast_points: list[Any] = []
    forecast_events: tuple[Any, ...] = ()
    forecast_income = Decimal("0")
    forecast_expenses = Decimal("0")
    if show_future:
        horizon_end = month_end(add_months(today, horizon_months))
        raw_events = collect_forecast_events(
            repository,
            user.id,
            as_of=today,
            end_date=horizon_end,
        )
        forecast_events = build_forecast_events(raw_events)
        forecast_points = list(
            project_balance(
                available,
                forecast_events,
                as_of=today,
                horizon_months=horizon_months,
            )
        )
        forecast_income = sum(
            (point.inflows for point in forecast_points[1:]),
            Decimal("0"),
        )
        forecast_expenses = sum(
            (point.outflows for point in forecast_points[1:]),
            Decimal("0"),
        )

    displayed_balance = forecast_points[-1].balance if forecast_points else available
    displayed_income = forecast_income if show_future else summary.income
    displayed_expenses = forecast_expenses if show_future else summary.expenses
    displayed_result = displayed_income - displayed_expenses if show_future else summary.balance

    render_metric_card(
        "Saldo projetado" if show_future else "Saldo disponível",
        displayed_balance,
        icon="◉",
        tone="blue" if displayed_balance >= 0 else "coral",
        hidden=private,
        caption=(
            f"Saldo atual {display_currency(available, private=private)}"
            if show_future
            else "Contas e dinheiro, sem compras em fatura"
        ),
    )
    income_col, expense_col, economy_col = st.columns(3)
    with income_col:
        render_metric_card(
            "Ganhos previstos" if show_future else "Entradas",
            displayed_income,
            icon="↗",
            tone="green",
            hidden=private,
        )
    with expense_col:
        render_metric_card(
            "Gastos previstos" if show_future else "Despesas",
            displayed_expenses,
            icon="↘",
            tone="coral",
            hidden=private,
        )
    with economy_col:
        render_metric_card(
            "Resultado previsto" if show_future else "Economia",
            displayed_result,
            icon="≈",
            tone="purple" if displayed_result >= 0 else "yellow",
            hidden=private,
        )

    if show_future:
        render_sparkline([point.balance for point in forecast_points])
        _render_future_months(forecast_points[1:], forecast_events, private=private)
    else:
        _labels, cashflow = _cashflow_series(repository, user.id, today)
        render_sparkline(cashflow)

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
