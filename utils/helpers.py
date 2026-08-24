"""Small, dependency-free helpers used by services and Streamlit views."""

from __future__ import annotations

import html
import unicodedata
from collections.abc import Mapping
from typing import Any, TypeVar

from utils.currency import MoneyLike, format_brl_currency


T = TypeVar("T")
MISSING = object()
PRIVATE_CURRENCY = "R$ \u2022\u2022\u2022\u2022\u2022\u2022"


def get_value(source: Any, *names: str, default: T | None = None) -> Any | T | None:
    """Read the first non-``None`` field from either a mapping or an object."""

    if source is None:
        return default
    for name in names:
        if isinstance(source, Mapping):
            candidate = source.get(name, MISSING)
        else:
            candidate = getattr(source, name, MISSING)
        if candidate is not MISSING and candidate is not None:
            return candidate
    return default


def normalize_token(value: Any) -> str:
    """Normalize user/model enum-like strings for reliable comparisons."""

    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return "_".join(text.strip().lower().replace("-", " ").split())


def safe_text(value: Any) -> str:
    """Escape user-controlled content before embedding it into custom HTML."""

    return html.escape(str(value), quote=True)


def mask_currency(_value: MoneyLike | str | None = None) -> str:
    """Return the fixed representation used by privacy mode."""

    return PRIVATE_CURRENCY


def display_currency(value: MoneyLike, *, private: bool = False) -> str:
    """Format money or hide it while privacy mode is active."""

    return mask_currency(value) if private else format_brl_currency(value)


def privacy_value(value: MoneyLike, hidden: bool) -> str:
    """Compatibility helper for session-state privacy toggles."""

    return display_currency(value, private=hidden)


def as_bool(value: Any, *, default: bool = False) -> bool:
    """Coerce common database/form representations to bool."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    token = normalize_token(value)
    if token in {"1", "true", "sim", "yes", "on"}:
        return True
    if token in {"0", "false", "nao", "no", "off"}:
        return False
    return bool(value)
