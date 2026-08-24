"""Explicit development/default-data seeds.

Nothing in this module runs on import or during :mod:`database.init_db`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from .models import Account, Category, Transaction, User
from .repository import FinanceRepository, repository_context

DEFAULT_CATEGORIES: tuple[tuple[str, str, str, str], ...] = (
    ("Alimentação", "expense", "🍽️", "#E8A66A"),
    ("Mercado", "expense", "🛒", "#75BFA3"),
    ("Moradia", "expense", "🏠", "#7CA7D9"),
    ("Transporte", "expense", "🚗", "#6EA8BE"),
    ("Saúde", "expense", "♡", "#D98282"),
    ("Lazer", "expense", "🎮", "#9A86C8"),
    ("Compras", "expense", "🛍️", "#C68AA5"),
    ("Tecnologia", "expense", "⌘", "#8299C5"),
    ("Educação", "expense", "📚", "#7BB7A5"),
    ("Assinaturas", "expense", "◉", "#9A86C8"),
    ("Contas", "expense", "▤", "#D5A85B"),
    ("Pets", "expense", "🐾", "#BB9676"),
    ("Viagem", "expense", "✈", "#68AFC0"),
    ("Investimentos", "both", "↗", "#8C7BC1"),
    ("Salário", "income", "↓", "#67B894"),
    ("Renda extra", "income", "+", "#75BFA3"),
    ("Outros", "both", "•••", "#8290A8"),
)


def seed_default_categories(
    session: Session, user_id: uuid.UUID | str
) -> list[Category]:
    """Create missing starter categories for one user, idempotently."""

    repository = FinanceRepository(session)
    uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    existing = {
        name.casefold(): category
        for category in session.scalars(
            select(Category).where(
                Category.user_id == uid,
                Category.deleted_at.is_(None),
            )
        )
        for name in (category.name,)
    }
    categories: list[Category] = []
    for name, kind, icon, color in DEFAULT_CATEGORIES:
        category = existing.get(name.casefold())
        if category is None:
            category = repository.create_category(
                uid, name, kind=kind, icon=icon, color=color
            )
        categories.append(category)
    return categories


def seed_demo_data(
    database_url: str | None = None,
    *,
    engine: Engine | None = None,
    user_id: uuid.UUID | str | None = None,
) -> dict[str, Any]:
    """Insert a small, visibly fake dataset for local development.

    This function is explicit and idempotent per user: if a ``demo_seed``
    transaction already exists it returns without duplicating movements.
    """

    with repository_context(database_url, engine=engine) as repository:
        if user_id:
            user = repository.require(User, user_id)
        else:
            user = repository.session.scalar(
                select(User)
                .where(
                    User.email == "demo.local@example.invalid",
                    User.deleted_at.is_(None),
                )
                .limit(1)
            )
            if user is None:
                user = repository.create_user(
                    "Usuário Demo", email="demo.local@example.invalid"
                )

        categories = seed_default_categories(repository.session, user.id)
        category_by_name = {category.name: category for category in categories}
        existing_demo_count = int(
            repository.session.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.user_id == user.id,
                    Transaction.source == "demo_seed",
                    Transaction.deleted_at.is_(None),
                )
            )
            or 0
        )
        if existing_demo_count:
            return {
                "user_id": user.id,
                "created": False,
                "transactions": existing_demo_count,
            }

        account = repository.session.scalar(
            select(Account)
            .where(
                Account.user_id == user.id,
                Account.name == "Conta principal",
                Account.deleted_at.is_(None),
            )
            .limit(1)
        )
        if account is None:
            account = repository.create_account(
                user.id,
                "Conta principal",
                institution="Banco Demo",
                account_type="digital",
                initial_balance=Decimal("1500.00"),
                color="#7CA7D9",
            )

        today = datetime.now(timezone.utc).date()
        transactions = [
            repository.create_transaction(
                user.id,
                "Salário demonstrativo",
                Decimal("4500.00"),
                "income",
                today.replace(day=1),
                category_id=category_by_name["Salário"].id,
                account_id=account.id,
                payment_method="transfer",
                source="demo_seed",
            ),
            repository.create_transaction(
                user.id,
                "Mercado demonstrativo",
                Decimal("184.70"),
                "expense",
                today - timedelta(days=min(3, today.day - 1)),
                category_id=category_by_name["Mercado"].id,
                account_id=account.id,
                payment_method="pix",
                source="demo_seed",
            ),
        ]
        bill = repository.create_bill(
            user.id,
            "Internet demonstrativa",
            Decimal("119.90"),
            today + timedelta(days=5),
            category_id=category_by_name["Contas"].id,
            account_id=account.id,
            recurrence_key=f"demo:{user.id}:internet",
        )
        return {
            "user_id": user.id,
            "created": True,
            "transactions": len(transactions),
            "bill_id": bill.id,
        }


__all__ = ["DEFAULT_CATEGORIES", "seed_default_categories", "seed_demo_data"]
