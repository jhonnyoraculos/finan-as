"""Native Streamlit navigation with URL/session-state synchronization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import streamlit as st


@dataclass(frozen=True, slots=True)
class NavigationItem:
    """One destination rendered as a native Streamlit button."""

    key: str
    label: str
    icon: str
    help: str | None = None

    @property
    def button_label(self) -> str:
        return f"{self.icon}\n{self.label}"


DEFAULT_NAV_ITEMS: tuple[NavigationItem, ...] = (
    NavigationItem("home", "Início", "⌂", "Visão geral das suas finanças"),
    NavigationItem("cards", "Cartões", "▣", "Cartões e faturas"),
    NavigationItem("add", "Adicionar", "+", "Adicionar movimentação"),
    NavigationItem("analytics", "Análises", "⌁", "Gráficos e previsões"),
    NavigationItem("more", "Mais", "•••", "Demais recursos e ajustes"),
)


def _query_value(query_key: str) -> str | None:
    """Read one query parameter on current Streamlit versions and older fallbacks."""

    query_params = getattr(st, "query_params", None)
    if query_params is not None:
        value = query_params.get(query_key)
    else:  # pragma: no cover - compatibility with pre-st.query_params releases
        getter = getattr(st, "experimental_get_query_params", None)
        if getter is None:
            return None
        value = getter().get(query_key)
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else None
    return str(value) if value is not None else None


def _set_query_value(query_key: str, value: str) -> None:
    query_params = getattr(st, "query_params", None)
    if query_params is not None:
        query_params[query_key] = value
        return
    setter = getattr(st, "experimental_set_query_params", None)  # pragma: no cover
    getter = getattr(st, "experimental_get_query_params", None)
    if setter is not None:
        existing = getter() if getter is not None else {}
        existing[query_key] = value
        setter(**existing)


def _validate_items(items: Iterable[NavigationItem]) -> tuple[NavigationItem, ...]:
    normalized = tuple(items)
    if not normalized:
        raise ValueError("A navegação precisa ter ao menos um item.")
    keys = [item.key for item in normalized]
    if any(not key or not key.strip() for key in keys):
        raise ValueError("Todo item de navegação precisa de uma chave não vazia.")
    if len(keys) != len(set(keys)):
        raise ValueError("As chaves dos itens de navegação devem ser únicas.")
    return normalized


def initialize_navigation(
    items: Sequence[NavigationItem] = DEFAULT_NAV_ITEMS,
    *,
    default: str = "home",
    state_key: str = "active_page",
    query_key: str = "page",
) -> str:
    """Initialize and return the active destination.

    A valid URL query parameter wins on first load. On later runs, the helper
    detects whether view code changed session state or browser navigation changed
    the URL and synchronizes the other side. Invalid values never reach dispatch.
    """

    nav_items = _validate_items(items)
    allowed = {item.key for item in nav_items}
    if default not in allowed:
        default = nav_items[0].key

    query_page = _query_value(query_key)
    session_page = st.session_state.get(state_key)
    sync_key = f"_{state_key}_last_synced"
    last_synced = st.session_state.get(sync_key)

    if last_synced not in allowed:
        # A shareable URL is the most intentional signal on first load.
        active = query_page if query_page in allowed else session_page
    elif session_page in allowed and session_page != last_synced and query_page == last_synced:
        # View code intentionally routed by assigning session state.
        active = session_page
    elif query_page in allowed and query_page != last_synced:
        # Browser history or an edited URL intentionally changed the route.
        active = query_page
    elif session_page in allowed:
        active = session_page
    else:
        active = default

    if active not in allowed:
        active = default

    st.session_state[state_key] = active
    st.session_state[sync_key] = active
    if query_page != active:
        _set_query_value(query_key, active)
    return active


def navigate_to(
    page: str,
    *,
    items: Sequence[NavigationItem] = DEFAULT_NAV_ITEMS,
    state_key: str = "active_page",
    query_key: str = "page",
) -> None:
    """Select a page in both session state and the shareable URL."""

    nav_items = _validate_items(items)
    allowed = {item.key for item in nav_items}
    if page not in allowed:
        raise ValueError(f"Destino de navegação desconhecido: {page!r}")
    st.session_state[state_key] = page
    st.session_state[f"_{state_key}_last_synced"] = page
    _set_query_value(query_key, page)


def _navigation_callback(
    page: str,
    items: Sequence[NavigationItem],
    state_key: str,
    query_key: str,
) -> None:
    navigate_to(page, items=items, state_key=state_key, query_key=query_key)


def render_navigation(
    items: Sequence[NavigationItem] = DEFAULT_NAV_ITEMS,
    *,
    default: str = "home",
    state_key: str = "active_page",
    query_key: str = "page",
    container_key: str = "finance_navigation",
) -> str:
    """Render app-like responsive navigation and return the active page key.

    It appears as a fixed bottom bar below 900px and as a quiet left rail on
    desktop. All destinations are genuine ``st.button`` widgets; no clickable
    HTML or JavaScript is used.
    """

    nav_items = _validate_items(items)
    active = initialize_navigation(
        nav_items,
        default=default,
        state_key=state_key,
        query_key=query_key,
    )

    with st.container(key=container_key):
        columns = st.columns(len(nav_items), gap="small")
        for column, item in zip(columns, nav_items):
            with column:
                st.button(
                    item.button_label,
                    key=f"{container_key}_{item.key}",
                    help=item.help,
                    type="primary" if item.key == active else "secondary",
                    width="stretch",
                    on_click=_navigation_callback,
                    args=(item.key, nav_items, state_key, query_key),
                )
    return active


__all__ = [
    "DEFAULT_NAV_ITEMS",
    "NavigationItem",
    "initialize_navigation",
    "navigate_to",
    "render_navigation",
]
