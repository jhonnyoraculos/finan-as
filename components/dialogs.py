"""Confirmation flows built with native Streamlit dialogs and buttons."""

from __future__ import annotations

import logging
from typing import Any, Callable, Literal, Mapping

import streamlit as st


logger = logging.getLogger(__name__)


def _state_key(key: str) -> str:
    return f"_confirmation_open_{key}"


def open_confirmation(key: str) -> None:
    """Open a confirmation flow on the current session."""

    st.session_state[_state_key(key)] = True


def close_confirmation(key: str) -> None:
    """Close a confirmation flow without running its action."""

    st.session_state[_state_key(key)] = False


def _rerun() -> None:
    rerun = getattr(st, "rerun", None)
    if rerun is not None:
        rerun()
        return
    experimental_rerun = getattr(st, "experimental_rerun", None)  # pragma: no cover
    if experimental_rerun is not None:
        experimental_rerun()


def render_confirmation(
    *,
    key: str,
    title: str,
    message: str,
    on_confirm: Callable[..., Any],
    confirm_label: str = "Confirmar",
    cancel_label: str = "Cancelar",
    confirm_args: tuple[Any, ...] = (),
    confirm_kwargs: Mapping[str, Any] | None = None,
    success_message: str | None = None,
    error_message: str = "Não foi possível concluir esta ação.",
) -> bool:
    """Render an open confirmation and return whether it is currently visible.

    Call ``open_confirmation(key)`` from any native button. Once confirmed, the
    callable runs, the dialog closes, and Streamlit reruns. Exceptions are logged
    while the user sees a concise message.
    """

    if not st.session_state.get(_state_key(key), False):
        return False

    kwargs = dict(confirm_kwargs or {})

    def content() -> None:
        st.write(message)
        cancel_column, confirm_column = st.columns(2)
        with cancel_column:
            if st.button(
                cancel_label,
                key=f"{key}_confirmation_cancel",
                width="stretch",
            ):
                close_confirmation(key)
                _rerun()
        with confirm_column:
            if st.button(
                confirm_label,
                key=f"{key}_confirmation_confirm",
                type="primary",
                width="stretch",
            ):
                try:
                    on_confirm(*confirm_args, **kwargs)
                except Exception:  # UI boundary: preserve details in logs only.
                    logger.exception("Confirmation action %s failed", key)
                    st.error(error_message)
                    return
                close_confirmation(key)
                if success_message:
                    toast = getattr(st, "toast", None)
                    if toast is not None:
                        toast(success_message, icon="✅")
                _rerun()

    dialog_decorator = getattr(st, "dialog", None)
    if dialog_decorator is not None:
        dialog_decorator(title)(content)()
    else:  # pragma: no cover - current Streamlit has st.dialog
        st.warning(title)
        content()
    return True


def confirmation_button(
    trigger_label: str,
    *,
    key: str,
    title: str,
    message: str,
    on_confirm: Callable[..., Any],
    confirm_label: str = "Confirmar",
    cancel_label: str = "Cancelar",
    trigger_type: str = "secondary",
    disabled: bool = False,
    help: str | None = None,
    width: Literal["content", "stretch"] = "content",
    use_container_width: bool | None = None,
    confirm_args: tuple[Any, ...] = (),
    confirm_kwargs: Mapping[str, Any] | None = None,
    success_message: str | None = None,
    error_message: str = "Não foi possível concluir esta ação.",
) -> bool:
    """Render a native trigger button and its confirmation dialog/fallback."""

    # Keep view compatibility while using Streamlit's current width API.
    button_width = (
        ("stretch" if use_container_width else "content")
        if use_container_width is not None
        else width
    )

    if st.button(
        trigger_label,
        key=f"{key}_confirmation_trigger",
        type=trigger_type,
        disabled=disabled,
        help=help,
        width=button_width,
    ):
        open_confirmation(key)

    return render_confirmation(
        key=key,
        title=title,
        message=message,
        on_confirm=on_confirm,
        confirm_label=confirm_label,
        cancel_label=cancel_label,
        confirm_args=confirm_args,
        confirm_kwargs=confirm_kwargs,
        success_message=success_message,
        error_message=error_message,
    )


# Common naming used in view modules.
confirm_action = confirmation_button
confirmation_dialog = render_confirmation


__all__ = [
    "close_confirmation",
    "confirm_action",
    "confirmation_button",
    "confirmation_dialog",
    "open_confirmation",
    "render_confirmation",
]
