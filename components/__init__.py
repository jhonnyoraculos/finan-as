"""Reusable UI component package with side-effect-free initialization.

Import components from their concrete modules so loading navigation does not
also import charts, dialogs and every other Streamlit component.
"""

__all__: list[str] = []
