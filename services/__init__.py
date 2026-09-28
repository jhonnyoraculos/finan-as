"""Business-service package with side-effect-free initialization.

Application code imports each concrete service module directly. Avoiding eager
re-exports keeps startup fast and prevents cross-thread import lock cycles.
"""

__all__: list[str] = []
