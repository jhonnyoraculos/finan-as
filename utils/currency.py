"""Safe parsing and formatting helpers for Brazilian monetary values."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import TypeAlias


MoneyLike: TypeAlias = Decimal | int | float | str
CENT = Decimal("0.01")
ZERO = Decimal("0.00")


class CurrencyParseError(ValueError):
    """Raised when a value cannot be interpreted as money."""


def quantize_money(value: Decimal, *, rounding: str = ROUND_HALF_UP) -> Decimal:
    """Round a Decimal to cents using an explicit, financial rounding mode."""

    if not value.is_finite():
        raise CurrencyParseError("O valor monetario deve ser finito.")
    return value.quantize(CENT, rounding=rounding)


def parse_brl_currency(value: MoneyLike | None) -> Decimal:
    """Convert a BRL-formatted value to ``Decimal``.

    Accepted examples include ``R$ 1.234,56``, ``1234,56``, ``-R$ 10,00``
    and already numeric values. A single dot followed by three digits is
    interpreted as a Brazilian thousands separator; otherwise a single dot is
    accepted as a decimal separator for interoperability with database values.
    """

    if value is None:
        raise CurrencyParseError("Informe um valor monetario.")
    if isinstance(value, bool):
        raise CurrencyParseError("Valor monetario invalido.")
    if isinstance(value, Decimal):
        return quantize_money(value)
    if isinstance(value, (int, float)):
        try:
            return quantize_money(Decimal(str(value)))
        except InvalidOperation as exc:
            raise CurrencyParseError("Valor monetario invalido.") from exc

    raw = str(value).strip().replace("\u00a0", " ")
    if not raw:
        raise CurrencyParseError("Informe um valor monetario.")

    negative_parentheses = raw.startswith("(") and raw.endswith(")")
    if negative_parentheses:
        raw = raw[1:-1].strip()

    raw = re.sub(r"(?i)r\s*\$", "", raw)
    raw = raw.replace(" ", "")

    sign = -1 if negative_parentheses else 1
    if raw.startswith(("+", "-")):
        sign *= -1 if raw[0] == "-" else 1
        raw = raw[1:]
    if raw.endswith("-"):
        sign *= -1
        raw = raw[:-1]

    if not raw:
        raise CurrencyParseError("Valor monetario invalido.")

    normalized: str
    if "," in raw:
        if raw.count(",") != 1:
            raise CurrencyParseError("Use apenas uma virgula decimal.")
        integer_part, decimal_part = raw.split(",", 1)
        if "." in decimal_part:
            raise CurrencyParseError("Separadores monetarios invalidos.")
        if not _valid_grouped_integer(integer_part, "."):
            raise CurrencyParseError("Separador de milhar em posicao invalida.")
        if decimal_part and not decimal_part.isdigit():
            raise CurrencyParseError("Centavos invalidos.")
        if len(decimal_part) > 2:
            raise CurrencyParseError("Use no maximo duas casas decimais.")
        integer_digits = integer_part.replace(".", "") or "0"
        normalized = integer_digits
        if decimal_part:
            normalized += f".{decimal_part}"
    elif "." in raw:
        if raw.count(".") > 1:
            if not _valid_grouped_integer(raw, "."):
                raise CurrencyParseError("Separador de milhar em posicao invalida.")
            normalized = raw.replace(".", "")
        elif re.fullmatch(r"\d{1,3}\.\d{3}", raw):
            normalized = raw.replace(".", "")
        elif match := re.fullmatch(r"\d+\.(\d+)", raw):
            if len(match.group(1)) > 2:
                raise CurrencyParseError("Use no maximo duas casas decimais.")
            normalized = raw
        else:
            raise CurrencyParseError("Valor monetario invalido.")
    else:
        if not raw.isdigit():
            raise CurrencyParseError("Valor monetario invalido.")
        normalized = raw

    try:
        parsed = Decimal(normalized) * sign
    except InvalidOperation as exc:
        raise CurrencyParseError("Valor monetario invalido.") from exc
    return quantize_money(parsed)


def _valid_grouped_integer(value: str, separator: str) -> bool:
    if not value:
        return True
    if separator not in value:
        return value.isdigit()
    escaped = re.escape(separator)
    return bool(re.fullmatch(rf"\d{{1,3}}(?:{escaped}\d{{3}})+", value))


def format_brl_currency(
    value: MoneyLike,
    *,
    symbol: bool = True,
    negative_before_symbol: bool = True,
) -> str:
    """Format money as ``R$ 1.234,56`` without relying on OS locales."""

    amount = parse_brl_currency(value)
    is_negative = amount < ZERO
    absolute = abs(amount)
    us_formatted = f"{absolute:,.2f}"
    br_formatted = us_formatted.replace(",", "_").replace(".", ",").replace("_", ".")

    if not symbol:
        return f"-{br_formatted}" if is_negative else br_formatted
    if is_negative and negative_before_symbol:
        return f"-R$ {br_formatted}"
    if is_negative:
        return f"R$ -{br_formatted}"
    return f"R$ {br_formatted}"


def format_brl_percentage(value: Decimal | int | float | str, decimals: int = 1) -> str:
    """Format a number as a Brazilian percentage, for example ``24,8%``."""

    if decimals < 0:
        raise ValueError("decimals nao pode ser negativo.")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Percentual invalido.") from exc
    quantum = Decimal(1).scaleb(-decimals)
    rendered = f"{number.quantize(quantum, rounding=ROUND_HALF_UP):,.{decimals}f}"
    rendered = rendered.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{rendered}%"


# Concise aliases for callers that do not need to mention the locale explicitly.
parse_currency = parse_brl_currency
format_currency = format_brl_currency
