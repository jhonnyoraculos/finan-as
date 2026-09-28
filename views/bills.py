"""Contas a pagar, recorrências e assinaturas."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import streamlit as st
from sqlalchemy import select

from components.cards import (
    render_bill_card,
    render_metric_card,
    render_section_header,
)
from components.dialogs import confirmation_button
from components.widgets import money_input, notify_success
from database.models import Bill, Loan, RecurringTransaction, Subscription
from services.application_service import materialize_recurring_items
from utils.dates import format_brl_date
from views.common import (
    PAYMENT_METHODS,
    friendly_error,
    page_header,
    privacy_enabled,
    safe_rerun,
    select_model,
    status_label,
)


FREQUENCIES = {"weekly": "Semanal", "monthly": "Mensal", "yearly": "Anual"}


def _refresh_overdue(repository: Any, bills: list[Any]) -> None:
    changed = False
    today = date.today()
    for bill in bills:
        expected = "overdue" if bill.status == "pending" and bill.due_date < today else bill.status
        if bill.status == "overdue" and bill.due_date >= today:
            expected = "pending"
        if expected != bill.status:
            bill.status = expected
            changed = True
    if changed:
        repository.session.flush()


def _render_open_bills(repository: Any, user: Any, accounts: list[Any], categories: list[Any]) -> None:
    bills = repository.list_bills(user.id, statuses=("pending", "overdue"), limit=100)
    _refresh_overdue(repository, bills)
    category_by_id = {item.id: item for item in categories}
    account_by_id = {item.id: item for item in accounts}
    overdue_total = sum((item.amount for item in bills if item.status == "overdue"), Decimal("0"))
    next_30_total = sum(
        (item.amount for item in bills if item.due_date <= date.today() + timedelta(days=30)),
        Decimal("0"),
    )
    metric_col, overdue_col = st.columns(2)
    with metric_col:
        render_metric_card("Próximos 30 dias", next_30_total, tone="yellow", hidden=privacy_enabled())
    with overdue_col:
        render_metric_card("Em atraso", overdue_total, tone="coral", hidden=privacy_enabled())

    render_section_header("Contas em aberto", subtitle=f"{len(bills)} compromisso(s)")
    if not bills:
        st.info("Nenhuma conta em aberto. Aproveite a tranquilidade.")
        return
    for bill in bills:
        category = category_by_id.get(bill.category_id)
        account = account_by_id.get(bill.account_id)
        render_bill_card(
            bill.description,
            bill.amount,
            due_label=f"Vence {format_brl_date(bill.due_date)}",
            status=status_label(bill.status),
            category=getattr(category, "name", None),
            account=getattr(account, "name", None),
            hidden=privacy_enabled(),
        )
    selected = st.selectbox(
        "Conta para agir",
        bills,
        format_func=lambda item: f"{item.due_date:%d/%m} · {item.description}",
        key="bill_action_select",
    )
    payment_account = select_model(
        "Pagar com",
        accounts,
        key=f"bill_payment_account_{selected.id}",
        formatter=lambda item: item.name,
        default_id=selected.account_id,
    )
    method = st.selectbox(
        "Forma de pagamento",
        ("pix", "debit", "boleto", "cash", "other"),
        format_func=PAYMENT_METHODS.get,
        key=f"bill_payment_method_{selected.id}",
    )
    confirmation_button(
        "Marcar como paga",
        key=f"pay_bill_{selected.id}",
        title="Confirmar pagamento",
        message="Uma despesa será criada na conta escolhida e vinculada a esta conta a pagar.",
        on_confirm=repository.mark_bill_paid,
        confirm_args=(user.id, selected.id),
        confirm_kwargs={
            "account_id": getattr(payment_account, "id", None),
            "payment_date": date.today(),
            "payment_method": method,
        },
        success_message="Conta marcada como paga",
        use_container_width=True,
    )

    with st.expander("Editar ou excluir conta"):
        with st.form(f"edit_bill_{selected.id}"):
            description = st.text_input("Descrição", value=selected.description, max_chars=240)
            amount = money_input(
                "Valor",
                value=selected.amount,
                key=f"edit_bill_amount_{selected.id}",
                minimum=Decimal("0.01"),
            )
            due = st.date_input("Vencimento", value=selected.due_date, format="DD/MM/YYYY")
            notes = st.text_area("Observação", value=selected.notes or "", max_chars=2000)
            save = st.form_submit_button("Salvar", use_container_width=True)
        if save and amount is not None:
            try:
                repository.update_fields(
                    Bill,
                    selected.id,
                    {
                        "description": description.strip(),
                        "amount": amount,
                        "due_date": due,
                        "notes": notes.strip() or None,
                        "status": "overdue" if due < date.today() else "pending",
                    },
                    user_id=user.id,
                )
                notify_success("Conta atualizada")
                safe_rerun()
            except Exception as exc:
                friendly_error("Não foi possível atualizar a conta.", exc)
        confirmation_button(
            "Excluir conta",
            key=f"delete_bill_{selected.id}",
            title="Excluir conta?",
            message="O registro será removido das previsões, mas ficará preservado no banco.",
            on_confirm=repository.soft_delete,
            confirm_args=(Bill, selected.id),
            confirm_kwargs={"user_id": user.id},
            success_message="Conta excluída",
        )


def _render_add_bill(repository: Any, user: Any, accounts: list[Any], categories: list[Any]) -> None:
    render_section_header("Nova conta a pagar")
    with st.form("new_bill"):
        description = st.text_input("Descrição", placeholder="Ex.: Internet", max_chars=240)
        amount = money_input("Valor", key="new_bill_amount", minimum=Decimal("0.01"))
        due = st.date_input("Vencimento", value=date.today(), format="DD/MM/YYYY")
        category = select_model("Categoria", categories, key="new_bill_category", optional=True)
        account = select_model("Conta prevista", accounts, key="new_bill_account", optional=True)
        notes = st.text_area("Observação", max_chars=2000)
        submitted = st.form_submit_button("Adicionar conta", type="primary", use_container_width=True)
    if submitted:
        if not description.strip() or amount is None:
            st.warning("Informe descrição e valor.")
            return
        try:
            repository.create_bill(
                user.id,
                description.strip(),
                amount,
                due,
                category_id=getattr(category, "id", None),
                account_id=getattr(account, "id", None),
                notes=notes.strip() or None,
            )
            notify_success("Conta adicionada")
            safe_rerun()
        except Exception as exc:
            friendly_error("Não foi possível adicionar a conta.", exc)


def _render_recurring(repository: Any, user: Any, accounts: list[Any], categories: list[Any]) -> None:
    rules = list(
        repository.session.scalars(
            select(RecurringTransaction)
            .where(
                RecurringTransaction.user_id == user.id,
                RecurringTransaction.deleted_at.is_(None),
            )
            .order_by(RecurringTransaction.description)
        )
    )
    render_section_header("Recorrências", subtitle="Próximos vencimentos são gerados sem duplicidade")
    for rule in rules:
        st.markdown(
            f"**{rule.description}** · {FREQUENCIES.get(rule.frequency)} · "
            f"próxima em {format_brl_date(rule.next_run_date)}"
        )
    with st.form("new_recurring_bill"):
        description = st.text_input("Descrição", placeholder="Aluguel, energia, academia…", max_chars=240)
        amount = money_input("Valor", key="new_recurring_amount", minimum=Decimal("0.01"))
        frequency = st.selectbox("Frequência", tuple(FREQUENCIES), format_func=FREQUENCIES.get)
        start = st.date_input("Primeiro vencimento", value=date.today(), format="DD/MM/YYYY")
        category = select_model("Categoria", categories, key="new_recurring_category", optional=True)
        account = select_model("Conta prevista", accounts, key="new_recurring_account", optional=True)
        submitted = st.form_submit_button("Criar recorrência", type="primary", use_container_width=True)
    if submitted:
        if not description.strip() or amount is None:
            st.warning("Informe descrição e valor.")
            return
        try:
            repository.create(
                RecurringTransaction,
                user_id=user.id,
                description=description.strip(),
                amount=amount,
                transaction_type="expense",
                frequency=frequency,
                start_date=start,
                next_run_date=start,
                category_id=getattr(category, "id", None),
                account_id=getattr(account, "id", None),
                payment_method="boleto",
                is_active=True,
            )
            materialize_recurring_items(repository, user.id)
            notify_success("Recorrência criada e próximos vencimentos gerados")
            safe_rerun()
        except Exception as exc:
            friendly_error("Não foi possível criar a recorrência.", exc)
    if rules:
        selected = st.selectbox("Gerenciar recorrência", rules, format_func=lambda item: item.description)
        with st.form(f"edit_recurring_{selected.id}"):
            edit_description = st.text_input("Descrição", value=selected.description, max_chars=240)
            edit_amount = money_input(
                "Valor",
                value=selected.amount,
                key=f"edit_recurring_amount_{selected.id}",
                minimum=Decimal("0.01"),
            )
            edit_frequency = st.selectbox(
                "Frequência",
                tuple(FREQUENCIES),
                index=tuple(FREQUENCIES).index(selected.frequency),
                format_func=FREQUENCIES.get,
            )
            saved = st.form_submit_button("Salvar alterações", use_container_width=True)
        if saved and edit_amount is not None:
            try:
                repository.update_fields(
                    RecurringTransaction,
                    selected.id,
                    {
                        "description": edit_description.strip(),
                        "amount": edit_amount,
                        "frequency": edit_frequency,
                    },
                    user_id=user.id,
                )
                notify_success("Recorrência atualizada")
                safe_rerun()
            except Exception as exc:
                friendly_error("Não foi possível atualizar a recorrência.", exc)
        confirmation_button(
            "Encerrar recorrência",
            key=f"delete_recurring_{selected.id}",
            title="Encerrar recorrência?",
            message="Vencimentos já gerados serão preservados; novos não serão criados.",
            on_confirm=repository.soft_delete,
            confirm_args=(RecurringTransaction, selected.id),
            confirm_kwargs={"user_id": user.id},
            success_message="Recorrência encerrada",
        )


def _render_subscriptions(repository: Any, user: Any, accounts: list[Any], categories: list[Any], cards: list[Any]) -> None:
    subscriptions = list(
        repository.session.scalars(
            select(Subscription)
            .where(
                Subscription.user_id == user.id,
                Subscription.deleted_at.is_(None),
                Subscription.is_active.is_(True),
            )
            .order_by(Subscription.next_charge_date)
        )
    )
    totals = repository.subscription_totals(user.id)
    month_col, year_col = st.columns(2)
    with month_col:
        render_metric_card("Total mensal", totals["monthly"], tone="purple", hidden=privacy_enabled())
    with year_col:
        render_metric_card("Estimativa anual", totals["yearly"], tone="yellow", hidden=privacy_enabled())
    render_section_header("Assinaturas ativas")
    for item in subscriptions:
        render_bill_card(
            item.name,
            item.amount,
            due_label=f"Próxima {format_brl_date(item.next_charge_date)}",
            status=FREQUENCIES.get(item.frequency, item.frequency),
            icon="◇",
            hidden=privacy_enabled(),
        )
    with st.form("new_subscription"):
        name = st.text_input("Nome", placeholder="Netflix, Spotify, iCloud…", max_chars=140)
        amount = money_input("Valor", key="new_subscription_amount", minimum=Decimal("0.01"))
        frequency = st.selectbox("Cobrança", tuple(FREQUENCIES), format_func=FREQUENCIES.get)
        next_charge = st.date_input("Próxima cobrança", value=date.today(), format="DD/MM/YYYY")
        category = select_model("Categoria", categories, key="subscription_category", optional=True)
        account = select_model("Conta", accounts, key="subscription_account", optional=True)
        card = select_model("Cartão", cards, key="subscription_card", optional=True)
        submitted = st.form_submit_button("Adicionar assinatura", type="primary", use_container_width=True)
    if submitted:
        if not name.strip() or amount is None:
            st.warning("Informe nome e valor.")
            return
        try:
            repository.create(
                Subscription,
                user_id=user.id,
                name=name.strip(),
                amount=amount,
                frequency=frequency,
                next_charge_date=next_charge,
                category_id=getattr(category, "id", None),
                account_id=getattr(account, "id", None),
                credit_card_id=getattr(card, "id", None),
                is_active=True,
            )
            notify_success("Assinatura adicionada")
            safe_rerun()
        except Exception as exc:
            friendly_error("Não foi possível adicionar a assinatura.", exc)
    if subscriptions:
        selected = st.selectbox("Gerenciar assinatura", subscriptions, format_func=lambda item: item.name)
        with st.form(f"edit_subscription_{selected.id}"):
            edit_name = st.text_input("Nome", value=selected.name, max_chars=140)
            edit_amount = money_input(
                "Valor",
                value=selected.amount,
                key=f"edit_subscription_amount_{selected.id}",
                minimum=Decimal("0.01"),
            )
            edit_frequency = st.selectbox(
                "Cobrança",
                tuple(FREQUENCIES),
                index=tuple(FREQUENCIES).index(selected.frequency),
                format_func=FREQUENCIES.get,
            )
            edit_next = st.date_input(
                "Próxima cobrança",
                value=selected.next_charge_date,
                format="DD/MM/YYYY",
            )
            saved = st.form_submit_button("Salvar alterações", use_container_width=True)
        if saved and edit_amount is not None:
            try:
                repository.update_fields(
                    Subscription,
                    selected.id,
                    {
                        "name": edit_name.strip(),
                        "amount": edit_amount,
                        "frequency": edit_frequency,
                        "next_charge_date": edit_next,
                    },
                    user_id=user.id,
                )
                notify_success("Assinatura atualizada")
                safe_rerun()
            except Exception as exc:
                friendly_error("Não foi possível atualizar a assinatura.", exc)
        confirmation_button(
            "Cancelar assinatura no controle",
            key=f"delete_subscription_{selected.id}",
            title="Remover assinatura?",
            message="Isso apenas remove a assinatura deste controle; não cancela o serviço no fornecedor.",
            on_confirm=repository.soft_delete,
            confirm_args=(Subscription, selected.id),
            confirm_kwargs={"user_id": user.id},
            success_message="Assinatura removida do controle",
        )


def _render_loans(repository: Any, user: Any, accounts: list[Any]) -> None:
    today = date.today()
    open_installments = repository.list_loan_installments(
        user.id, statuses=("pending", "overdue")
    )
    changed = False
    for installment in open_installments:
        expected = "overdue" if installment.due_date < today else "pending"
        if installment.status != expected:
            installment.status = expected
            changed = True
    if changed:
        repository.session.flush()

    summaries = repository.list_loan_summaries(user.id)
    active = [item for item in summaries if item.remaining_installments > 0]
    outstanding = sum((item.outstanding_amount for item in active), Decimal("0"))
    next_30 = sum(
        (
            installment.amount
            for installment in open_installments
            if installment.due_date <= today + timedelta(days=30)
        ),
        Decimal("0"),
    )
    debt_col, upcoming_col = st.columns(2)
    with debt_col:
        render_metric_card(
            "Saldo dos empréstimos",
            outstanding,
            tone="coral",
            hidden=privacy_enabled(),
        )
    with upcoming_col:
        render_metric_card(
            "Parcelas em 30 dias",
            next_30,
            tone="yellow",
            hidden=privacy_enabled(),
        )

    render_section_header(
        "Empréstimos mensais",
        subtitle="Parcelas pagas, meses restantes e saldo devedor",
    )
    if not summaries:
        st.info("Nenhum empréstimo cadastrado. Use Adicionar → Empréstimo para começar.")
        return

    for summary in summaries:
        loan = summary.loan
        next_item = summary.next_installment
        progress = (
            summary.paid_installments / loan.total_installments
            if loan.total_installments
            else 0
        )
        render_bill_card(
            loan.name,
            summary.outstanding_amount,
            due_label=(
                f"Próxima parcela {format_brl_date(next_item.due_date)}"
                if next_item
                else "Empréstimo quitado"
            ),
            status=(
                f"{summary.paid_installments}/{loan.total_installments} pagas · "
                f"faltam {summary.remaining_installments} mês(es)"
            ),
            category=f"Termina em {summary.end_date:%m/%Y}",
            account=loan.lender,
            icon="↘",
            hidden=privacy_enabled(),
        )
        st.progress(min(1.0, max(0.0, progress)))

    if not active:
        st.success("Todos os empréstimos estão quitados.")
        return
    selected = st.selectbox(
        "Empréstimo para agir",
        active,
        format_func=lambda item: (
            f"{item.loan.name} · próxima {item.next_installment.due_date:%d/%m/%Y}"
        ),
        key="loan_action_select",
    )
    payment_account = select_model(
        "Pagar próxima parcela com",
        accounts,
        key=f"loan_payment_account_{selected.loan.id}",
        default_id=selected.loan.account_id,
    )
    method = st.selectbox(
        "Forma de pagamento",
        ("pix", "debit", "boleto", "cash", "other"),
        format_func=PAYMENT_METHODS.get,
        key=f"loan_payment_method_{selected.loan.id}",
    )
    confirmation_button(
        "Pagar próxima parcela",
        key=f"pay_loan_{selected.next_installment.id}",
        title="Confirmar pagamento da parcela?",
        message=(
            f"Será registrada a parcela {selected.next_installment.installment_number}/"
            f"{selected.loan.total_installments} de {selected.loan.name}."
        ),
        on_confirm=repository.pay_loan_installment,
        confirm_args=(user.id, selected.next_installment.id),
        confirm_kwargs={
            "account_id": getattr(payment_account, "id", None),
            "payment_date": today,
            "payment_method": method,
        },
        success_message="Parcela do empréstimo paga",
        use_container_width=True,
    )
    with st.expander("Ver cronograma ou arquivar"):
        installments = repository.list_loan_installments(
            user.id, loan_id=selected.loan.id
        )
        for installment in installments:
            marker = "✓" if installment.status == "paid" else "○"
            st.caption(
                f"{marker} {installment.installment_number}/"
                f"{selected.loan.total_installments} · "
                f"{format_brl_date(installment.due_date)} · "
                f"{status_label(installment.status)}"
            )
        confirmation_button(
            "Arquivar empréstimo",
            key=f"archive_loan_{selected.loan.id}",
            title="Arquivar empréstimo?",
            message="O cronograma deixa de aparecer, mas o histórico permanece no banco.",
            on_confirm=repository.soft_delete,
            confirm_args=(Loan, selected.loan.id),
            confirm_kwargs={"user_id": user.id},
            success_message="Empréstimo arquivado",
        )


def render(repository: Any, user: Any, *, accounts: list[Any] | None = None) -> None:
    page_header("Contas e assinaturas", "Vencimentos previsíveis, sem alertas agressivos.", eyebrow="Próximos compromissos")
    section = st.segmented_control(
        "Área de contas",
        ("Em aberto", "Empréstimos", "Adicionar", "Recorrentes", "Assinaturas"),
        default="Em aberto",
        key="bills_section",
        selection_mode="single",
        width="stretch",
        label_visibility="collapsed",
    ) or "Em aberto"

    accounts = accounts if accounts is not None else repository.list_accounts(user.id)
    if section == "Em aberto":
        categories = repository.list_categories(user.id, kind="expense")
        _render_open_bills(repository, user, accounts, categories)
    elif section == "Adicionar":
        categories = repository.list_categories(user.id, kind="expense")
        _render_add_bill(repository, user, accounts, categories)
    elif section == "Empréstimos":
        _render_loans(repository, user, accounts)
    elif section == "Recorrentes":
        categories = repository.list_categories(user.id, kind="expense")
        _render_recurring(repository, user, accounts, categories)
    else:
        categories = repository.list_categories(user.id, kind="expense")
        cards = repository.list_credit_cards(user.id)
        _render_subscriptions(repository, user, accounts, categories, cards)
