"""Centralized Liquid Glass styling and Plotly theme helpers.

Only static, application-owned HTML/CSS is injected here. Values supplied by a
user belong in the component layer, where they are escaped before rendering.
"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any, Final, Mapping

import streamlit as st

if TYPE_CHECKING:
    from plotly.graph_objects import Figure


BREAKPOINTS: Final[dict[str, int]] = {
    "mobile": 600,
    "desktop": 1100,
}

COLORS: Final[dict[str, str]] = {
    "background": "#070B1A",
    "surface": "rgba(19, 29, 55, 0.68)",
    "surface_strong": "rgba(24, 36, 65, 0.86)",
    "text": "#F5F7FC",
    "muted": "#9AA8C2",
    "blue": "#6C9EFF",
    "green": "#72D7A3",
    "coral": "#FF8D86",
    "orange": "#F3B36A",
    "purple": "#B49AF8",
    "yellow": "#E7CB74",
    "grid": "rgba(164, 184, 221, 0.10)",
}


_GLOBAL_CSS: Final[str] = r"""
<style>
:root {
    color-scheme: dark;
    --finance-bg: #070B1A;
    --finance-bg-soft: #0A1023;
    --finance-glass: rgba(19, 29, 55, 0.64);
    --finance-glass-strong: rgba(24, 36, 65, 0.84);
    --finance-border: rgba(255, 255, 255, 0.09);
    --finance-highlight: rgba(255, 255, 255, 0.12);
    --finance-text: #F5F7FC;
    --finance-muted: #9AA8C2;
    --finance-blue: #6C9EFF;
    --finance-green: #72D7A3;
    --finance-coral: #FF8D86;
    --finance-orange: #F3B36A;
    --finance-purple: #B49AF8;
    --finance-yellow: #E7CB74;
    --finance-shadow: 0 18px 48px rgba(0, 0, 0, 0.24);
    --finance-radius: 24px;
    --finance-nav-height: 76px;
}

html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display",
        "SF Pro Text", Inter, Roboto, "Segoe UI", sans-serif;
}

html, body, [data-testid="stAppViewContainer"], .stApp {
    background: var(--finance-bg);
    color: var(--finance-text);
}

[data-testid="stAppViewContainer"] {
    background:
        radial-gradient(circle at 12% -8%, rgba(63, 100, 181, 0.18), transparent 31rem),
        radial-gradient(circle at 96% 18%, rgba(118, 85, 175, 0.11), transparent 27rem),
        linear-gradient(150deg, #070B1A 0%, #080D1E 54%, #060A16 100%);
    background-attachment: fixed;
}

[data-testid="stHeader"] {
    background: transparent;
    height: 2.25rem;
}

[data-testid="stToolbar"] {
    right: 0.35rem;
}

/* Keep Streamlit status controls available, but remove decorative chrome. */
#MainMenu,
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
footer {
    display: none !important;
}

[data-testid="stMain"] > div,
.block-container {
    width: 100%;
    max-width: 1180px;
}

.block-container {
    padding-top: 1rem;
    padding-bottom: 2.5rem;
}

h1, h2, h3, h4, h5, h6, p, label, span {
    color: inherit;
}

h1 {
    letter-spacing: -0.045em;
    font-weight: 720;
}

h2, h3 {
    letter-spacing: -0.025em;
}

a { color: var(--finance-blue); }

/* Native Streamlit controls: accessible touch targets with glass surfaces. */
.stButton > button,
.stDownloadButton > button,
[data-testid="stFormSubmitButton"] > button,
[data-testid="stBaseButton-secondary"],
[data-testid="stBaseButton-primary"] {
    min-height: 44px;
    border-radius: 14px;
    border: 1px solid var(--finance-border);
    background: rgba(255, 255, 255, 0.055);
    color: var(--finance-text);
    font-weight: 620;
    transition: transform 180ms ease, background 180ms ease,
        border-color 180ms ease, box-shadow 180ms ease;
}

.stButton > button:hover,
.stDownloadButton > button:hover,
[data-testid="stFormSubmitButton"] > button:hover {
    border-color: rgba(149, 181, 255, 0.38);
    background: rgba(108, 158, 255, 0.13);
    color: var(--finance-text);
    transform: translateY(-1px);
}

.stButton > button:active,
.stDownloadButton > button:active,
[data-testid="stFormSubmitButton"] > button:active {
    transform: scale(0.985);
}

.stButton > button:focus-visible,
.stDownloadButton > button:focus-visible,
input:focus-visible,
textarea:focus-visible {
    outline: 2px solid rgba(108, 158, 255, 0.78) !important;
    outline-offset: 2px;
}

[data-testid="stBaseButton-primary"] {
    background: linear-gradient(135deg, #769FFF, #8D83EE);
    border-color: rgba(255, 255, 255, 0.20);
    box-shadow: 0 8px 26px rgba(79, 103, 211, 0.26);
    color: #FFFFFF;
}

[data-baseweb="input"] > div,
[data-baseweb="textarea"] > div,
[data-baseweb="select"] > div,
[data-baseweb="base-input"] {
    min-height: 46px;
    border-radius: 15px !important;
    border-color: var(--finance-border) !important;
    background: rgba(255, 255, 255, 0.055) !important;
    color: var(--finance-text) !important;
}

[data-baseweb="input"] input,
[data-baseweb="textarea"] textarea,
[data-baseweb="select"] input {
    color: var(--finance-text) !important;
    caret-color: var(--finance-blue);
}

[data-baseweb="popover"],
[role="listbox"],
[data-baseweb="menu"] {
    background: #11192D !important;
    color: var(--finance-text) !important;
}

[data-testid="stDateInput"] input,
[data-testid="stNumberInput"] input,
.stTextInput input,
.stTextArea textarea,
.stSelectbox [role="combobox"] {
    min-height: 44px;
    font-size: 16px; /* Prevents iOS Safari auto-zoom. */
}

[data-testid="stExpander"],
[data-testid="stForm"],
[data-testid="stPopoverBody"] {
    border: 1px solid var(--finance-border);
    border-radius: 20px;
    background: rgba(17, 26, 48, 0.54);
}

[data-testid="stTabs"] [data-baseweb="tab-list"] {
    gap: 0.25rem;
    overflow-x: auto;
    padding: 0.25rem;
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.035);
    scrollbar-width: none;
}

[data-testid="stTabs"] [data-baseweb="tab-list"]::-webkit-scrollbar {
    display: none;
}

[data-testid="stTabs"] [data-baseweb="tab"] {
    min-height: 44px;
    padding: 0.45rem 0.78rem;
    border-radius: 12px;
    color: var(--finance-muted);
    font-weight: 620;
}

[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] {
    background: rgba(108, 158, 255, 0.13);
    color: var(--finance-text);
}

[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
    display: none;
}

[data-testid="stAlert"] {
    border: 1px solid var(--finance-border);
    border-radius: 16px;
    background: rgba(18, 28, 51, 0.68);
}

[data-testid="stProgress"] > div > div {
    border-radius: 999px;
}

[data-testid="stDialog"] > div,
[role="dialog"] > div {
    border: 1px solid var(--finance-border);
    border-radius: 24px;
    background: rgba(12, 19, 37, 0.95);
    box-shadow: 0 28px 80px rgba(0, 0, 0, 0.46);
    backdrop-filter: blur(24px);
    -webkit-backdrop-filter: blur(24px);
}

[data-testid="stToast"] {
    border: 1px solid var(--finance-border);
    border-radius: 16px;
    background: rgba(17, 27, 49, 0.94);
    color: var(--finance-text);
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
}

/* Shared component primitives. */
.finance-glass-card {
    position: relative;
    isolation: isolate;
    overflow: hidden;
    width: 100%;
    margin: 0 0 0.8rem;
    padding: 1rem;
    border: 1px solid var(--finance-border);
    border-radius: var(--finance-radius);
    background:
        linear-gradient(145deg, rgba(255,255,255,0.065), rgba(255,255,255,0.018)),
        var(--finance-glass);
    box-shadow: var(--finance-shadow), inset 0 1px 0 rgba(255,255,255,0.045);
    backdrop-filter: blur(22px) saturate(125%);
    -webkit-backdrop-filter: blur(22px) saturate(125%);
    transition: transform 190ms ease, border-color 190ms ease,
        background 190ms ease;
}

.finance-glass-card::before {
    content: "";
    position: absolute;
    z-index: -1;
    inset: 0 0 auto 0;
    height: 48%;
    pointer-events: none;
    background: linear-gradient(180deg, rgba(255,255,255,0.045), transparent);
}

@media (hover: hover) and (pointer: fine) {
    .finance-glass-card:hover {
        transform: translateY(-2px);
        border-color: rgba(255, 255, 255, 0.15);
    }
}

.finance-card-row,
.finance-card-heading,
.finance-transaction,
.finance-bill-row,
.finance-progress-heading {
    display: flex;
    align-items: center;
    gap: 0.75rem;
}

.finance-card-row,
.finance-card-heading,
.finance-transaction,
.finance-bill-row,
.finance-progress-heading {
    justify-content: space-between;
}

.finance-card-main {
    min-width: 0;
    flex: 1 1 auto;
}

.finance-kicker,
.finance-card-meta,
.finance-transaction-meta,
.finance-bill-meta,
.finance-progress-caption {
    color: var(--finance-muted);
    font-size: 0.78rem;
    line-height: 1.35;
}

.finance-kicker {
    margin-bottom: 0.35rem;
    font-weight: 580;
    letter-spacing: 0.01em;
}

.finance-card-title,
.finance-transaction-title,
.finance-bill-title {
    overflow: hidden;
    color: var(--finance-text);
    font-size: 0.96rem;
    font-weight: 650;
    line-height: 1.3;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.finance-card-value {
    margin-top: 0.1rem;
    color: var(--finance-text);
    font-size: clamp(1.45rem, 5vw, 2rem);
    font-variant-numeric: tabular-nums;
    font-weight: 720;
    letter-spacing: -0.035em;
}

.finance-card-value--small {
    font-size: 1.16rem;
    letter-spacing: -0.018em;
}

.finance-value-positive { color: var(--finance-green); }
.finance-value-negative { color: var(--finance-coral); }
.finance-value-blue { color: var(--finance-blue); }
.finance-value-orange { color: var(--finance-orange); }
.finance-value-purple { color: var(--finance-purple); }
.finance-value-yellow { color: var(--finance-yellow); }
.finance-value-muted { color: var(--finance-muted); }

.finance-delta,
.finance-status {
    display: inline-flex;
    align-items: center;
    min-height: 25px;
    margin-top: 0.5rem;
    padding: 0.22rem 0.52rem;
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 999px;
    background: rgba(255,255,255,0.045);
    color: var(--finance-muted);
    font-size: 0.72rem;
    font-weight: 620;
}

.finance-delta--positive,
.finance-status--paid {
    background: rgba(114,215,163,0.10);
    color: var(--finance-green);
}

.finance-delta--negative,
.finance-status--late {
    background: rgba(255,141,134,0.10);
    color: var(--finance-coral);
}

.finance-status--pending {
    background: rgba(231,203,116,0.09);
    color: var(--finance-yellow);
}

.finance-icon {
    display: inline-grid;
    flex: 0 0 auto;
    width: 42px;
    height: 42px;
    place-items: center;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px;
    background: rgba(108,158,255,0.11);
    font-size: 1.1rem;
}

.finance-account-card {
    min-height: 145px;
    background:
        radial-gradient(circle at 90% -10%, var(--card-glow, rgba(108,158,255,0.20)), transparent 55%),
        linear-gradient(145deg, rgba(255,255,255,0.07), rgba(255,255,255,0.015)),
        var(--finance-glass);
}

.finance-credit-card {
    min-height: 206px;
    background:
        radial-gradient(circle at 102% -8%, var(--card-glow, rgba(243,179,106,0.28)), transparent 54%),
        linear-gradient(145deg, rgba(255,255,255,0.08), rgba(255,255,255,0.018)),
        rgba(18, 28, 51, 0.84);
}

.finance-card-brand {
    color: var(--finance-muted);
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.13em;
    text-transform: uppercase;
}

.finance-card-foot {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.8rem;
    margin-top: 1rem;
}

.finance-card-foot strong {
    display: block;
    margin-top: 0.15rem;
    color: var(--finance-text);
    font-size: 0.9rem;
    font-variant-numeric: tabular-nums;
}

.finance-transaction,
.finance-bill-row {
    min-height: 68px;
}

.finance-transaction-amount,
.finance-bill-amount {
    flex: 0 0 auto;
    text-align: right;
    font-size: 0.95rem;
    font-variant-numeric: tabular-nums;
    font-weight: 700;
}

.finance-progress-track {
    overflow: hidden;
    width: 100%;
    height: 8px;
    margin-top: 0.75rem;
    border-radius: 999px;
    background: rgba(255,255,255,0.075);
}

.finance-progress-bar {
    width: var(--progress, 0%);
    height: 100%;
    border-radius: inherit;
    background: var(--progress-color, var(--finance-blue));
    box-shadow: 0 0 18px color-mix(in srgb, var(--progress-color), transparent 58%);
}

.finance-sparkline {
    width: 100%;
    height: 112px;
    margin: 0.2rem 0 0.55rem;
}

.finance-sparkline svg {
    display: block;
    width: 100%;
    height: 100%;
    overflow: visible;
}

.finance-section-heading {
    display: flex;
    align-items: end;
    justify-content: space-between;
    gap: 1rem;
    margin: 1.35rem 0 0.7rem;
}

.finance-section-heading h2 {
    margin: 0;
    color: var(--finance-text);
    font-size: 1.08rem;
    font-weight: 690;
}

.finance-section-heading p {
    margin: 0.2rem 0 0;
    color: var(--finance-muted);
    font-size: 0.78rem;
}

.finance-section-action {
    color: var(--finance-blue);
    font-size: 0.78rem;
    font-weight: 620;
}

.finance-input-error {
    margin: -0.35rem 0 0.55rem;
    color: var(--finance-coral);
    font-size: 0.76rem;
}

/* Native-button navigation; CSS changes placement only. */
.st-key-finance_navigation {
    position: fixed;
    z-index: 990;
    right: max(0.7rem, env(safe-area-inset-right));
    bottom: max(0.55rem, env(safe-area-inset-bottom));
    left: max(0.7rem, env(safe-area-inset-left));
    width: auto;
    max-width: none;
    padding: 0.42rem 0.45rem;
    border: 1px solid rgba(255,255,255,0.11);
    border-radius: 23px;
    background: rgba(12, 19, 37, 0.86);
    box-shadow: 0 18px 55px rgba(0,0,0,0.42), inset 0 1px 0 rgba(255,255,255,0.06);
    backdrop-filter: blur(24px) saturate(140%);
    -webkit-backdrop-filter: blur(24px) saturate(140%);
}

.st-key-finance_navigation [data-testid="stHorizontalBlock"] {
    align-items: end;
    gap: 0.18rem;
}

.st-key-finance_navigation :is([data-testid="column"], [data-testid="stColumn"]) {
    min-width: 0 !important;
}

.st-key-finance_navigation button {
    min-height: 55px;
    padding: 0.25rem 0.12rem;
    border: 0;
    border-radius: 17px;
    background: transparent;
    box-shadow: none;
    color: var(--finance-muted);
    font-size: clamp(0.64rem, 2.5vw, 0.75rem);
    line-height: 1.18;
    white-space: pre-line;
}

.st-key-finance_navigation button p {
    font-size: clamp(0.64rem, 2.5vw, 0.75rem) !important;
    line-height: inherit !important;
    white-space: pre-line !important;
    word-break: keep-all !important;
    overflow-wrap: normal !important;
    hyphens: none !important;
}

.st-key-finance_navigation button[kind="primary"],
.st-key-finance_navigation [data-testid="stBaseButton-primary"] {
    background: rgba(108,158,255,0.14);
    color: #DDE7FF;
    box-shadow: inset 0 0 0 1px rgba(108,158,255,0.18);
}

.st-key-finance_navigation :is([data-testid="column"], [data-testid="stColumn"]):nth-child(3) button {
    min-height: 58px;
    margin-top: -0.42rem;
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 19px;
    background: linear-gradient(145deg, #779FFF, #8C82ED);
    box-shadow: 0 9px 27px rgba(75,94,207,0.38);
    color: #FFFFFF;
    font-size: 0.75rem;
}

/* Plotly containers blend into the surrounding glass surface. */
[data-testid="stPlotlyChart"] {
    overflow: hidden;
    border-radius: 20px;
}

/* Mobile: app-like spacing, one-column content and safe bottom inset. */
@media (max-width: 599.98px) {
    [data-testid="stHeader"] { height: 1.65rem; }
    [data-testid="stToolbar"] { display: none !important; }
    .block-container {
        padding: 0.35rem 0.78rem calc(var(--finance-nav-height) + 2.25rem);
    }
    h1 { font-size: 1.72rem; }
    .finance-glass-card {
        padding: 0.95rem;
        border-radius: 21px;
    }
    [data-testid="stHorizontalBlock"] {
        flex-wrap: wrap;
    }
    [data-testid="stHorizontalBlock"] > :is([data-testid="column"], [data-testid="stColumn"]) {
        flex: 1 1 100%;
        width: 100% !important;
    }
    /* Navigation columns must remain in a single row. */
    .st-key-finance_navigation [data-testid="stHorizontalBlock"] {
        flex-wrap: nowrap;
    }
    .st-key-finance_navigation [data-testid="stHorizontalBlock"] > :is([data-testid="column"], [data-testid="stColumn"]) {
        flex: 1 1 20%;
        width: 20% !important;
    }
    .st-key-finance_topbar [data-testid="stHorizontalBlock"] {
        width: 100%;
        flex-wrap: nowrap;
        align-items: center;
        gap: 0.65rem;
    }
    .st-key-finance_topbar :is([data-testid="column"], [data-testid="stColumn"]) {
        width: calc(50% - 0.325rem) !important;
        min-width: 0 !important;
        flex: 0 1 calc(50% - 0.325rem) !important;
    }
    /* Account cards stay swipeable instead of becoming a long vertical list. */
    .st-key-finance_accounts_carousel {
        overflow-x: auto;
        padding-bottom: 0.35rem;
        scrollbar-width: none;
    }
    .st-key-finance_accounts_carousel::-webkit-scrollbar { display: none; }
    .st-key-finance_accounts_carousel [data-testid="stHorizontalBlock"] {
        min-width: max-content;
        flex-wrap: nowrap;
    }
    .st-key-finance_accounts_carousel [data-testid="stHorizontalBlock"] > :is([data-testid="column"], [data-testid="stColumn"]) {
        width: min(78vw, 300px) !important;
        flex: 0 0 min(78vw, 300px) !important;
    }
    /* Calendar must remain a seven-day grid even at phone widths. */
    .st-key-finance_calendar_grid [data-testid="stHorizontalBlock"] {
        flex-wrap: nowrap;
        gap: 0.16rem;
    }
    .st-key-finance_calendar_grid [data-testid="stHorizontalBlock"] > :is([data-testid="column"], [data-testid="stColumn"]) {
        width: 14.285% !important;
        flex: 1 1 14.285% !important;
        min-width: 0 !important;
    }
    .st-key-finance_calendar_grid button {
        min-height: 44px;
        padding: 0.2rem 0;
        font-size: 0.72rem;
    }
}

/* Tablet: still bottom navigation, with denser dashboard columns. */
@media (min-width: 600px) and (max-width: 1099.98px) {
    .block-container {
        padding: 1rem 1.4rem calc(var(--finance-nav-height) + 2.3rem);
    }
    .st-key-finance_navigation {
        right: max(1.4rem, env(safe-area-inset-right));
        left: max(1.4rem, env(safe-area-inset-left));
    }
}

/* Desktop: a complete left rail and a fluid workspace use the available width. */
@media (min-width: 1100px) {
    [data-testid="stMain"] > div {
        max-width: none;
    }
    .block-container {
        max-width: none;
        margin: 0;
        padding: 1.4rem clamp(1.8rem, 3vw, 3.6rem) 3rem 15.5rem;
    }
    .st-key-finance_navigation {
        top: 50%;
        right: auto;
        bottom: auto;
        left: 1rem;
        width: 216px;
        max-height: calc(100vh - 2rem);
        overflow-y: auto;
        padding: 0.7rem;
        transform: translateY(-50%);
        scrollbar-width: thin;
    }
    .st-key-finance_navigation [data-testid="stHorizontalBlock"] {
        width: 100%;
        flex-direction: column !important;
        align-items: stretch;
        gap: 0.38rem;
    }
    .st-key-finance_navigation [data-testid="stHorizontalBlock"] > :is([data-testid="column"], [data-testid="stColumn"]) {
        width: 100% !important;
        min-width: 0 !important;
        flex: 0 0 auto !important;
        align-self: stretch !important;
    }
    .st-key-finance_navigation :is([data-testid="stButton"], .stButton),
    .st-key-finance_navigation button {
        width: 100%;
    }
    .st-key-finance_navigation button {
        min-height: 56px;
        font-size: 0.78rem;
        line-height: 1.22;
    }
    .st-key-finance_navigation button p {
        min-height: 0;
        font-size: 0.78rem !important;
        line-height: 1.22 !important;
        white-space: nowrap !important;
        word-break: normal !important;
        overflow-wrap: normal !important;
        hyphens: none !important;
    }
    .st-key-finance_navigation :is([data-testid="column"], [data-testid="stColumn"]):nth-child(3) button {
        margin-top: 0;
    }
}

@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        scroll-behavior: auto !important;
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
    }
}
</style>
"""


def inject_global_styles() -> None:
    """Inject the application's static responsive Liquid Glass stylesheet."""

    st.markdown(_GLOBAL_CSS, unsafe_allow_html=True)


def get_plotly_theme(*, height: int = 280, showlegend: bool = True) -> dict[str, Any]:
    """Return a fresh Plotly layout dictionary matching the app theme."""

    theme: dict[str, Any] = {
        "height": height,
        "margin": {"l": 8, "r": 8, "t": 22, "b": 8},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {
            "family": '-apple-system, BlinkMacSystemFont, "SF Pro Text", Inter, sans-serif',
            "color": COLORS["muted"],
            "size": 12,
        },
        "colorway": [
            COLORS["blue"],
            COLORS["green"],
            COLORS["coral"],
            COLORS["orange"],
            COLORS["purple"],
            COLORS["yellow"],
        ],
        "hoverlabel": {
            "bgcolor": "#111A30",
            "bordercolor": "rgba(255,255,255,0.12)",
            "font": {"color": COLORS["text"], "size": 12},
        },
        "hovermode": "x unified",
        "showlegend": showlegend,
        "legend": {
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
            "font": {"size": 11},
        },
        "xaxis": {
            "showgrid": False,
            "zeroline": False,
            "fixedrange": True,
            "tickfont": {"color": COLORS["muted"]},
        },
        "yaxis": {
            "showgrid": True,
            "gridcolor": COLORS["grid"],
            "zeroline": False,
            "fixedrange": True,
            "tickfont": {"color": COLORS["muted"]},
        },
    }
    return deepcopy(theme)


def apply_plotly_theme(
    figure: "Figure",
    *,
    height: int = 280,
    showlegend: bool = True,
    overrides: Mapping[str, Any] | None = None,
) -> "Figure":
    """Apply the shared Plotly layout in place and return ``figure``.

    ``overrides`` is passed to ``Figure.update_layout`` after the base theme,
    making small page-specific adjustments possible without duplicating it.
    """

    figure.update_layout(**get_plotly_theme(height=height, showlegend=showlegend))
    if overrides:
        figure.update_layout(**dict(overrides))
    return figure
