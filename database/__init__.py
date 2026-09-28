"""Database package.

Import concrete modules directly (for example, ``database.repository``).
Keeping package initialization side-effect free prevents concurrent Streamlit
sessions from loading the model and repository graphs in conflicting orders.
"""

__all__: list[str] = []
