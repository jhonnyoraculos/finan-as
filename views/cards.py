"""Cartões, faturas, parcelamentos e pagamento de fatura."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from components.cards import (
    render_credit_card,
    render_metric_card,
    render_section_header,
    render_transaction_card,
)
from components.dialogs import confirmation_button
from components.widgets import money_input, notify_success
from database.models import CreditCard, Transaction
from utils.dates import format_brl_date
from views.common import (
    friendly_error,
    page_header,
    privacy_enabled,
    safe_rerun,
    select_model,
    status_label,
)


CARD_COLORS = {
    "Azul profundo": "#425FAD",
    "Roxo suave": "#7258A8",
    "Laranja âmbar": "#A5673F",
    "Verde petróleo": "#356E6A",
    "Grafite": "#384052",
}


def _render_card_form(repository: Any, user: Any, accounts: list[Any]) -> None:
    render_section_header("Novo cartão", subtitle="A conta só será debitada ao pagar a fatura")
    with st.form("new_credit_card"):
        name = st.text_input("Nome", placeholder="Ex.: Nubank", max_chars=100)
        bank = st.text_input("Banco", max_chars=120)
        limit_total = money_input(
            "Limite total",
            key="new_card_limit",
            minimum=Decimal("0"),
        )
        day_col, due_col = st.columns(2)
        with day_col:
            closing_day = st.number_input("Fecha dia", 1, 31, 25)
        with due_col:
            due_day = st.number_input("Vence dia", 1, 31, 10)
        account = select_model(
            "Conta de pagamento",
            accounts,
            key="new_card_account",
            optional=True,
        )
        color_label = st.selectbox("Cor", list(CARD_COLORS))
        digits = st.text_input("Últimos 4 dígitos", max_chars=4, placeholder="Opcional")
        submitted = st.form_submit_button("Adicionar cartão", type="primary", use_container_width=True)
    if submitted:
        if not name.strip() or limit_total is None:
            st.warning("Informe nome e limite do cartão.")
            return
        if digits and (len(digits) != 4 or not digits.isdigit()):
            st.warning("Os últimos dígitos devem conter exatamente 4 números.")
            return
        try:
            repository.create_credit_card(
                user.id,
                name.strip(),
                limit_total,
                int(closing_day),
                int(due_day),
                bank=bank.strip() or None,
                payment_account_id=getattr(account, "id", None),
                color=CARD_COLORS[color_label],
                last_four_digits=digits or None,
            )
            notify_success("Cartão adicionado")
            safe_rerun()
        except Exception as exc:
            friendly_error("Não foi possível adicionar o cartão.", exc)


def _invoice_transactions(repository: Any, invoice_id: Any) -> list[Any]:
    return list(
        repository.session.scalars(
            select(Transaction)
            .options(joinedload(Transaction.category))
            .where(
                Transaction.invoice_id == invoice_id,
                Transaction.deleted_at.is_(None),
            )
            .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
        ).unique()
    )


def _render_invoices(repository: Any, user: Any, card: Any, accounts: list[Any]) -> None:
    invoices = repository.list_invoices(user.id, credit_card_id=card.id, limit=24)
    render_section_header("Faturas", subtitle="Aberta, fechada ou paga — sem dupla contagem")
    if not invoices:
        st.info("As faturas aparecem assim que você lança a primeira compra no cartão.")
        return
    invoice = st.selectbox(
        "Competência",
        invoices,
        format_func=lambda item: (
            f"{item.reference_month:%m/%Y} · {status_label(item.status)} · "
            f"vence {item.due_date:%d/%m}"
        ),
        key=f"invoice_select_{card.id}",
    )
    repository.recalculate_invoice_total(invoice.id, user_id=user.id)
    total_col, close_col, due_col = st.columns(3)
    with total_col:
        render_metric_card("Total", invoice.total_amount, tone="orange", hidden=privacy_enabled())
    with close_col:
        render_metric_card(
            "Fechamento",
            format_brl_date(invoice.closing_date),
            value_is_formatted=True,
            tone="neutral",
        )
    with due_col:
        render_metric_card(
            "Vencimento",
            format_brl_date(invoice.due_date),
            value_is_formatted=True,
            tone="yellow",
        )

    if invoice.status != "paid" and invoice.total_amount > 0:
        payment_account = select_model(
            "Pagar usando",
            accounts,
            key=f"invoice_account_{invoice.id}",
            formatter=lambda item: item.name,
        )
        confirmation_button(
            "Pagar fatura",
            key=f"pay_invoice_{invoice.id}",
            title="Confirmar pagamento",
            message=(
                "O valor será debitado da conta escolhida. As compras já registradas "
                "não serão contadas novamente como despesa."
            ),
            on_confirm=repository.pay_invoice,
            confirm_args=(user.id, invoice.id),
            confirm_kwargs={
                "account_id": getattr(payment_account, "id", None),
                "payment_date": date.today(),
            },
            confirm_label="Pagar agora",
            success_message="Fatura paga",
            use_container_width=True,
        )

    items = _invoice_transactions(repository, invoice.id)
    if items:
        st.caption(f"{len(items)} lançamento(s) nesta fatura")
        for transaction in items:
            render_transaction_card(
                transaction.description,
                transaction.amount,
                transaction_type="expense",
                date_label=format_brl_date(transaction.transaction_date),
                method="Crédito",
                category=getattr(transaction.category, "name", None),
                installments=(
                    f"{transaction.installment_number}/{transaction.installment_count}"
                    if transaction.installment_count and transaction.installment_count > 1
                    else None
                ),
                hidden=privacy_enabled(),
            )


def _render_installment_plans(repository: Any, user: Any, card: Any) -> None:
    plans = repository.list_installment_plans(
        user.id, credit_card_id=card.id, active_only=True
    )
    render_section_header(
        "Compras parceladas",
        subtitle="Veja quantas parcelas e meses ainda faltam",
    )
    if not plans:
        st.caption("Nenhuma compra parcelada ativa neste cartão.")
        return
    for plan in plans:
        progress = (
            plan.paid_installments / plan.total_installments
            if plan.total_installments
            else 0
        )
        render_transaction_card(
            plan.description,
            plan.remaining_amount,
            transaction_type="expense",
            date_label=(
                f"Próxima {format_brl_date(plan.next_due_date)}"
                if plan.next_due_date
                else "Concluída"
            ),
            method=f"Termina em {plan.end_date:%m/%Y}",
            category=f"Faltam {plan.remaining_installments} mês(es)",
            installments=f"{plan.paid_installments}/{plan.total_installments} pagas",
            hidden=privacy_enabled(),
        )
        st.progress(min(1.0, max(0.0, progress)))


def _render_manage_card(repository: Any, user: Any, cards: list[Any], accounts: list[Any]) -> None:
    if not cards:
        return
    render_section_header("Editar cartão")
    card = st.selectbox("Cartão", cards, format_func=lambda item: item.name, key="manage_card")
    with st.form(f"edit_card_{card.id}"):
        name = st.text_input("Nome", value=card.name, max_chars=100)
        bank = st.text_input("Banco", value=card.bank or "", max_chars=120)
        limit_total = money_input("Limite", value=card.credit_limit, key=f"edit_limit_{card.id}")
        closing_col, due_col = st.columns(2)
        with closing_col:
            closing_day = st.number_input("Fecha dia", 1, 31, int(card.closing_day))
        with due_col:
            due_day = st.number_input("Vence dia", 1, 31, int(card.due_day))
        payment_account = select_model(
            "Conta de pagamento",
            accounts,
            key=f"edit_card_account_{card.id}",
            optional=True,
            default_id=card.payment_account_id,
        )
        saved = st.form_submit_button("Salvar alterações", use_container_width=True)
    if saved and limit_total is not None:
        try:
            repository.update_fields(
                CreditCard,
                card.id,
                {
                    "name": name.strip(),
                    "bank": bank.strip() or None,
                    "credit_limit": limit_total,
                    "closing_day": int(closing_day),
                    "due_day": int(due_day),
                    "payment_account_id": getattr(payment_account, "id", None),
                },
                user_id=user.id,
            )
            notify_success("Cartão atualizado")
            safe_rerun()
        except Exception as exc:
            friendly_error("Não foi possível atualizar o cartão.", exc)
    confirmation_button(
        "Arquivar cartão",
        key=f"delete_card_{card.id}",
        title="Arquivar cartão?",
        message="O histórico será preservado e o cartão deixará de aparecer nos novos lançamentos.",
        on_confirm=repository.soft_delete,
        confirm_args=(CreditCard, card.id),
        confirm_kwargs={"user_id": user.id},
        success_message="Cartão arquivado",
    )


def render(repository: Any, user: Any) -> None:
    page_header("Cartões", "Limites e faturas com o efeito correto no saldo.", eyebrow="Apple Wallet, do seu jeito")
    accounts = repository.list_accounts(user.id)
    cards = repository.list_credit_cards(user.id)
    summaries = repository.list_card_summaries(user.id)

    overview_tab, add_tab, manage_tab = st.tabs(("Visão geral", "Adicionar", "Gerenciar"))
    with overview_tab:
        if not summaries:
            st.info("Adicione um cartão para acompanhar faturas e parcelamentos.")
        for summary in summaries:
            card = summary.card
            render_credit_card(
                card.name,
                available=summary.available_limit,
                used=summary.open_amount,
                limit_total=card.credit_limit,
                bank=card.bank,
                closing_label=f"Fecha dia {card.closing_day}",
                due_label=f"Vence dia {card.due_day}",
                color=card.color,
                hidden=privacy_enabled(),
            )
        if cards:
            selected = st.selectbox(
                "Detalhar cartão",
                cards,
                format_func=lambda item: item.name,
                key="card_details_select",
                label_visibility="collapsed",
            )
            _render_installment_plans(repository, user, selected)
            _render_invoices(repository, user, selected, accounts)
    with add_tab:
        _render_card_form(repository, user, accounts)
    with manage_tab:
        _render_manage_card(repository, user, cards, accounts)
