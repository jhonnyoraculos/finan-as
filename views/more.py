"""Hub das áreas secundárias sem recorrer à sidebar padrão."""

from __future__ import annotations

from typing import Any

import streamlit as st

from views import bills, planning, settings, transactions


SECTIONS = ("Histórico", "Contas", "Planejamento", "Configurações")


def render(
    repository: Any,
    user: Any,
    *,
    engine: Any = None,
    accounts: list[Any] | None = None,
) -> None:
    selected = st.segmented_control(
        "Área",
        SECTIONS,
        default=st.session_state.get("more_section", "Histórico"),
        key="more_section",
        selection_mode="single",
        width="stretch",
    ) or "Histórico"
    if selected == "Histórico":
        transactions.render(repository, user, accounts=accounts)
    elif selected == "Contas":
        bills.render(repository, user, accounts=accounts)
    elif selected == "Planejamento":
        planning.render(repository, user, accounts=accounts)
    else:
        settings.render(repository, user, engine=engine, accounts=accounts)
