"""Orçamentos, metas, patrimônio e calendário financeiro."""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from typing import Any

import streamlit as st
from sqlalchemy import select

from components.cards import (
    render_bill_card,
    render_metric_card,
    render_progress_card,
    render_section_header,
    render_transaction_card,
)
from components.charts import balance_line_chart, render_chart
from components.dialogs import confirmation_button
from components.widgets import money_input, notify_success
from database.models import (
    Asset,
    FinancialGoal,
    Liability,
    NetWorthSnapshot,
    Transaction,
)
from utils.dates import add_months, format_brl_date, month_end, month_start
from utils.helpers import display_currency
from views.common import friendly_error, page_header, privacy_enabled, safe_rerun, select_model, status_label


ASSET_TYPES = {
    "investment": "Investimento",
    "property": "Imóvel",
    "vehicle": "Veículo",
    "equipment": "Equipamento",
    "cash_other": "Dinheiro fora das contas",
    "other": "Outro ativo",
}

LIABILITY_TYPES = {
    "loan": "Empréstimo",
    "financing": "Financiamento",
    "debt": "Dívida",
    "other": "Outro passivo",
}

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


def _render_budgets(repository: Any, user: Any) -> None:
    month = month_start(date.today())
    categories = repository.list_categories(user.id, kind="expense")
    rows = repository.budget_progress(user.id, month)
    render_section_header("Orçamento mensal", subtitle="Limites gentis por categoria")
    if rows:
        for row in rows:
            percentage = row["percentage"]
            tone = "coral" if percentage >= 100 else "yellow" if percentage >= 80 else "blue"
            render_progress_card(
                row["category"].name,
                row["spent"],
                row["budget"].amount,
                tone=tone,
                icon=row["category"].icon,
                subtitle=f"Restante {display_currency(row['remaining'], private=privacy_enabled())}",
                hidden=privacy_enabled(),
            )
    else:
        st.info("Defina um primeiro limite para acompanhar seus gastos sem pressão.")
    with st.form("budget_form"):
        category = select_model("Categoria", categories, key="budget_category")
        amount = money_input("Limite no mês", key="budget_amount", minimum=Decimal("0.01"))
        submitted = st.form_submit_button("Salvar orçamento", type="primary", use_container_width=True)
    if submitted:
        if category is None or amount is None:
            st.warning("Selecione categoria e limite.")
            return
        try:
            repository.upsert_budget(user.id, category.id, month, amount)
            notify_success("Orçamento salvo")
            safe_rerun()
        except Exception as exc:
            friendly_error("Não foi possível salvar o orçamento.", exc)


def _render_goals(repository: Any, user: Any) -> None:
    accounts = repository.list_accounts(user.id)
    progress = repository.goal_progress(user.id)
    render_section_header("Metas financeiras", subtitle="Acompanhe o que está construindo")
    for item in progress:
        goal = item["goal"]
        render_progress_card(
            goal.name,
            item["saved"],
            goal.target_amount,
            tone="purple",
            icon=goal.icon or "◇",
            subtitle=(f"Até {format_brl_date(goal.target_date)}" if goal.target_date else status_label(goal.status)),
            hidden=privacy_enabled(),
        )
    add_tab, contribution_tab = st.tabs(("Nova meta", "Adicionar aporte"))
    with add_tab:
        with st.form("new_goal"):
            name = st.text_input("Nome", placeholder="Reserva de emergência", max_chars=140)
            target = money_input("Valor da meta", key="goal_target", minimum=Decimal("0.01"))
            initial = money_input("Já guardado", key="goal_initial", minimum=Decimal("0"))
            has_date = st.checkbox("Definir prazo")
            target_date = st.date_input(
                "Prazo",
                value=add_months(date.today(), 12),
                format="DD/MM/YYYY",
                disabled=not has_date,
            )
            submitted = st.form_submit_button("Criar meta", type="primary", use_container_width=True)
        if submitted:
            if not name.strip() or target is None or initial is None:
                st.warning("Informe nome e valores da meta.")
            else:
                try:
                    repository.create(
                        FinancialGoal,
                        user_id=user.id,
                        name=name.strip(),
                        target_amount=target,
                        initial_amount=initial,
                        target_date=target_date if has_date else None,
                        icon="◇",
                        color="#B49AF8",
                        status="completed" if initial >= target else "active",
                    )
                    notify_success("Meta criada")
                    safe_rerun()
                except Exception as exc:
                    friendly_error("Não foi possível criar a meta.", exc)
    with contribution_tab:
        if progress:
            goal = st.selectbox("Meta", [item["goal"] for item in progress], format_func=lambda item: item.name)
            amount = money_input("Valor do aporte", key="goal_contribution", minimum=Decimal("0.01"))
            account = select_model(
                "Conta de referência",
                accounts,
                key="goal_contribution_account",
                optional=True,
                help="O aporte acompanha a meta; não cria uma nova despesa.",
            )
            contribution_date = st.date_input("Data", value=date.today(), format="DD/MM/YYYY")
            if st.button("Adicionar aporte", type="primary", use_container_width=True):
                if amount is None:
                    st.warning("Informe o valor do aporte.")
                else:
                    try:
                        repository.add_goal_contribution(
                            user.id,
                            goal.id,
                            amount,
                            contribution_date,
                            account_id=getattr(account, "id", None),
                        )
                        notify_success("Aporte adicionado")
                        safe_rerun()
                    except Exception as exc:
                        friendly_error("Não foi possível adicionar o aporte.", exc)
        else:
            st.caption("Crie uma meta antes de registrar aportes.")
    if progress:
        selected = st.selectbox("Gerenciar meta", [item["goal"] for item in progress], format_func=lambda item: item.name)
        with st.form(f"edit_goal_{selected.id}"):
            edit_name = st.text_input("Nome", value=selected.name, max_chars=140)
            edit_target = money_input(
                "Valor da meta",
                value=selected.target_amount,
                key=f"edit_goal_target_{selected.id}",
                minimum=Decimal("0.01"),
            )
            edit_date_enabled = st.checkbox("Manter prazo", value=selected.target_date is not None)
            edit_target_date = st.date_input(
                "Prazo",
                value=selected.target_date or add_months(date.today(), 12),
                format="DD/MM/YYYY",
                disabled=not edit_date_enabled,
            )
            saved = st.form_submit_button("Salvar alterações", use_container_width=True)
        if saved and edit_target is not None:
            try:
                repository.update_fields(
                    FinancialGoal,
                    selected.id,
                    {
                        "name": edit_name.strip(),
                        "target_amount": edit_target,
                        "target_date": edit_target_date if edit_date_enabled else None,
                    },
                    user_id=user.id,
                )
                notify_success("Meta atualizada")
                safe_rerun()
            except Exception as exc:
                friendly_error("Não foi possível atualizar a meta.", exc)
        confirmation_button(
            "Arquivar meta",
            key=f"delete_goal_{selected.id}",
            title="Arquivar meta?",
            message="A meta e seus aportes ficarão preservados no banco.",
            on_confirm=repository.soft_delete,
            confirm_args=(FinancialGoal, selected.id),
            confirm_kwargs={"user_id": user.id},
            success_message="Meta arquivada",
        )


def _render_wealth(repository: Any, user: Any) -> None:
    summary = repository.net_worth_summary(user.id)
    assets = list(
        repository.session.scalars(
            select(Asset).where(
                Asset.user_id == user.id,
                Asset.deleted_at.is_(None),
                Asset.is_active.is_(True),
            ).order_by(Asset.name)
        )
    )
    liabilities = list(
        repository.session.scalars(
            select(Liability).where(
                Liability.user_id == user.id,
                Liability.deleted_at.is_(None),
                Liability.is_active.is_(True),
            ).order_by(Liability.name)
        )
    )
    net_col, asset_col, liability_col = st.columns(3)
    with net_col:
        render_metric_card("Patrimônio líquido", summary["net_worth"], tone="purple", hidden=privacy_enabled())
    with asset_col:
        render_metric_card("Ativos", summary["assets"], tone="green", hidden=privacy_enabled())
    with liability_col:
        render_metric_card("Passivos", summary["liabilities"], tone="coral", hidden=privacy_enabled())
    st.caption("Contas entram automaticamente nos ativos; faturas abertas entram nos passivos.")

    history = list(
        repository.session.scalars(
            select(NetWorthSnapshot)
            .where(NetWorthSnapshot.user_id == user.id)
            .order_by(NetWorthSnapshot.snapshot_date)
            .limit(36)
        )
    )
    if history:
        render_chart(
            balance_line_chart(
                [format_brl_date(item.snapshot_date) for item in history],
                [item.net_worth for item in history],
                name="Patrimônio líquido",
            ),
            key="wealth_history",
        )
    if st.button("Registrar posição de hoje", use_container_width=True, key="wealth_snapshot"):
        try:
            repository.create_net_worth_snapshot(user.id)
            notify_success("Posição patrimonial registrada")
            safe_rerun()
        except Exception as exc:
            friendly_error("Não foi possível registrar a posição.", exc)

    asset_tab, liability_tab = st.tabs(("Ativos", "Passivos"))
    with asset_tab:
        for item in assets:
            render_bill_card(
                item.name,
                item.current_value,
                due_label=ASSET_TYPES.get(item.asset_type, item.asset_type),
                status="Ativo",
                icon="◆",
                hidden=privacy_enabled(),
            )
        with st.form("new_asset"):
            name = st.text_input("Nome do ativo", max_chars=140)
            asset_type = st.selectbox("Tipo", tuple(ASSET_TYPES), format_func=ASSET_TYPES.get)
            value = money_input("Valor atual", key="asset_value", minimum=Decimal("0"))
            acquired = st.date_input("Data de referência", value=date.today(), format="DD/MM/YYYY")
            submitted = st.form_submit_button("Adicionar ativo", type="primary", use_container_width=True)
        if submitted and name.strip() and value is not None:
            try:
                repository.create(
                    Asset,
                    user_id=user.id,
                    name=name.strip(),
                    asset_type=asset_type,
                    current_value=value,
                    acquired_at=acquired,
                    is_active=True,
                )
                notify_success("Ativo adicionado")
                safe_rerun()
            except Exception as exc:
                friendly_error("Não foi possível adicionar o ativo.", exc)
        if assets:
            selected_asset = st.selectbox("Gerenciar ativo", assets, format_func=lambda item: item.name)
            with st.form(f"edit_asset_{selected_asset.id}"):
                edit_name = st.text_input("Nome", value=selected_asset.name, max_chars=140)
                edit_type = st.selectbox(
                    "Tipo",
                    tuple(ASSET_TYPES),
                    index=tuple(ASSET_TYPES).index(selected_asset.asset_type),
                    format_func=ASSET_TYPES.get,
                )
                edit_value = money_input(
                    "Valor atual",
                    value=selected_asset.current_value,
                    key=f"edit_asset_value_{selected_asset.id}",
                    minimum=Decimal("0"),
                )
                saved = st.form_submit_button("Salvar alterações", use_container_width=True)
            if saved and edit_value is not None:
                try:
                    repository.update_fields(
                        Asset,
                        selected_asset.id,
                        {"name": edit_name.strip(), "asset_type": edit_type, "current_value": edit_value},
                        user_id=user.id,
                    )
                    notify_success("Ativo atualizado")
                    safe_rerun()
                except Exception as exc:
                    friendly_error("Não foi possível atualizar o ativo.", exc)
            confirmation_button(
                "Arquivar ativo",
                key=f"delete_asset_{selected_asset.id}",
                title="Arquivar ativo?",
                message="O item deixa o cálculo atual e permanece no histórico.",
                on_confirm=repository.soft_delete,
                confirm_args=(Asset, selected_asset.id),
                confirm_kwargs={"user_id": user.id},
                success_message="Ativo arquivado",
            )
    with liability_tab:
        for item in liabilities:
            render_bill_card(
                item.name,
                item.current_balance,
                due_label=LIABILITY_TYPES.get(item.liability_type, item.liability_type),
                status="Passivo",
                icon="◇",
                hidden=privacy_enabled(),
            )
        with st.form("new_liability"):
            name = st.text_input("Nome do passivo", max_chars=140)
            liability_type = st.selectbox("Tipo", tuple(LIABILITY_TYPES), format_func=LIABILITY_TYPES.get)
            balance = money_input("Saldo devedor", key="liability_value", minimum=Decimal("0"))
            has_due = st.checkbox("Possui vencimento")
            due = st.date_input("Vencimento", value=date.today(), format="DD/MM/YYYY", disabled=not has_due)
            submitted = st.form_submit_button("Adicionar passivo", type="primary", use_container_width=True)
        if submitted and name.strip() and balance is not None:
            try:
                repository.create(
                    Liability,
                    user_id=user.id,
                    name=name.strip(),
                    liability_type=liability_type,
                    current_balance=balance,
                    due_date=due if has_due else None,
                    is_active=True,
                )
                notify_success("Passivo adicionado")
                safe_rerun()
            except Exception as exc:
                friendly_error("Não foi possível adicionar o passivo.", exc)
        if liabilities:
            selected_liability = st.selectbox("Gerenciar passivo", liabilities, format_func=lambda item: item.name)
            with st.form(f"edit_liability_{selected_liability.id}"):
                edit_name = st.text_input("Nome", value=selected_liability.name, max_chars=140)
                edit_type = st.selectbox(
                    "Tipo",
                    tuple(LIABILITY_TYPES),
                    index=tuple(LIABILITY_TYPES).index(selected_liability.liability_type),
                    format_func=LIABILITY_TYPES.get,
                )
                edit_balance = money_input(
                    "Saldo devedor",
                    value=selected_liability.current_balance,
                    key=f"edit_liability_value_{selected_liability.id}",
                    minimum=Decimal("0"),
                )
                saved = st.form_submit_button("Salvar alterações", use_container_width=True)
            if saved and edit_balance is not None:
                try:
                    repository.update_fields(
                        Liability,
                        selected_liability.id,
                        {
                            "name": edit_name.strip(),
                            "liability_type": edit_type,
                            "current_balance": edit_balance,
                        },
                        user_id=user.id,
                    )
                    notify_success("Passivo atualizado")
                    safe_rerun()
                except Exception as exc:
                    friendly_error("Não foi possível atualizar o passivo.", exc)
            confirmation_button(
                "Arquivar passivo",
                key=f"delete_liability_{selected_liability.id}",
                title="Arquivar passivo?",
                message="O item deixa o cálculo atual e permanece no histórico.",
                on_confirm=repository.soft_delete,
                confirm_args=(Liability, selected_liability.id),
                confirm_kwargs={"user_id": user.id},
                success_message="Passivo arquivado",
            )


def _month_transactions(repository: Any, user_id: Any, reference: date) -> list[Any]:
    return list(
        repository.session.scalars(
            select(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.deleted_at.is_(None),
                Transaction.transaction_date >= month_start(reference),
                Transaction.transaction_date <= month_end(reference),
            ).order_by(Transaction.transaction_date)
        )
    )


def _render_calendar(repository: Any, user: Any) -> None:
    reference = st.date_input("Mês", value=date.today(), format="DD/MM/YYYY", key="calendar_reference")
    start = month_start(reference)
    end = month_end(reference)
    events = repository.list_upcoming_events(user.id, start_date=start, end_date=end, limit=200)
    transactions = _month_transactions(repository, user.id, reference)
    events_by_day: dict[date, list[Any]] = {}
    for event in events:
        events_by_day.setdefault(event["date"], []).append(event)
    for transaction in transactions:
        events_by_day.setdefault(transaction.transaction_date, []).append(transaction)

    render_section_header(
        f"{MONTH_NAMES[reference.month - 1]} {reference.year}",
        subtitle="Pontos indicam dias com movimentações ou vencimentos",
    )
    with st.container(key="finance_calendar_grid"):
        header = st.columns(7)
        for column, label in zip(header, ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")):
            column.caption(label)
        weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(reference.year, reference.month)
        selected_day = st.session_state.get("calendar_selected_day", date.today())
        for week_index, week in enumerate(weeks):
            columns = st.columns(7)
            for column, day in zip(columns, week):
                has_events = bool(events_by_day.get(day))
                label = f"{day.day}{' •' if has_events else ''}"
                with column:
                    if st.button(
                        label,
                        key=f"calendar_{week_index}_{day.isoformat()}",
                        disabled=day.month != reference.month,
                        type="primary" if day == selected_day else "secondary",
                        use_container_width=True,
                    ):
                        st.session_state["calendar_selected_day"] = day
                        selected_day = day
    render_section_header(f"{format_brl_date(selected_day)}")
    day_items = events_by_day.get(selected_day, [])
    if not day_items:
        st.caption("Nenhuma movimentação neste dia.")
    for item in day_items:
        if isinstance(item, Transaction):
            render_transaction_card(
                item.description,
                item.amount,
                transaction_type=item.transaction_type,
                date_label=format_brl_date(item.transaction_date),
                hidden=privacy_enabled(),
            )
        else:
            record = item["record"]
            render_bill_card(
                item["description"],
                item["amount"],
                due_label=format_brl_date(item["date"]),
                status=status_label(record.status),
                hidden=privacy_enabled(),
            )


def render(repository: Any, user: Any) -> None:
    page_header("Planejamento", "Orçamento, objetivos e visão patrimonial.", eyebrow="Seu próximo capítulo")
    budget_tab, goals_tab, wealth_tab, calendar_tab = st.tabs(("Orçamento", "Metas", "Patrimônio", "Calendário"))
    with budget_tab:
        _render_budgets(repository, user)
    with goals_tab:
        _render_goals(repository, user)
    with wealth_tab:
        _render_wealth(repository, user)
    with calendar_tab:
        _render_calendar(repository, user)
