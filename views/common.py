"""Pequenos utilitários compartilhados entre as páginas Streamlit."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from datetime import date
from decimal import Decimal
from typing import Any, TypeVar

import streamlit as st

from components.widgets import format_date_br
from utils.helpers import display_currency


LOGGER = logging.getLogger("finance_app.ui")
T = TypeVar("T")


ACCOUNT_TYPES = {
    "checking": "Conta corrente",
    "savings": "Poupança",
    "digital": "Conta digital",
    "wallet": "Carteira",
    "cash": "Dinheiro",
    "investment": "Investimentos",
    "other": "Outros",
}

PAYMENT_METHODS = {
    "pix": "PIX",
    "cash": "Dinheiro",
    "debit": "Débito",
    "credit": "Crédito",
    "boleto": "Boleto",
    "transfer": "Transferência",
    "other": "Outros",
}

TRANSACTION_TYPES = {
    "income": "Receita",
    "expense": "Despesa",
    "transfer": "Transferência",
}

CATEGORY_TONES = {
    "income": "green",
    "expense": "coral",
    "both": "blue",
}


def page_header(title: str, subtitle: str | None = None, *, eyebrow: str | None = None) -> None:
    """Render a compact product-like page heading."""

    if eyebrow:
        st.caption(eyebrow.upper())
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def privacy_enabled() -> bool:
    """Return the session-only privacy preference."""

    return bool(st.session_state.get("privacy_mode", False))


def money(value: Decimal | int | str | None) -> str:
    """Format an amount while respecting privacy mode."""

    return display_currency(value or Decimal("0"), private=privacy_enabled())


def option_map(items: Iterable[T], label: Callable[[T], str]) -> tuple[list[Any], dict[Any, T], dict[Any, str]]:
    """Build Streamlit-friendly UUID options and safe labels."""

    objects = list(items)
    by_id = {item.id: item for item in objects}
    labels = {item.id: label(item) for item in objects}
    return list(by_id), by_id, labels


def select_model(
    label: str,
    items: Sequence[T],
    *,
    key: str,
    formatter: Callable[[T], str] = lambda value: str(getattr(value, "name", value)),
    optional: bool = False,
    default_id: Any | None = None,
    help: str | None = None,
) -> T | None:
    """Select an ORM object without placing the object itself in widget state."""

    options, by_id, labels = option_map(items, formatter)
    empty = "__none__"
    widget_options: list[Any] = ([empty] if optional else []) + options
    if not widget_options:
        st.info(f"Cadastre {label.lower()} antes de continuar.")
        return None
    if key not in st.session_state:
        if default_id in by_id:
            st.session_state[key] = default_id
        elif optional:
            st.session_state[key] = empty
    selected = st.selectbox(
        label,
        widget_options,
        key=key,
        format_func=lambda item_id: "Não informado" if item_id == empty else labels[item_id],
        help=help,
    )
    return None if selected == empty else by_id[selected]


def date_label(value: date | None) -> str:
    return format_date_br(value)


def status_label(status: str) -> str:
    return {
        "pending": "Pendente",
        "paid": "Pago",
        "open": "Aberta",
        "closed": "Fechada",
        "overdue": "Atrasado",
        "cancelled": "Cancelado",
        "refunded": "Reembolsado",
        "active": "Ativo",
        "completed": "Concluída",
        "paused": "Pausada",
    }.get(status, status.replace("_", " ").title())


def friendly_error(message: str, exc: Exception) -> None:
    """Log technical detail and show only actionable copy in the UI."""

    LOGGER.exception(message, exc_info=exc)
    st.error(message)


def safe_rerun() -> None:
    rerun = getattr(st, "rerun", None)
    if rerun is not None:
        rerun()
