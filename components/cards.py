"""Safe, reusable Liquid Glass cards for finance views."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape
import re
from typing import Any, Iterable, Literal

import streamlit as st


Tone = Literal[
    "neutral",
    "positive",
    "negative",
    "green",
    "coral",
    "blue",
    "orange",
    "purple",
    "yellow",
    "muted",
]

_TONE_CLASSES: dict[str, str] = {
    "neutral": "",
    "positive": "finance-value-positive",
    "negative": "finance-value-negative",
    "green": "finance-value-positive",
    "coral": "finance-value-negative",
    "blue": "finance-value-blue",
    "orange": "finance-value-orange",
    "purple": "finance-value-purple",
    "yellow": "finance-value-yellow",
    "muted": "finance-value-muted",
}

_STATUS_CLASSES: dict[str, str] = {
    "pago": "paid",
    "paid": "paid",
    "pendente": "pending",
    "pending": "pending",
    "atrasado": "late",
    "late": "late",
    "overdue": "late",
}

_PROGRESS_COLORS: dict[str, str] = {
    "neutral": "#9AA8C2",
    "positive": "#72D7A3",
    "negative": "#FF8D86",
    "green": "#72D7A3",
    "coral": "#FF8D86",
    "blue": "#6C9EFF",
    "orange": "#F3B36A",
    "purple": "#B49AF8",
    "yellow": "#E7CB74",
    "muted": "#9AA8C2",
}

_SAFE_COLOR = re.compile(
    r"^(?:#[0-9a-fA-F]{3,8}|rgba?\(\s*[\d.%]+\s*,\s*[\d.%]+\s*,\s*[\d.%]+"
    r"(?:\s*,\s*[\d.]+)?\s*\))$"
)


def _safe_text(value: Any, *, fallback: str = "") -> str:
    """Escape content before it reaches a component HTML template."""

    if value is None:
        value = fallback
    return escape(str(value), quote=True)


def _safe_color(value: str | None, fallback: str) -> str:
    """Allow only simple hex/rgb colors in inline custom properties."""

    if value and _SAFE_COLOR.fullmatch(value.strip()):
        return value.strip()
    return fallback


def _tone_class(tone: str) -> str:
    return _TONE_CLASSES.get(tone, _TONE_CLASSES["neutral"])


def _as_decimal(value: Decimal | int | float | str) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Valor monetário inválido: {value!r}") from exc


def format_brl(value: Decimal | int | float | str, *, hidden: bool = False) -> str:
    """Format a numeric value as Brazilian Real for card display."""

    if hidden:
        return "R$ ••••••"
    amount = _as_decimal(value)
    sign = "-" if amount < 0 else ""
    absolute = abs(amount)
    formatted = f"{absolute:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{sign}R$ {formatted}"


def _display_value(
    value: Decimal | int | float | str,
    *,
    hidden: bool,
    already_formatted: bool = False,
) -> str:
    if hidden:
        return "R$ ••••••"
    if already_formatted:
        return str(value)
    return format_brl(value)


def _render(html: str) -> None:
    st.markdown(html, unsafe_allow_html=True)


def render_section_header(
    title: str,
    *,
    subtitle: str | None = None,
    action_label: str | None = None,
) -> None:
    """Render a compact section heading (action label is visual only)."""

    subtitle_html = f"<p>{_safe_text(subtitle)}</p>" if subtitle else ""
    action_html = (
        f'<span class="finance-section-action">{_safe_text(action_label)}</span>'
        if action_label
        else ""
    )
    _render(
        '<div class="finance-section-heading">'
        f'<div><h2>{_safe_text(title)}</h2>{subtitle_html}</div>{action_html}'
        "</div>"
    )


def render_sparkline(
    values: Iterable[Decimal | int | float | str],
    *,
    color: str = "#6C9EFF",
    label: str = "Evolução financeira dos últimos meses",
) -> None:
    """Render a dependency-free SVG sparkline for lightweight summary pages."""

    numbers = [_as_decimal(value) for value in values]
    if not numbers:
        return
    low, high = min(numbers), max(numbers)
    spread = high - low
    last_index = max(1, len(numbers) - 1)
    points: list[tuple[Decimal, Decimal]] = []
    for index, value in enumerate(numbers):
        x = Decimal(index) / Decimal(last_index) * Decimal("100")
        y = (
            Decimal("12")
            if spread == 0
            else Decimal("22") - ((value - low) / spread * Decimal("20"))
        )
        points.append((x, y))
    coordinates = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    area = f"0,24 {coordinates} 100,24"
    safe_color = _safe_color(color, "#6C9EFF")
    _render(
        f'<div class="finance-sparkline" role="img" aria-label="{_safe_text(label)}">'
        '<svg viewBox="0 0 100 24" preserveAspectRatio="none" aria-hidden="true">'
        '<defs><linearGradient id="finance-sparkline-fill" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{safe_color}" stop-opacity="0.22" />'
        f'<stop offset="100%" stop-color="{safe_color}" stop-opacity="0" />'
        '</linearGradient></defs>'
        f'<polygon points="{area}" fill="url(#finance-sparkline-fill)" />'
        f'<polyline points="{coordinates}" fill="none" stroke="{safe_color}" '
        'stroke-width="0.55" stroke-linecap="round" stroke-linejoin="round" />'
        "</svg></div>"
    )


def render_metric_card(
    title: str,
    value: Decimal | int | float | str,
    *,
    delta: str | None = None,
    delta_tone: Tone = "neutral",
    icon: str | None = None,
    tone: Tone = "neutral",
    hidden: bool = False,
    value_is_formatted: bool = False,
    caption: str | None = None,
) -> None:
    """Render a primary KPI card.

    Set ``value_is_formatted=True`` for percentages or non-monetary values.
    """

    icon_html = f'<span class="finance-icon">{_safe_text(icon)}</span>' if icon else ""
    caption_html = (
        f'<div class="finance-card-meta">{_safe_text(caption)}</div>' if caption else ""
    )
    delta_class = ""
    if delta_tone in {"positive", "green"}:
        delta_class = " finance-delta--positive"
    elif delta_tone in {"negative", "coral"}:
        delta_class = " finance-delta--negative"
    delta_html = (
        f'<span class="finance-delta{delta_class}">{_safe_text(delta)}</span>' if delta else ""
    )
    display = _display_value(value, hidden=hidden, already_formatted=value_is_formatted)
    _render(
        '<div class="finance-glass-card">'
        '<div class="finance-card-heading">'
        '<div class="finance-card-main">'
        f'<div class="finance-kicker">{_safe_text(title)}</div>'
        f'<div class="finance-card-value {_tone_class(tone)}">{_safe_text(display)}</div>'
        f"{caption_html}{delta_html}"
        f"</div>{icon_html}</div></div>"
    )


def render_account_card(
    name: str,
    balance: Decimal | int | float | str,
    *,
    institution: str | None = None,
    account_type: str | None = None,
    icon: str = "◉",
    color: str | None = None,
    hidden: bool = False,
) -> None:
    """Render an account summary card."""

    meta_parts = [part for part in (institution, account_type) if part]
    meta = " · ".join(str(part) for part in meta_parts)
    glow = _safe_color(color, "rgba(108,158,255,0.22)")
    _render(
        f'<div class="finance-glass-card finance-account-card" style="--card-glow:{glow}">'
        '<div class="finance-card-heading">'
        '<div class="finance-card-main">'
        f'<div class="finance-card-title">{_safe_text(name)}</div>'
        f'<div class="finance-card-meta">{_safe_text(meta or "Conta")}</div>'
        f'</div><span class="finance-icon">{_safe_text(icon)}</span></div>'
        f'<div class="finance-card-value">{_safe_text(format_brl(balance, hidden=hidden))}</div>'
        "</div>"
    )


def render_credit_card(
    name: str,
    *,
    available: Decimal | int | float | str,
    used: Decimal | int | float | str,
    limit_total: Decimal | int | float | str,
    bank: str | None = None,
    closing_label: str | None = None,
    due_label: str | None = None,
    color: str | None = None,
    hidden: bool = False,
) -> None:
    """Render a wallet-style credit card with utilization progress."""

    used_value = _as_decimal(used)
    limit_value = _as_decimal(limit_total)
    percent = Decimal("0") if limit_value <= 0 else (used_value / limit_value) * 100
    clamped_percent = max(Decimal("0"), min(percent, Decimal("100")))
    tone = "negative" if percent >= 90 else "yellow" if percent >= 75 else "orange"
    progress_color = _PROGRESS_COLORS[tone]
    glow = _safe_color(color, "rgba(243,179,106,0.28)")
    timeline_parts = [part for part in (closing_label, due_label) if part]
    timeline = " · ".join(str(part) for part in timeline_parts)
    _render(
        f'<div class="finance-glass-card finance-credit-card" style="--card-glow:{glow}">'
        '<div class="finance-card-heading">'
        '<div class="finance-card-main">'
        f'<div class="finance-card-brand">{_safe_text(bank or "Cartão")}</div>'
        f'<div class="finance-card-title">{_safe_text(name)}</div>'
        f'</div><span class="finance-icon">◫</span></div>'
        '<div class="finance-kicker" style="margin-top:1rem">Limite disponível</div>'
        f'<div class="finance-card-value">{_safe_text(format_brl(available, hidden=hidden))}</div>'
        '<div class="finance-progress-track">'
        f'<div class="finance-progress-bar" style="--progress:{clamped_percent:.2f}%;'
        f'--progress-color:{progress_color}"></div></div>'
        '<div class="finance-card-foot">'
        f'<div><span class="finance-card-meta">Usado</span><strong>{_safe_text(format_brl(used_value, hidden=hidden))}</strong></div>'
        f'<div><span class="finance-card-meta">Limite</span><strong>{_safe_text(format_brl(limit_value, hidden=hidden))}</strong></div>'
        "</div>"
        f'<div class="finance-card-meta" style="margin-top:.7rem">{_safe_text(timeline)}</div>'
        "</div>"
    )


def render_transaction_card(
    description: str,
    amount: Decimal | int | float | str,
    *,
    transaction_type: str = "despesa",
    date_label: str | None = None,
    method: str | None = None,
    category: str | None = None,
    icon: str = "•",
    installments: str | None = None,
    hidden: bool = False,
) -> None:
    """Render one mobile-friendly transaction row as a glass card."""

    normalized_type = transaction_type.casefold().strip()
    is_income = normalized_type in {"receita", "income", "entrada", "refund", "reembolso"}
    is_transfer = normalized_type in {"transferencia", "transferência", "transfer"}
    tone = "blue" if is_transfer else "positive" if is_income else "negative"
    amount_value = abs(_as_decimal(amount))
    if hidden:
        display_amount = "R$ ••••••"
    else:
        prefix = "" if is_transfer else "+" if is_income else "−"
        display_amount = f"{prefix}{format_brl(amount_value)}"
    meta_parts = [part for part in (date_label, category, method, installments) if part]
    meta = " · ".join(str(part) for part in meta_parts)
    _render(
        '<div class="finance-glass-card">'
        '<div class="finance-transaction">'
        f'<span class="finance-icon">{_safe_text(icon)}</span>'
        '<div class="finance-card-main">'
        f'<div class="finance-transaction-title">{_safe_text(description)}</div>'
        f'<div class="finance-transaction-meta">{_safe_text(meta)}</div>'
        "</div>"
        f'<div class="finance-transaction-amount {_tone_class(tone)}">{_safe_text(display_amount)}</div>'
        "</div></div>"
    )


def render_bill_card(
    description: str,
    amount: Decimal | int | float | str,
    *,
    due_label: str,
    status: str = "pendente",
    category: str | None = None,
    account: str | None = None,
    icon: str = "▣",
    hidden: bool = False,
) -> None:
    """Render a bill/payment card with an explicit textual status."""

    status_key = status.casefold().strip()
    status_class = _STATUS_CLASSES.get(status_key, "pending")
    meta_parts = [due_label, category, account]
    meta = " · ".join(str(part) for part in meta_parts if part)
    _render(
        '<div class="finance-glass-card">'
        '<div class="finance-bill-row">'
        f'<span class="finance-icon">{_safe_text(icon)}</span>'
        '<div class="finance-card-main">'
        f'<div class="finance-bill-title">{_safe_text(description)}</div>'
        f'<div class="finance-bill-meta">{_safe_text(meta)}</div>'
        f'<span class="finance-status finance-status--{status_class}">{_safe_text(status)}</span>'
        "</div>"
        f'<div class="finance-bill-amount">{_safe_text(format_brl(amount, hidden=hidden))}</div>'
        "</div></div>"
    )


def render_progress_card(
    title: str,
    current: Decimal | int | float | str,
    total: Decimal | int | float | str,
    *,
    subtitle: str | None = None,
    tone: Tone = "blue",
    icon: str | None = None,
    hidden: bool = False,
    show_percentage: bool = True,
) -> None:
    """Render a budget/goal progress card, clamping only its visual bar."""

    current_value = _as_decimal(current)
    total_value = _as_decimal(total)
    percent = Decimal("0") if total_value <= 0 else current_value / total_value * 100
    visual_percent = max(Decimal("0"), min(percent, Decimal("100")))
    progress_color = _PROGRESS_COLORS.get(tone, _PROGRESS_COLORS["blue"])
    icon_html = f'<span class="finance-icon">{_safe_text(icon)}</span>' if icon else ""
    percentage_html = (
        f'<strong class="{_tone_class(tone)}">{_safe_text(f"{percent:.0f}%")}</strong>'
        if show_percentage
        else ""
    )
    value_text = f"{format_brl(current_value, hidden=hidden)} / {format_brl(total_value, hidden=hidden)}"
    _render(
        '<div class="finance-glass-card">'
        '<div class="finance-progress-heading">'
        f'<div class="finance-card-main"><div class="finance-card-title">{_safe_text(title)}</div>'
        f'<div class="finance-card-meta">{_safe_text(subtitle)}</div></div>{icon_html}{percentage_html}'
        "</div>"
        f'<div class="finance-card-value finance-card-value--small">{_safe_text(value_text)}</div>'
        '<div class="finance-progress-track">'
        f'<div class="finance-progress-bar" style="--progress:{visual_percent:.2f}%;'
        f'--progress-color:{progress_color}"></div></div>'
        "</div>"
    )


# Short names keep view code pleasant while ``render_*`` remains self-documenting.
metric_card = render_metric_card
account_card = render_account_card
credit_card = render_credit_card
transaction_card = render_transaction_card
bill_card = render_bill_card
progress_card = render_progress_card
section_header = render_section_header


__all__ = [
    "account_card",
    "bill_card",
    "credit_card",
    "format_brl",
    "metric_card",
    "progress_card",
    "render_account_card",
    "render_bill_card",
    "render_credit_card",
    "render_metric_card",
    "render_progress_card",
    "render_section_header",
    "render_sparkline",
    "render_transaction_card",
    "section_header",
    "transaction_card",
]
