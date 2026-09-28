"""Fluxo rápido de lançamento, otimizado para uso com uma mão no celular."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import streamlit as st

from components.cards import render_section_header, render_transaction_card
from components.dialogs import confirmation_button
from components.widgets import money_input, notify_success, transaction_type_input
from database.models import FavoriteTransaction, RecurringTransaction
from services.application_service import post_quick_transaction
from utils.dates import add_months, add_years
from views.common import (
    PAYMENT_METHODS,
    friendly_error,
    page_header,
    safe_rerun,
    select_model,
)


TYPE_MAP = {
    "despesa": "expense",
    "receita": "income",
    "transferencia": "transfer",
    "transferência": "transfer",
    "emprestimo": "loan",
    "empréstimo": "loan",
}


def _next_date(start: date, frequency: str) -> date:
    if frequency == "weekly":
        return start + timedelta(weeks=1)
    if frequency == "yearly":
        return add_years(start, 1)
    return add_months(start, 1, preferred_day=start.day)


def _clear_form() -> None:
    for key in list(st.session_state):
        if key.startswith("quick_"):
            del st.session_state[key]


def _render_favorites(repository: Any, user: Any) -> None:
    favorites = list(
        repository.session.query(FavoriteTransaction)
        .filter(
            FavoriteTransaction.user_id == user.id,
            FavoriteTransaction.deleted_at.is_(None),
        )
        .order_by(FavoriteTransaction.created_at.desc())
        .limit(4)
    )
    if not favorites:
        return
    render_section_header("Favoritos", subtitle="Toque para preencher seu lançamento")
    columns = st.columns(min(4, len(favorites)))
    for column, favorite in zip(columns, favorites):
        with column:
            if st.button(
                favorite.name,
                key=f"favorite_{favorite.id}",
                use_container_width=True,
                help=favorite.description,
            ):
                _clear_form()
                st.session_state["quick_description"] = favorite.description
                if favorite.amount is not None:
                    from components.widgets import format_brl

                    st.session_state["quick_amount"] = format_brl(favorite.amount)
                st.session_state["quick_type"] = {
                    "expense": "despesa",
                    "income": "receita",
                    "transfer": "transferencia",
                }.get(favorite.transaction_type, "despesa")
                if favorite.category_id is not None:
                    st.session_state["quick_category"] = favorite.category_id
                if favorite.account_id is not None:
                    st.session_state["quick_account"] = favorite.account_id
                if favorite.credit_card_id is not None:
                    st.session_state["quick_card"] = favorite.credit_card_id
                st.session_state["quick_favorite_method"] = favorite.payment_method
                safe_rerun()
    with st.expander("Gerenciar favoritos"):
        selected = st.selectbox(
            "Favorito",
            favorites,
            format_func=lambda item: item.name,
            key="favorite_manage_select",
        )
        confirmation_button(
            "Excluir favorito",
            key=f"delete_favorite_{selected.id}",
            title="Excluir favorito?",
            message="Isso remove apenas o atalho; movimentações já criadas não mudam.",
            on_confirm=repository.soft_delete,
            confirm_args=(FavoriteTransaction, selected.id),
            confirm_kwargs={"user_id": user.id},
            success_message="Favorito excluído",
        )


def _render_loan_form(repository: Any, user: Any, accounts: list[Any]) -> None:
    """Render the dedicated monthly-loan entry flow."""

    from services.loan_service import generate_loan_schedule
    from utils.currency import format_brl_currency

    categories = repository.list_categories(user.id, kind="expense")
    st.info(
        "Cadastre o valor contratado e o total financiado. O empréstimo fica "
        "separado do saldo disponível; somente as parcelas pagas reduzem a conta."
    )
    with st.form("quick_new_loan"):
        name = st.text_input(
            "Nome do empréstimo",
            placeholder="Ex.: Empréstimo pessoal",
            max_chars=140,
        )
        lender = st.text_input("Banco ou credor", max_chars=140)
        received_col, total_col = st.columns(2)
        with received_col:
            principal = money_input(
                "Valor contratado",
                key="quick_loan_principal",
                minimum=Decimal("0.01"),
            )
        with total_col:
            total = money_input(
                "Total a pagar",
                key="quick_loan_total",
                minimum=Decimal("0.01"),
            )
        count_col, paid_col = st.columns(2)
        with count_col:
            installment_count = st.number_input(
                "Quantidade de parcelas",
                min_value=1,
                max_value=600,
                value=12,
                step=1,
            )
        with paid_col:
            paid_installments = st.number_input(
                "Parcelas já pagas",
                min_value=0,
                max_value=int(installment_count),
                value=0,
                step=1,
            )
        first_due = st.date_input(
            "Primeiro vencimento",
            value=add_months(date.today(), 1),
            format="DD/MM/YYYY",
        )
        account = select_model(
            "Conta que pagará as parcelas",
            accounts,
            key="quick_loan_account",
            optional=True,
        )
        category = select_model(
            "Categoria das parcelas",
            categories,
            key="quick_loan_category",
            optional=True,
        )
        record_receipt = st.checkbox(
            "Adicionar o valor contratado ao saldo disponível",
            value=False,
            help="Ative somente se esse dinheiro realmente entrou na conta selecionada.",
        )
        receipt_date = st.date_input(
            "Data de entrada do valor (usada somente se a opção acima estiver ativa)",
            value=date.today(),
            format="DD/MM/YYYY",
        )
        interest_rate = st.number_input(
            "Taxa de juros (% ao mês, opcional)",
            min_value=0.0,
            max_value=1000.0,
            value=0.0,
            step=0.01,
            format="%.2f",
        )
        notes = st.text_area("Observação", max_chars=2000)
        if total is not None and total > 0:
            try:
                schedule = generate_loan_schedule(
                    total,
                    int(installment_count),
                    first_due,
                    paid_installments=int(paid_installments),
                )
                remaining = int(installment_count) - int(paid_installments)
                st.caption(
                    f"{installment_count}x de aproximadamente "
                    f"{format_brl_currency(schedule[0].amount)} · "
                    f"faltam {remaining} mês(es) · termina em "
                    f"{schedule[-1].due_date:%m/%Y}"
                )
            except ValueError:
                pass
        submitted = st.form_submit_button(
            "Adicionar empréstimo", type="primary", use_container_width=True
        )
    if not submitted:
        return
    if not name.strip() or principal is None or total is None:
        st.warning("Informe nome, valor contratado e total a pagar.")
        return
    if record_receipt and account is None:
        st.warning("Selecione a conta na qual o valor do empréstimo entrou.")
        return
    try:
        with repository.session.begin_nested():
            repository.create_loan(
                user.id,
                name.strip(),
                principal,
                total,
                int(installment_count),
                first_due,
                lender=lender.strip() or None,
                paid_installments=int(paid_installments),
                account_id=getattr(account, "id", None),
                category_id=getattr(category, "id", None),
                interest_rate=Decimal(str(interest_rate)),
                record_disbursement=record_receipt,
                disbursement_date=receipt_date,
                notes=notes.strip() or None,
            )
        notify_success("Empréstimo adicionado com o cronograma mensal")
        st.session_state["_clear_quick_on_load"] = True
        safe_rerun()
    except Exception as exc:
        friendly_error("Não foi possível adicionar o empréstimo.", exc)


def render(repository: Any, user: Any, *, accounts: list[Any] | None = None) -> None:
    if st.session_state.pop("_clear_quick_on_load", False):
        _clear_form()
    page_header(
        "Adicionar",
        "Registre uma movimentação em poucos segundos.",
        eyebrow="Ação rápida",
    )
    _render_favorites(repository, user)

    selected_type = transaction_type_input(
        key="quick_type",
        options=("despesa", "receita", "transferencia", "emprestimo"),
    )
    transaction_type = TYPE_MAP[selected_type]
    accounts = accounts if accounts is not None else repository.list_accounts(user.id)
    if transaction_type == "loan":
        _render_loan_form(repository, user, accounts)
        return
    amount = money_input(
        "Valor",
        value=Decimal("0"),
        key="quick_amount",
        minimum=Decimal("0.01"),
        help="Aceita 1234,56 ou 1.234,56.",
    )
    description = st.text_input(
        "Descrição",
        key="quick_description",
        placeholder="Ex.: Mercado",
        max_chars=240,
    )

    category_kind = "income" if transaction_type == "income" else "expense"
    categories = repository.list_categories(user.id, kind=category_kind)
    cards = repository.list_credit_cards(user.id)

    category = None
    account = None
    destination = None
    card = None
    payment_method = "transfer" if transaction_type == "transfer" else "pix"
    installment_count = 1

    if transaction_type == "transfer":
        col_source, col_destination = st.columns(2)
        with col_source:
            account = select_model("De", accounts, key="quick_source_account")
        destination_options = [item for item in accounts if account is None or item.id != account.id]
        with col_destination:
            destination = select_model("Para", destination_options, key="quick_destination_account")
    else:
        category = select_model(
            "Categoria",
            categories,
            key="quick_category",
            optional=True,
            formatter=lambda item: f"{item.icon or '•'} {item.name}",
        )
        allowed_methods = (
            ("pix", "cash", "transfer", "other")
            if transaction_type == "income"
            else ("pix", "cash", "debit", "credit", "boleto", "other")
        )
        favorite_method = st.session_state.pop("quick_favorite_method", None)
        method_index = allowed_methods.index(favorite_method) if favorite_method in allowed_methods else 0
        payment_method = st.selectbox(
            "Pagamento",
            allowed_methods,
            index=method_index,
            key="quick_payment_method",
            format_func=PAYMENT_METHODS.get,
        )
        if payment_method == "credit":
            card = select_model(
                "Cartão",
                cards,
                key="quick_card",
                formatter=lambda item: f"{item.name} · {item.bank or 'Cartão'}",
            )
            installment_count = st.number_input(
                "Parcelas",
                min_value=1,
                max_value=60,
                value=1,
                step=1,
                key="quick_installments",
            )
            if installment_count > 1 and amount:
                from services.installment_service import split_installment_amounts
                from utils.currency import format_brl_currency

                first = split_installment_amounts(amount, int(installment_count))[0]
                st.caption(f"{installment_count}x · primeira parcela {format_brl_currency(first)}")
        else:
            account = select_model("Conta", accounts, key="quick_account")

    tx_date = st.date_input("Data", value=date.today(), key="quick_date", format="DD/MM/YYYY")
    with st.expander("Mais opções"):
        notes = st.text_area(
            "Observação",
            key="quick_notes",
            max_chars=2000,
            placeholder="Opcional",
        )
        recurring = st.checkbox(
            "Repetir automaticamente",
            key="quick_recurring",
            disabled=transaction_type == "transfer" or payment_method == "credit",
        )
        frequency = st.selectbox(
            "Frequência",
            ("weekly", "monthly", "yearly"),
            format_func={"weekly": "Semanal", "monthly": "Mensal", "yearly": "Anual"}.get,
            key="quick_frequency",
            disabled=not recurring,
        )
        is_refund = st.checkbox(
            "Marcar como reembolso",
            key="quick_refund",
            disabled=transaction_type != "income",
        )
        refunded_transaction = None
        if is_refund and transaction_type == "income":
            expenses = repository.list_transactions(
                user.id, transaction_type="expense", page_size=50
            ).items
            refunded_transaction = select_model(
                "Despesa reembolsada",
                expenses,
                key="quick_refunded_transaction",
                optional=True,
                formatter=lambda item: f"{item.description} · {item.transaction_date:%d/%m/%Y}",
            )
        save_favorite = st.checkbox("Salvar como favorito", key="quick_save_favorite")

    action_label = {
        "expense": "Adicionar despesa",
        "income": "Adicionar receita",
        "transfer": "Transferir",
    }[transaction_type]
    if st.button(action_label, type="primary", use_container_width=True, key="quick_submit"):
        if amount is None or amount <= 0:
            st.warning("Informe um valor maior que zero.")
            return
        if not description.strip() and transaction_type != "transfer":
            st.warning("Informe uma descrição curta.")
            return
        if transaction_type == "transfer" and (account is None or destination is None):
            st.warning("Selecione as duas contas da transferência.")
            return
        if transaction_type != "transfer" and payment_method != "credit" and account is None:
            st.warning("Selecione a conta da movimentação.")
            return
        if payment_method == "credit" and card is None:
            st.warning("Selecione o cartão da compra.")
            return
        try:
            with repository.session.begin_nested():
                created = post_quick_transaction(
                    repository,
                    user_id=user.id,
                    transaction_type=transaction_type,
                    description=description.strip() or "Transferência",
                    amount=amount,
                    transaction_date=tx_date,
                    account_id=getattr(account, "id", None),
                    destination_account_id=getattr(destination, "id", None),
                    category_id=getattr(category, "id", None),
                    payment_method=payment_method,
                    credit_card=card,
                    installment_count=int(installment_count),
                    notes=notes.strip() or None,
                    is_refund=is_refund,
                    refunded_transaction_id=getattr(refunded_transaction, "id", None),
                )
                if recurring:
                    repository.create(
                        RecurringTransaction,
                        user_id=user.id,
                        description=description.strip(),
                        amount=amount,
                        transaction_type=transaction_type,
                        frequency=frequency,
                        start_date=tx_date,
                        next_run_date=_next_date(tx_date, frequency),
                        category_id=getattr(category, "id", None),
                        account_id=getattr(account, "id", None),
                        payment_method=payment_method,
                        is_active=True,
                    )
                if save_favorite:
                    repository.create(
                        FavoriteTransaction,
                        user_id=user.id,
                        name=(description.strip() or "Transferência")[:100],
                        description=description.strip() or "Transferência",
                        amount=amount,
                        transaction_type=transaction_type,
                        category_id=getattr(category, "id", None),
                        account_id=getattr(account, "id", None),
                        credit_card_id=getattr(card, "id", None),
                        payment_method=payment_method,
                        notes=notes.strip() or None,
                    )
            notify_success(
                "Transferência concluída"
                if transaction_type == "transfer"
                else f"{'Receita' if transaction_type == 'income' else 'Despesa'} adicionada"
            )
            if payment_method == "credit" and len(created) > 1:
                st.caption(f"Compra distribuída em {len(created)} faturas, sem reduzir a conta agora.")
            st.session_state["_clear_quick_on_load"] = True
            st.session_state["active_page"] = "home"
            safe_rerun()
        except Exception as exc:
            friendly_error("Não foi possível salvar a movimentação.", exc)

    if amount and description.strip():
        render_section_header("Prévia")
        render_transaction_card(
            description.strip(),
            amount,
            transaction_type=transaction_type,
            date_label="Hoje" if tx_date == date.today() else tx_date.strftime("%d/%m/%Y"),
            method=PAYMENT_METHODS.get(payment_method),
            category=getattr(category, "name", None),
            installments=(f"{int(installment_count)}x" if int(installment_count) > 1 else None),
            hidden=bool(st.session_state.get("privacy_mode")),
        )
