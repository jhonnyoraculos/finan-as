"""Preferências, cadastros-base, privacidade e exportação de backup."""

from __future__ import annotations

import csv
import io
import os
import zipfile
from datetime import date
from typing import Any

import streamlit as st
from sqlalchemy import inspect as sa_inspect, select

from components.cards import render_account_card, render_metric_card, render_section_header
from components.dialogs import confirmation_button
from components.widgets import money_input, notify_success
from database.models import Account, Category, MODEL_BY_TABLE, User
from database.seed import seed_demo_data
from utils.dates import format_brl_date
from views.common import (
    ACCOUNT_TYPES,
    friendly_error,
    page_header,
    privacy_enabled,
    safe_rerun,
    select_model,
)


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text


def _backup_zip(repository: Any, user_id: Any) -> bytes:
    """Build one CSV per owned table without loading unrelated users."""

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for table_name, model in sorted(MODEL_BY_TABLE.items()):
            if not hasattr(model, "user_id"):
                continue
            records = list(
                repository.session.scalars(
                    select(model).where(model.user_id == user_id)  # type: ignore[attr-defined]
                )
            )
            columns = [column.key for column in sa_inspect(model).columns]
            text_output = io.StringIO(newline="")
            writer = csv.writer(text_output, delimiter=";")
            writer.writerow(columns)
            for record in records:
                writer.writerow([_csv_cell(getattr(record, column)) for column in columns])
            archive.writestr(f"{table_name}.csv", "\ufeff" + text_output.getvalue())
    return output.getvalue()


def _render_profile(repository: Any, user: Any, accounts: list[Any]) -> None:
    settings = repository.get_settings(user.id)
    categories = repository.list_categories(user.id)
    render_section_header("Preferências")
    session_privacy = privacy_enabled()
    st.caption(
        "Modo privacidade ativo nesta sessão."
        if session_privacy
        else "Use o controle ‘Ocultar valores’ no topo para ativar a privacidade."
    )
    with st.form("profile_settings"):
        name = st.text_input("Seu nome", value=user.name, max_chars=120)
        currency = st.selectbox("Moeda", ("BRL",), disabled=True)
        first_day = st.number_input(
            "Primeiro dia do mês financeiro",
            min_value=1,
            max_value=28,
            value=int(settings.financial_month_start_day),
        )
        default_account = select_model(
            "Conta padrão",
            accounts,
            key="settings_default_account",
            optional=True,
            default_id=settings.default_account_id,
        )
        default_category = select_model(
            "Categoria padrão",
            categories,
            key="settings_default_category",
            optional=True,
            default_id=settings.default_category_id,
        )
        st.selectbox("Tema", ("Dark Liquid Glass",), disabled=True)
        submitted = st.form_submit_button("Salvar preferências", type="primary", use_container_width=True)
    st.caption("Light e OLED estão previstos; nesta versão o tema é Dark Liquid Glass.")
    if submitted:
        if not name.strip():
            st.warning("Informe um nome.")
            return
        try:
            repository.update_fields(User, user.id, {"name": name.strip()})
            repository.update_settings(
                user.id,
                currency=currency,
                financial_month_start_day=int(first_day),
                default_account_id=getattr(default_account, "id", None),
                default_category_id=getattr(default_category, "id", None),
                privacy_mode=session_privacy,
                theme="dark_liquid",
            )
            notify_success("Preferências salvas")
            safe_rerun()
        except Exception as exc:
            friendly_error("Não foi possível salvar as preferências.", exc)


def _render_accounts(repository: Any, user: Any) -> None:
    balances = repository.get_account_balances(user.id)
    render_section_header("Contas", subtitle="O saldo é derivado; compras em fatura não saem daqui")
    for item in balances:
        account = item.account
        render_account_card(
            account.name,
            item.balance,
            institution=account.institution,
            account_type=ACCOUNT_TYPES.get(account.account_type),
            icon=account.icon or "◉",
            color=account.color,
            hidden=privacy_enabled(),
        )
    with st.form("new_account"):
        name = st.text_input("Nome da conta", placeholder="Conta principal", max_chars=100)
        institution = st.text_input("Instituição", max_chars=120)
        account_type = st.selectbox("Tipo", tuple(ACCOUNT_TYPES), format_func=ACCOUNT_TYPES.get)
        initial = money_input("Saldo inicial", key="account_initial", allow_negative=True)
        color = st.color_picker("Cor", "#6C9EFF")
        submitted = st.form_submit_button("Adicionar conta", type="primary", use_container_width=True)
    if submitted:
        if not name.strip() or initial is None:
            st.warning("Informe nome e saldo inicial.")
        else:
            try:
                repository.create_account(
                    user.id,
                    name.strip(),
                    initial_balance=initial,
                    institution=institution.strip() or None,
                    account_type=account_type,
                    icon="💵" if account_type == "cash" else "◉",
                    color=color,
                )
                notify_success("Conta adicionada")
                safe_rerun()
            except Exception as exc:
                friendly_error("Não foi possível adicionar a conta.", exc)
    accounts = [item.account for item in balances]
    if accounts:
        selected = st.selectbox("Editar conta", accounts, format_func=lambda item: item.name)
        with st.form(f"edit_account_{selected.id}"):
            edit_name = st.text_input("Nome", value=selected.name, max_chars=100)
            edit_institution = st.text_input("Instituição", value=selected.institution or "", max_chars=120)
            edit_type = st.selectbox(
                "Tipo",
                tuple(ACCOUNT_TYPES),
                index=list(ACCOUNT_TYPES).index(selected.account_type),
                format_func=ACCOUNT_TYPES.get,
            )
            edit_color = st.color_picker("Cor", selected.color or "#6C9EFF")
            saved = st.form_submit_button("Salvar alterações", use_container_width=True)
        if saved:
            try:
                repository.update_fields(
                    Account,
                    selected.id,
                    {
                        "name": edit_name.strip(),
                        "institution": edit_institution.strip() or None,
                        "account_type": edit_type,
                        "color": edit_color,
                    },
                    user_id=user.id,
                )
                notify_success("Conta atualizada")
                safe_rerun()
            except Exception as exc:
                friendly_error("Não foi possível atualizar a conta.", exc)
        confirmation_button(
            "Arquivar conta",
            key=f"delete_account_{selected.id}",
            title="Arquivar conta?",
            message="O histórico será preservado. A conta deixará de aceitar novos lançamentos.",
            on_confirm=repository.soft_delete,
            confirm_args=(Account, selected.id),
            confirm_kwargs={"user_id": user.id},
            success_message="Conta arquivada",
        )


def _render_categories(repository: Any, user: Any) -> None:
    categories = repository.list_categories(user.id)
    render_section_header("Categorias", subtitle=f"{len(categories)} categoria(s) ativa(s)")
    if categories:
        st.dataframe(
            [
                {
                    "Ícone": item.icon or "•",
                    "Nome": item.name,
                    "Uso": {"income": "Receitas", "expense": "Despesas", "both": "Ambos"}.get(item.kind),
                    "Cor": item.color or "",
                }
                for item in categories
            ],
            hide_index=True,
            use_container_width=True,
        )
    with st.form("new_category"):
        name = st.text_input("Nome", max_chars=80)
        kind = st.selectbox(
            "Uso",
            ("expense", "income", "both"),
            format_func={"expense": "Despesas", "income": "Receitas", "both": "Ambos"}.get,
        )
        icon = st.text_input("Ícone", value="•", max_chars=8)
        color = st.color_picker("Cor", "#8290A8")
        submitted = st.form_submit_button("Criar categoria", type="primary", use_container_width=True)
    if submitted:
        if not name.strip():
            st.warning("Informe o nome da categoria.")
        else:
            try:
                repository.create_category(
                    user.id,
                    name.strip(),
                    kind=kind,
                    icon=icon.strip() or "•",
                    color=color,
                )
                notify_success("Categoria criada")
                safe_rerun()
            except Exception as exc:
                friendly_error("Não foi possível criar a categoria.", exc)
    if categories:
        selected = st.selectbox("Editar categoria", categories, format_func=lambda item: item.name)
        with st.form(f"edit_category_{selected.id}"):
            edit_name = st.text_input("Nome", value=selected.name, max_chars=80)
            edit_kind = st.selectbox(
                "Uso",
                ("expense", "income", "both"),
                index=("expense", "income", "both").index(selected.kind),
                format_func={"expense": "Despesas", "income": "Receitas", "both": "Ambos"}.get,
            )
            edit_icon = st.text_input("Ícone", value=selected.icon or "•", max_chars=8)
            edit_color = st.color_picker("Cor", selected.color or "#8290A8")
            saved = st.form_submit_button("Salvar alterações", use_container_width=True)
        if saved:
            try:
                repository.update_fields(
                    Category,
                    selected.id,
                    {
                        "name": edit_name.strip(),
                        "kind": edit_kind,
                        "icon": edit_icon.strip() or "•",
                        "color": edit_color,
                    },
                    user_id=user.id,
                )
                notify_success("Categoria atualizada")
                safe_rerun()
            except Exception as exc:
                friendly_error("Não foi possível atualizar a categoria.", exc)
        confirmation_button(
            "Arquivar categoria",
            key=f"delete_category_{selected.id}",
            title="Arquivar categoria?",
            message="Lançamentos antigos permanecem vinculados; a categoria sai dos novos cadastros.",
            on_confirm=repository.soft_delete,
            confirm_args=(Category, selected.id),
            confirm_kwargs={"user_id": user.id},
            success_message="Categoria arquivada",
        )


def _render_data(repository: Any, user: Any, engine: Any) -> None:
    stats = repository.backup_stats(user.id)
    count_col, last_col = st.columns(2)
    with count_col:
        render_metric_card(
            "Movimentações",
            str(stats.transaction_count),
            value_is_formatted=True,
            tone="blue",
        )
    with last_col:
        render_metric_card(
            "Última movimentação",
            format_brl_date(stats.last_transaction_date) if stats.last_transaction_date else "—",
            value_is_formatted=True,
            tone="neutral",
        )
    backup_data = None
    if st.button("Preparar backup em ZIP", key="prepare_backup", use_container_width=True):
        backup_data = _backup_zip(repository, user.id)
    if backup_data is not None:
        st.download_button(
            "Baixar backup em ZIP",
            data=backup_data,
            file_name=f"financas_backup_{date.today():%Y-%m-%d}.zip",
            mime="application/zip",
            use_container_width=True,
            help="Um CSV por tabela, incluindo registros arquivados.",
            on_click="ignore",
        )
    st.caption("Não há backup externo automático nesta versão. Guarde o arquivo em local seguro.")

    if os.getenv("FINANCE_APP_ENV", "").casefold() == "development":
        render_section_header("Ferramentas de desenvolvimento")
        confirmation_button(
            "Inserir dados fictícios",
            key="seed_demo_data",
            title="Popular dados de demonstração?",
            message="Os registros serão marcados como fictícios e o processo é idempotente.",
            on_confirm=seed_demo_data,
            confirm_kwargs={"engine": engine, "user_id": user.id},
            success_message="Dados de demonstração verificados",
        )


def render(
    repository: Any,
    user: Any,
    *,
    engine: Any = None,
    accounts: list[Any] | None = None,
) -> None:
    page_header("Configurações", "Preferências e cadastros-base em um só lugar.", eyebrow="Controle local")
    section = st.segmented_control(
        "Área de configurações",
        ("Preferências", "Contas", "Categorias", "Dados"),
        default="Preferências",
        key="settings_section",
    )
    if section == "Preferências":
        accounts = accounts if accounts is not None else repository.list_accounts(user.id)
        _render_profile(repository, user, accounts)
    elif section == "Contas":
        _render_accounts(repository, user)
    elif section == "Categorias":
        _render_categories(repository, user)
    else:
        _render_data(repository, user, engine)
