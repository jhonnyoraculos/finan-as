"""Small Plotly chart factories tuned for touch screens and dark glass UI."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Sequence

import plotly.graph_objects as go
import streamlit as st

from styles.style import COLORS, apply_plotly_theme


PLOTLY_CONFIG: dict[str, Any] = {
    "displayModeBar": False,
    "displaylogo": False,
    "responsive": True,
    "scrollZoom": False,
    "doubleClick": False,
}


def _to_float(value: Decimal | int | float | str) -> float:
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Valor numérico inválido para gráfico: {value!r}") from exc


def _numbers(values: Iterable[Decimal | int | float | str]) -> list[float]:
    return [_to_float(value) for value in values]


def _format_brl(value: float) -> str:
    sign = "-" if value < 0 else ""
    raw = f"{abs(value):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{sign}R$ {raw}"


def _money_labels(values: Sequence[float]) -> list[str]:
    return [_format_brl(value) for value in values]


def _validate_lengths(labels: Sequence[Any], *series: Sequence[Any]) -> None:
    for values in series:
        if len(values) != len(labels):
            raise ValueError("Rótulos e séries do gráfico precisam ter o mesmo tamanho.")


def _empty_annotation(figure: go.Figure, message: str = "Sem dados neste período") -> go.Figure:
    figure.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font={"color": COLORS["muted"], "size": 13},
    )
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    return figure


def income_expense_chart(
    periods: Iterable[Any],
    income: Iterable[Decimal | int | float | str],
    expenses: Iterable[Decimal | int | float | str],
    *,
    height: int = 285,
) -> go.Figure:
    """Create a grouped income-versus-expense bar chart."""

    x = list(periods)
    income_values = _numbers(income)
    expense_values = _numbers(expenses)
    _validate_lengths(x, income_values, expense_values)
    figure = go.Figure()
    if not x:
        return apply_plotly_theme(_empty_annotation(figure), height=height, showlegend=False)

    figure.add_bar(
        name="Entradas",
        x=x,
        y=income_values,
        customdata=_money_labels(income_values),
        marker={"color": COLORS["green"], "line": {"width": 0}},
        hovertemplate="%{x}<br><b>%{customdata}</b><extra>Entradas</extra>",
    )
    figure.add_bar(
        name="Despesas",
        x=x,
        y=expense_values,
        customdata=_money_labels(expense_values),
        marker={"color": COLORS["coral"], "line": {"width": 0}},
        hovertemplate="%{x}<br><b>%{customdata}</b><extra>Despesas</extra>",
    )
    apply_plotly_theme(
        figure,
        height=height,
        showlegend=True,
        overrides={
            "barmode": "group",
            "bargap": 0.28,
            "bargroupgap": 0.08,
            "hovermode": "x unified",
        },
    )
    figure.update_traces(marker_cornerradius=5)
    return figure


def category_donut_chart(
    categories: Iterable[str],
    values: Iterable[Decimal | int | float | str],
    *,
    height: int = 300,
    center_label: str = "Gastos",
) -> go.Figure:
    """Create a compact category donut with a readable center label."""

    labels = list(categories)
    amounts = _numbers(values)
    _validate_lengths(labels, amounts)
    figure = go.Figure()
    if not labels or sum(max(value, 0) for value in amounts) <= 0:
        return apply_plotly_theme(_empty_annotation(figure), height=height, showlegend=False)

    figure.add_pie(
        labels=labels,
        values=amounts,
        hole=0.68,
        sort=False,
        direction="clockwise",
        customdata=_money_labels(amounts),
        textinfo="none",
        hovertemplate="<b>%{label}</b><br>%{customdata}<br>%{percent}<extra></extra>",
        marker={"line": {"color": "rgba(7,11,26,0.75)", "width": 2}},
    )
    apply_plotly_theme(
        figure,
        height=height,
        showlegend=True,
        overrides={
            "margin": {"l": 4, "r": 4, "t": 12, "b": 4},
            "hovermode": "closest",
            "legend": {
                "orientation": "h",
                "yanchor": "top",
                "y": -0.03,
                "xanchor": "center",
                "x": 0.5,
                "font": {"size": 10},
            },
        },
    )
    figure.add_annotation(
        text=center_label,
        x=0.5,
        y=0.5,
        showarrow=False,
        font={"color": COLORS["muted"], "size": 12},
    )
    return figure


def balance_line_chart(
    periods: Iterable[Any],
    balances: Iterable[Decimal | int | float | str],
    *,
    height: int = 275,
    name: str = "Saldo",
    color: str = COLORS["blue"],
) -> go.Figure:
    """Create a smooth balance/equity evolution line chart."""

    x = list(periods)
    y = _numbers(balances)
    _validate_lengths(x, y)
    figure = go.Figure()
    if not x:
        return apply_plotly_theme(_empty_annotation(figure), height=height, showlegend=False)

    figure.add_scatter(
        x=x,
        y=y,
        name=name,
        mode="lines+markers",
        customdata=_money_labels(y),
        line={"color": color, "width": 3, "shape": "spline", "smoothing": 0.7},
        marker={
            "size": 7,
            "color": color,
            "line": {"color": "rgba(255,255,255,0.5)", "width": 1},
        },
        fill="tozeroy",
        fillcolor="rgba(108,158,255,0.09)",
        hovertemplate="%{x}<br><b>%{customdata}</b><extra></extra>",
    )
    apply_plotly_theme(figure, height=height, showlegend=False)
    return figure


def forecast_chart(
    periods: Iterable[Any],
    balances: Iterable[Decimal | int | float | str],
    *,
    height: int = 290,
) -> go.Figure:
    """Create a forecast chart with a subtly dashed future line."""

    figure = balance_line_chart(
        periods,
        balances,
        height=height,
        name="Saldo previsto",
        color=COLORS["purple"],
    )
    if figure.data:
        figure.data[0].line.dash = "dot"
        figure.data[0].fillcolor = "rgba(180,154,248,0.08)"
    return figure


def ranking_bar_chart(
    labels: Iterable[str],
    values: Iterable[Decimal | int | float | str],
    *,
    height: int = 285,
    color: str = COLORS["orange"],
) -> go.Figure:
    """Create a horizontal ranking suited to the narrow mobile viewport."""

    names = list(labels)
    amounts = _numbers(values)
    _validate_lengths(names, amounts)
    figure = go.Figure()
    if not names:
        return apply_plotly_theme(_empty_annotation(figure), height=height, showlegend=False)

    ordered = sorted(zip(names, amounts), key=lambda item: item[1])
    sorted_names = [item[0] for item in ordered]
    sorted_amounts = [item[1] for item in ordered]
    figure.add_bar(
        x=sorted_amounts,
        y=sorted_names,
        orientation="h",
        customdata=_money_labels(sorted_amounts),
        marker={"color": color, "line": {"width": 0}},
        hovertemplate="<b>%{y}</b><br>%{customdata}<extra></extra>",
    )
    apply_plotly_theme(
        figure,
        height=height,
        showlegend=False,
        overrides={"margin": {"l": 8, "r": 8, "t": 16, "b": 8}, "hovermode": "closest"},
    )
    figure.update_traces(marker_cornerradius=5)
    figure.update_xaxes(visible=False)
    figure.update_yaxes(showgrid=False, automargin=True)
    return figure


def sparkline_chart(
    values: Iterable[Decimal | int | float | str],
    *,
    labels: Iterable[Any] | None = None,
    height: int = 120,
    color: str = COLORS["blue"],
) -> go.Figure:
    """Create a label-free miniature line for a summary card."""

    y = _numbers(values)
    x = list(labels) if labels is not None else list(range(len(y)))
    _validate_lengths(x, y)
    figure = balance_line_chart(x, y, height=height, color=color)
    figure.update_layout(margin={"l": 0, "r": 0, "t": 4, "b": 0}, hovermode="closest")
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    if figure.data:
        figure.data[0].marker.size = 0
        figure.data[0].line.width = 2.5
    return figure


def render_chart(
    figure: go.Figure,
    *,
    key: str | None = None,
    config: dict[str, Any] | None = None,
) -> None:
    """Render a responsive Plotly chart with a minimal mobile toolbar."""

    chart_config = {**PLOTLY_CONFIG, **(config or {})}
    st.plotly_chart(
        figure,
        width="stretch",
        theme=None,
        config=chart_config,
        key=key,
    )


# Friendly aliases used by several view naming conventions.
income_vs_expense_chart = income_expense_chart
donut_chart = category_donut_chart
balance_evolution_chart = balance_line_chart


__all__ = [
    "PLOTLY_CONFIG",
    "balance_evolution_chart",
    "balance_line_chart",
    "category_donut_chart",
    "donut_chart",
    "forecast_chart",
    "income_expense_chart",
    "income_vs_expense_chart",
    "ranking_bar_chart",
    "render_chart",
    "sparkline_chart",
]
