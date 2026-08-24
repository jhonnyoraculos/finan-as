"""Histórico pesquisável, paginação, edição, soft delete e CSV."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import streamlit as st

from components.cards import render_section_header, render_transaction_card
from components.dialogs import confirmation_button
from components.widgets import money_input, notify_success
from database.models import Transaction
from utils.dates import format_brl_date
from views.common import (
    PAYMENT_METHODS,
    TRANSACTION_TYPES,
    friendly_error,
    page_header,
    privacy_enabled,
    safe_rerun,
    select_model,
    status_label,
)


def _csv_safe(value: Any) -> str:
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text


def _export_csv(items: list[Any]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        (
            "data",
            "descricao",
            "tipo",
            "valor",
            "categoria",
            "conta",
            "cartao",
            "pagamento",
            "status",
            "observacao",
        )
    )
    for item in items:
        writer.writerow(
            (
                item.transaction_date.strftime("%d/%m/%Y"),
                _csv_safe(item.description),
                TRANSACTION_TYPES.get(item.transaction_type, item.transaction_type),
                f"{item.amount:.2f}".replace(".", ","),
                _csv_safe(getattr(item.category, "name", "")),
                _csv_safe(getattr(item.account, "name", "")),
                _csv_safe(getattr(item.credit_card, "name", "")),
                PAYMENT_METHODS.get(item.payment_method or "", item.payment_method or ""),
                status_label(item.status),
                _csv_safe(item.notes),
            )
        )
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _delete_transaction(repository: Any, user_id: Any, transaction: Any) -> None:
    """Soft-delete a complete transfer pair or a single financial record."""

    touched_invoice = transaction.invoice_id
    if transaction.transfer_group_id:
        pairs = (
            repository.session.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.transfer_group_id == transaction.transfer_group_id,
                Transaction.deleted_at.is_(None),
            )
            .all()
        )
        for pair in pairs:
            repository.soft_delete(Transaction, pair.id, user_id=user_id)
    else:
        repository.soft_delete(Transaction, transaction.id, user_id=user_id)
    if touched_invoice:
        repository.recalculate_invoice_total(touched_invoice, user_id=user_id)


def _render_editor(repository: Any, user: Any, items: list[Any]) -> None:
    if not items:
        return
    render_section_header("Editar ou excluir", subtitle="Exclusões ficam preservadas para restauração futura")
    transaction = st.selectbox(
        "Movimentação",
        items,
        format_func=lambda item: f"{item.transaction_date:%d/%m} · {item.description}",
        key="history_edit_select",
    )
    if transaction.transaction_type == "transfer":
        st.caption("Transferências vinculadas são excluídas em conjunto. Para editar, recrie a transferência.")
    else:
        categories = repository.list_categories(user.id, kind=transaction.transaction_type)
        accounts = repository.list_accounts(user.id)
        with st.form(f"edit_transaction_{transaction.id}"):
            description = st.text_input("Descrição", value=transaction.description, max_chars=240)
            amount = money_input(
                "Valor",
                value=transaction.amount,
                key=f"history_edit_amount_{transaction.id}",
                minimum=Decimal("0.01"),
            )
            tx_date = st.date_input(
                "Data",
                value=transaction.transaction_date,
                format="DD/MM/YYYY",
            )
            category = select_model(
                "Categoria",
                categories,
                key=f"history_edit_category_{transaction.id}",
                optional=True,
                default_id=transaction.category_id,
                formatter=lambda item: item.name,
            )
            account = None
            if transaction.credit_card_id is None:
                account = select_model(
                    "Conta",
                    accounts,
                    key=f"history_edit_account_{transaction.id}",
                    optional=True,
                    default_id=transaction.account_id,
                )
            editable_statuses = ("paid", "pending")
            edit_status = st.selectbox(
                "Situação",
                editable_statuses,
                index=editable_statuses.index(
                    transaction.status if transaction.status in editable_statuses else "paid"
                ),
                format_func={"paid": "Efetivada", "pending": "Pendente"}.get,
                disabled=transaction.credit_card_id is not None,
            )
            notes = st.text_area("Observação", value=transaction.notes or "", max_chars=2000)
            submitted = st.form_submit_button("Salvar alterações", use_container_width=True)
        if submitted and amount is not None:
            if not description.strip():
                st.warning("A descrição não pode ficar vazia.")
            else:
                try:
                    repository.update_fields(
                        Transaction,
                        transaction.id,
                        {
                            "description": description.strip(),
                            "amount": amount,
                            "transaction_date": tx_date,
                            "competence_date": (
                                transaction.competence_date
                                if transaction.credit_card_id is not None
                                else tx_date
                            ),
                            "category_id": getattr(category, "id", None),
                            "account_id": (
                                transaction.account_id
                                if transaction.credit_card_id is not None
                                else getattr(account, "id", None)
                            ),
                            "notes": notes.strip() or None,
                            "status": (
                                transaction.status
                                if transaction.credit_card_id is not None
                                else edit_status
                            ),
                            "paid_at": (
                                transaction.paid_at
                                if transaction.credit_card_id is not None
                                else (
                                    datetime.now(timezone.utc)
                                    if edit_status == "paid" and transaction.paid_at is None
                                    else None if edit_status == "pending" else transaction.paid_at
                                )
                            ),
                        },
                        user_id=user.id,
                    )
                    if transaction.invoice_id:
                        repository.recalculate_invoice_total(transaction.invoice_id, user_id=user.id)
                    notify_success("Movimentação atualizada")
                    safe_rerun()
                except Exception as exc:
                    friendly_error("Não foi possível atualizar a movimentação.", exc)
    confirmation_button(
        "Excluir movimentação",
        key=f"delete_transaction_{transaction.id}",
        title="Excluir movimentação?",
        message=(
            "Ela deixará de afetar saldos e relatórios, mas continuará preservada no banco."
            if not transaction.transfer_group_id
            else "As duas pontas vinculadas da transferência serão excluídas juntas."
        ),
        on_confirm=_delete_transaction,
        confirm_args=(repository, user.id, transaction),
        success_message="Movimentação excluída",
    )


def render(repository: Any, user: Any) -> None:
    page_header("Histórico", "Pesquise, filtre e cuide de cada movimentação.", eyebrow="Tudo em um lugar")
    accounts = repository.list_accounts(user.id)
    categories = repository.list_categories(user.id)
    cards = repository.list_credit_cards(user.id)

    with st.expander("Pesquisar e filtrar", expanded=True):
        search = st.text_input("Pesquisar", placeholder="Mercado, salário, internet…", key="history_search")
        period_col, type_col = st.columns(2)
        with period_col:
            period = st.selectbox(
                "Período",
                (30, 90, 180, 365, 0),
                format_func={30: "30 dias", 90: "3 meses", 180: "6 meses", 365: "1 ano", 0: "Tudo"}.get,
                key="history_period",
            )
        with type_col:
            tx_type = st.selectbox(
                "Tipo",
                (None, "income", "expense", "transfer"),
                format_func=lambda item: "Todos" if item is None else TRANSACTION_TYPES[item],
                key="history_type",
            )
        account = select_model("Conta", accounts, key="history_account", optional=True)
        category = select_model("Categoria", categories, key="history_category", optional=True)
        card = select_model("Cartão", cards, key="history_card", optional=True)
        method = st.selectbox(
            "Pagamento",
            (None, *PAYMENT_METHODS),
            format_func=lambda item: "Todos" if item is None else PAYMENT_METHODS[item],
            key="history_method",
        )
        min_col, max_col = st.columns(2)
        with min_col:
            minimum = money_input("Valor mínimo", None, key="history_min", required=False)
        with max_col:
            maximum = money_input("Valor máximo", None, key="history_max", required=False)

    current_page = int(st.session_state.get("history_page", 1))
    start = date.today() - timedelta(days=int(period)) if period else None
    result = repository.list_transactions(
        user.id,
        page=current_page,
        page_size=20,
        start_date=start,
        account_id=getattr(account, "id", None),
        category_id=getattr(category, "id", None),
        credit_card_id=getattr(card, "id", None),
        transaction_type=tx_type,
        payment_method=method,
        min_amount=minimum,
        max_amount=maximum,
        search=search.strip() or None,
    )
    st.caption(f"{result.total} resultado(s) · página {result.page} de {max(result.pages, 1)}")
    if result.items:
        for transaction in result.items:
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
                hidden=privacy_enabled(),
            )
        prev_col, page_col, next_col = st.columns((1, 2, 1))
        with prev_col:
            if st.button("←", disabled=not result.has_previous, key="history_previous", use_container_width=True):
                st.session_state["history_page"] = current_page - 1
                safe_rerun()
        with page_col:
            st.caption(f"Página {result.page}")
        with next_col:
            if st.button("→", disabled=not result.has_next, key="history_next", use_container_width=True):
                st.session_state["history_page"] = current_page + 1
                safe_rerun()

        export_result = repository.list_transactions(
            user.id,
            page=1,
            page_size=100,
            start_date=start,
            account_id=getattr(account, "id", None),
            category_id=getattr(category, "id", None),
            credit_card_id=getattr(card, "id", None),
            transaction_type=tx_type,
            payment_method=method,
            min_amount=minimum,
            max_amount=maximum,
            search=search.strip() or None,
        )
        st.download_button(
            "Exportar resultados em CSV",
            data=_export_csv(export_result.items),
            file_name=f"movimentacoes_{date.today():%Y-%m-%d}.csv",
            mime="text/csv",
            use_container_width=True,
        )
        if result.total > 100:
            st.caption("A exportação rápida contém os 100 resultados mais recentes do filtro.")

        with st.expander("Visualização em tabela (desktop)"):
            st.dataframe(
                [
                    {
                        "Data": item.transaction_date.strftime("%d/%m/%Y"),
                        "Descrição": item.description,
                        "Tipo": TRANSACTION_TYPES.get(item.transaction_type),
                        "Valor": float(item.amount),
                        "Status": status_label(item.status),
                    }
                    for item in result.items
                ],
                hide_index=True,
                use_container_width=True,
            )
        _render_editor(repository, user, result.items)
    else:
        st.info("Nenhuma movimentação combina com esses filtros.")
