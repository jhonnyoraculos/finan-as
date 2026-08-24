"""Finance-specific Streamlit inputs and Brazilian formatting helpers."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Callable, Sequence

import streamlit as st


_CENT = Decimal("0.01")
_BRAZILIAN_WITH_DECIMALS = re.compile(
    r"^(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?$"
)
_INTEGER = re.compile(r"^\d+$")
_DOT_DECIMAL = re.compile(r"^\d+\.\d{1,2}$")
_GROUPED_INTEGER = re.compile(r"^\d{1,3}(?:\.\d{3})+$")


def parse_brl(value: Decimal | int | float | str) -> Decimal:
    """Parse a BRL amount without losing cents.

    Accepted examples include ``R$ 1.234,56``, ``1234,56``, ``29,90`` and
    numeric Python values. A single dot followed by one or two digits is also
    accepted as a decimal separator for keyboard convenience. Ambiguous or
    malformed strings raise ``ValueError`` instead of silently changing value.
    """

    if isinstance(value, bool):
        raise ValueError("Booleanos não são valores monetários.")

    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, (int, float)):
        try:
            amount = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("Valor monetário inválido.") from exc
    elif isinstance(value, str):
        normalized = (
            value.strip()
            .replace("\u00a0", "")
            .replace("\u202f", "")
            .replace("−", "-")
            .replace(" ", "")
        )
        if not normalized:
            raise ValueError("Informe um valor.")

        negative_parentheses = normalized.startswith("(") and normalized.endswith(")")
        if negative_parentheses:
            normalized = normalized[1:-1]

        sign = ""
        if normalized[:1] in {"+", "-"}:
            sign, normalized = normalized[0], normalized[1:]
        normalized = re.sub(r"(?i)^r\$", "", normalized)
        if not normalized:
            raise ValueError("Informe um valor numérico.")

        if "," in normalized:
            if not _BRAZILIAN_WITH_DECIMALS.fullmatch(normalized):
                raise ValueError("Use o formato brasileiro, por exemplo: 1.234,56.")
            canonical = normalized.replace(".", "").replace(",", ".")
        elif _INTEGER.fullmatch(normalized):
            canonical = normalized
        elif _GROUPED_INTEGER.fullmatch(normalized):
            canonical = normalized.replace(".", "")
        elif _DOT_DECIMAL.fullmatch(normalized):
            canonical = normalized
        else:
            raise ValueError("Use o formato brasileiro, por exemplo: 1.234,56.")

        if negative_parentheses:
            sign = "-"
        try:
            amount = Decimal(f"{sign}{canonical}")
        except InvalidOperation as exc:
            raise ValueError("Valor monetário inválido.") from exc
    else:
        raise TypeError("O valor precisa ser texto, Decimal, int ou float.")

    if not amount.is_finite():
        raise ValueError("O valor precisa ser finito.")
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


def format_brl(
    value: Decimal | int | float | str,
    *,
    hidden: bool = False,
    include_symbol: bool = True,
) -> str:
    """Format a monetary value as ``R$ 1.234,56``."""

    if hidden:
        return "R$ ••••••" if include_symbol else "••••••"
    amount = parse_brl(value)
    sign = "-" if amount < 0 else ""
    formatted = (
        f"{abs(amount):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    )
    symbol = "R$ " if include_symbol else ""
    return f"{sign}{symbol}{formatted}"


def format_percentage(value: Decimal | int | float | str, *, places: int = 1) -> str:
    """Format a percentage with a Brazilian decimal comma."""

    if places < 0:
        raise ValueError("A quantidade de casas não pode ser negativa.")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Percentual inválido.") from exc
    if not amount.is_finite():
        raise ValueError("O percentual precisa ser finito.")
    quantum = Decimal("1").scaleb(-places)
    text = f"{amount.quantize(quantum, rounding=ROUND_HALF_UP):.{places}f}"
    return f"{text.replace('.', ',')}%"


def format_date_br(value: date | datetime | None, *, fallback: str = "—") -> str:
    """Format a date as DD/MM/YYYY."""

    if value is None:
        return fallback
    if not isinstance(value, (date, datetime)):
        raise TypeError("A data precisa ser date, datetime ou None.")
    return value.strftime("%d/%m/%Y")


def money_input(
    label: str,
    value: Decimal | int | float | str | None = Decimal("0.00"),
    *,
    key: str | None = None,
    placeholder: str = "R$ 0,00",
    help: str | None = None,
    disabled: bool = False,
    label_visibility: str = "visible",
    allow_negative: bool = False,
    minimum: Decimal | int | float | str | None = None,
    maximum: Decimal | int | float | str | None = None,
    required: bool = True,
    show_validation: bool = True,
) -> Decimal | None:
    """Render a touch-friendly BRL text input and return ``Decimal``.

    Invalid or out-of-range input returns ``None``. This makes form handlers
    explicit: persist only when the returned amount is not ``None``.
    """

    initial = "" if value is None else format_brl(value)
    raw_value = st.text_input(
        label,
        value=initial,
        key=key,
        placeholder=placeholder,
        help=help,
        disabled=disabled,
        label_visibility=label_visibility,
    )
    if not raw_value.strip():
        if required and show_validation:
            st.caption("⚠ Informe um valor.")
        return None

    try:
        parsed = parse_brl(raw_value)
        if not allow_negative and parsed < 0:
            raise ValueError("O valor não pode ser negativo.")
        if minimum is not None and parsed < parse_brl(minimum):
            raise ValueError(f"O valor mínimo é {format_brl(minimum)}.")
        if maximum is not None and parsed > parse_brl(maximum):
            raise ValueError(f"O valor máximo é {format_brl(maximum)}.")
    except (TypeError, ValueError) as exc:
        if show_validation:
            st.caption(f"⚠ {exc}")
        return None
    return parsed


def transaction_type_input(
    *,
    label: str = "Tipo",
    options: Sequence[str] = ("despesa", "receita", "transferencia"),
    default: str = "despesa",
    key: str = "transaction_type",
) -> str:
    """Render a compact transaction-type selector with a compatible fallback."""

    normalized_options = tuple(options)
    if not normalized_options:
        raise ValueError("Informe ao menos um tipo de transação.")
    if default not in normalized_options:
        default = normalized_options[0]
    labels = {
        "despesa": "Despesa",
        "receita": "Receita",
        "transferencia": "Transferência",
        "transferência": "Transferência",
    }
    formatter: Callable[[str], str] = lambda item: labels.get(item.casefold(), item.title())
    segmented = getattr(st, "segmented_control", None)
    if segmented is not None:
        selected = segmented(
            label,
            options=normalized_options,
            default=default,
            format_func=formatter,
            key=key,
            selection_mode="single",
        )
        return selected or default
    return st.radio(  # pragma: no cover - fallback for older Streamlit
        label,
        options=normalized_options,
        index=normalized_options.index(default),
        format_func=formatter,
        key=key,
        horizontal=True,
    )


def privacy_toggle(
    *,
    label: str = "Ocultar valores",
    key: str = "privacy_mode",
    help: str = "Oculta valores financeiros durante esta sessão.",
) -> bool:
    """Render and persist the session-only privacy switch."""

    toggle = getattr(st, "toggle", None)
    if toggle is not None:
        return bool(toggle(label, key=key, help=help))
    return bool(st.checkbox(label, key=key, help=help))  # pragma: no cover


def notify_success(message: str, *, icon: str = "✅") -> None:
    """Show discreet feedback using toast when available."""

    toast = getattr(st, "toast", None)
    if toast is not None:
        toast(message, icon=icon)
    else:  # pragma: no cover - fallback for older Streamlit
        st.success(message)


# A familiar alternate name for forms authored before this module existed.
currency_input = money_input


__all__ = [
    "currency_input",
    "format_brl",
    "format_date_br",
    "format_percentage",
    "money_input",
    "notify_success",
    "parse_brl",
    "privacy_toggle",
    "transaction_type_input",
]
