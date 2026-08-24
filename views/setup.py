"""Configuração inicial e onboarding da aplicação."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import streamlit as st

from components.widgets import money_input, notify_success
from views.common import ACCOUNT_TYPES, friendly_error, page_header, safe_rerun


def render_missing_database() -> None:
    """Explain local Neon configuration without exposing implementation errors."""

    page_header(
        "Conecte seu banco Neon",
        "Suas credenciais ficam apenas no computador e nunca entram no código.",
        eyebrow="Primeira configuração",
    )
    st.info("A variável `DATABASE_URL` ainda não foi configurada.", icon="🔐")
    st.markdown(
        """
        1. Crie um projeto gratuito no Neon e copie a *connection string*.
        2. Crie `.streamlit/secrets.toml` a partir do arquivo de exemplo.
        3. Use uma URL iniciada por `postgresql+psycopg://`.
        4. Reinicie o Streamlit; as tabelas serão criadas sem apagar dados.
        """
    )
    st.code(
        'DATABASE_URL = "postgresql+psycopg://usuario:senha@host.neon.tech/neondb?sslmode=require"',
        language="toml",
    )
    example = Path(".streamlit/secrets.toml.example")
    if example.exists():
        st.caption("Um modelo pronto está em `.streamlit/secrets.toml.example`.")


def render_database_error() -> None:
    page_header("Não foi possível conectar", "Revise a conexão do Neon e tente novamente.")
    st.error(
        "A conexão com o banco falhou. Confira host, senha, `sslmode=require` e sua internet.",
        icon="⚠️",
    )
    st.caption("O detalhe técnico foi mantido no terminal para não expor sua credencial na tela.")


def render_onboarding(repository: Any, user: Any) -> None:
    """Create the first account; every other step remains optional."""

    page_header(
        f"Bem-vindo, {getattr(user, 'name', 'você')}",
        "Comece com uma conta. Cartão e renda podem ser adicionados depois.",
        eyebrow="Suas finanças, no seu ritmo",
    )
    progress = st.progress(0.34, text="Etapa 1 de 3 · Primeira conta")
    with st.form("onboarding_account", clear_on_submit=False):
        name = st.text_input("Nome da conta", placeholder="Conta principal", max_chars=100)
        institution = st.text_input("Instituição", placeholder="Ex.: banco, carteira", max_chars=120)
        account_type = st.selectbox(
            "Tipo",
            options=list(ACCOUNT_TYPES),
            format_func=ACCOUNT_TYPES.get,
        )
        initial_balance = money_input(
            "Saldo atual",
            key="onboarding_initial_balance",
            value=Decimal("0"),
            allow_negative=True,
            help="Use o saldo disponível hoje; compras em fatura não entram aqui.",
        )
        submitted = st.form_submit_button(
            "Criar minha primeira conta",
            type="primary",
            use_container_width=True,
        )
    if submitted:
        if not name.strip():
            st.warning("Dê um nome para identificar a conta.")
            return
        try:
            repository.create_account(
                user_id=user.id,
                name=name.strip(),
                institution=institution.strip() or None,
                account_type=account_type,
                initial_balance=initial_balance or Decimal("0"),
                icon="💳" if account_type != "cash" else "💵",
                color="#6C9EFF",
            )
            progress.progress(1.0, text="Tudo pronto")
            notify_success("Conta criada. Bem-vindo às suas finanças!")
            safe_rerun()
        except Exception as exc:  # UI boundary
            friendly_error("Não foi possível criar sua conta.", exc)
