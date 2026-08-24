"""Finanças Pessoais — aplicação Streamlit local, conectada ao Neon PostgreSQL."""

from __future__ import annotations

import logging
from datetime import date

import streamlit as st


# Precisa ser a primeira chamada Streamlit do script.
st.set_page_config(
    page_title="Finanças",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed",
)

from dotenv import load_dotenv
from sqlalchemy.orm import Session
from streamlit.runtime.scriptrunner_utils.exceptions import RerunException

from components.navigation import (
    DEFAULT_NAV_ITEMS,
    initialize_navigation,
    render_navigation,
)
from components.widgets import privacy_toggle
from database.connection import get_database_url, get_engine, get_session_factory
from database.init_db import init_database
from database.repository import FinanceRepository
from database.seed import seed_default_categories
from services.application_service import materialize_recurring_items, refresh_invoice_statuses
from styles import inject_global_styles
from views import analytics, cards, home, more, quick_add
from views.setup import render_database_error, render_missing_database, render_onboarding


LOGGER = logging.getLogger("finance_app")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
load_dotenv()
inject_global_styles()


@st.cache_resource(show_spinner=False)
def _prepare_database(database_url: str):
    """Create the pool and missing tables once per local Streamlit process."""

    engine = get_engine(database_url)
    init_database(engine=engine)
    return engine


def _bootstrap(repository: FinanceRepository):
    user = repository.first_active_user()
    if user is None:
        user = repository.create_user("Você")
        seed_default_categories(repository.session, user.id)
    elif not st.session_state.get("default_categories_checked"):
        seed_default_categories(repository.session, user.id)
        st.session_state["default_categories_checked"] = True
    settings = repository.get_settings(user.id)
    if "privacy_mode" not in st.session_state:
        st.session_state["privacy_mode"] = bool(settings.privacy_mode)
    return user


def _run_background_rules(repository: FinanceRepository, user_id) -> None:
    today_key = date.today().isoformat()
    if st.session_state.get("financial_rules_date") == today_key:
        return
    refresh_invoice_statuses(repository, user_id)
    materialize_recurring_items(repository, user_id, as_of=date.today(), horizon_months=3)
    st.session_state["financial_rules_date"] = today_key


def _render_application(repository: FinanceRepository, user, engine) -> None:
    accounts = repository.list_accounts(user.id)
    if not accounts:
        render_onboarding(repository, user)
        return

    with st.container(key="finance_topbar"):
        privacy_column, search_column = st.columns(2)
        with privacy_column:
            privacy_toggle(key="privacy_mode")
        with search_column, st.popover("⌕ Pesquisar", width="stretch"):
            query = st.text_input(
                "Pesquisar movimentações",
                key="global_search_query",
                placeholder="Mercado, salário, internet…",
            )
            if st.button("Ver resultados", width="stretch", disabled=not query.strip()):
                st.session_state["history_search"] = query.strip()
                st.session_state["history_page"] = 1
                st.session_state["more_section"] = "Histórico"
                st.session_state["active_page"] = "more"
                st.rerun()
    active_page = initialize_navigation(DEFAULT_NAV_ITEMS, default="home")
    if active_page == "home":
        home.render(repository, user)
    elif active_page == "cards":
        cards.render(repository, user)
    elif active_page == "add":
        quick_add.render(repository, user)
    elif active_page == "analytics":
        analytics.render(repository, user)
    else:
        more.render(repository, user, engine=engine)
    render_navigation(DEFAULT_NAV_ITEMS, default="home")


def _run_with_session(engine) -> None:
    """Commit successful UI actions even when Streamlit requests an immediate rerun."""

    factory = get_session_factory(engine=engine)
    session: Session = factory()
    repository = FinanceRepository(session)
    try:
        user = _bootstrap(repository)
        _run_background_rules(repository, user.id)
        _render_application(repository, user, engine)
    except RerunException:
        try:
            session.commit()
        except Exception as exc:
            session.rollback()
            LOGGER.exception("Falha ao confirmar alteração antes do rerun", exc_info=exc)
            st.error("Não foi possível salvar a alteração.")
            return
        raise
    except Exception as exc:
        session.rollback()
        LOGGER.exception("Erro ao renderizar a aplicação", exc_info=exc)
        st.error("Não foi possível carregar esta área. Tente novamente.")
    else:
        try:
            session.commit()
        except Exception as exc:
            session.rollback()
            LOGGER.exception("Falha ao salvar alterações", exc_info=exc)
            st.error("Não foi possível salvar a alteração.")
    finally:
        session.close()


def main() -> None:
    try:
        database_url = get_database_url()
    except RuntimeError:
        render_missing_database()
        return
    try:
        engine = _prepare_database(database_url)
    except Exception as exc:
        LOGGER.exception("Falha na conexão ou inicialização do Neon", exc_info=exc)
        render_database_error()
        return
    _run_with_session(engine)


main()
