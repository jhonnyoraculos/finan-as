"""SQLAlchemy models for the personal-finance application.

The schema deliberately uses portable SQLAlchemy types while targeting PostgreSQL.
UUIDs make the data model ready for multiple users, and all monetary values use
``NUMERIC(14, 2)`` / :class:`decimal.Decimal`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

MONEY = Numeric(14, 2)
ZERO = Decimal("0.00")


class Base(DeclarativeBase):
    """Declarative base shared by every table."""


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, unique=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    accounts: Mapped[list[Account]] = relationship(back_populates="user")
    categories: Mapped[list[Category]] = relationship(back_populates="user")
    transactions: Mapped[list[Transaction]] = relationship(back_populates="user")
    credit_cards: Mapped[list[CreditCard]] = relationship(back_populates="user")
    settings: Mapped[AppSettings | None] = relationship(
        back_populates="user", uselist=False
    )


class Account(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        Index("ix_accounts_user_active", "user_id", "is_active"),
        CheckConstraint(
            "account_type IN ('checking','savings','digital','wallet','cash',"
            "'investment','other')",
            name="ck_accounts_type",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    institution: Mapped[str | None] = mapped_column(String(120), nullable=True)
    account_type: Mapped[str] = mapped_column(
        String(24), nullable=False, default="checking"
    )
    initial_balance: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=ZERO
    )
    icon: Mapped[str | None] = mapped_column(String(40), nullable=True)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped[User] = relationship(back_populates="accounts")
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="account", foreign_keys="Transaction.account_id"
    )
    destination_transactions: Mapped[list[Transaction]] = relationship(
        back_populates="destination_account",
        foreign_keys="Transaction.destination_account_id",
    )
    credit_cards: Mapped[list[CreditCard]] = relationship(
        back_populates="payment_account"
    )


class Category(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (
        Index("ix_categories_user_kind", "user_id", "kind"),
        CheckConstraint(
            "kind IN ('income','expense','both')", name="ck_categories_kind"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False, default="expense")
    icon: Mapped[str | None] = mapped_column(String(40), nullable=True)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped[User] = relationship(back_populates="categories")
    parent: Mapped[Category | None] = relationship(
        remote_side="Category.id", back_populates="children"
    )
    children: Mapped[list[Category]] = relationship(back_populates="parent")
    transactions: Mapped[list[Transaction]] = relationship(back_populates="category")


class CreditCard(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "credit_cards"
    __table_args__ = (
        Index("ix_credit_cards_user_active", "user_id", "is_active"),
        CheckConstraint("closing_day BETWEEN 1 AND 31", name="ck_card_closing_day"),
        CheckConstraint("due_day BETWEEN 1 AND 31", name="ck_card_due_day"),
        CheckConstraint("credit_limit >= 0", name="ck_card_limit_nonnegative"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    bank: Mapped[str | None] = mapped_column(String(120), nullable=True)
    credit_limit: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=ZERO)
    closing_day: Mapped[int] = mapped_column(Integer, nullable=False)
    due_day: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_four_digits: Mapped[str | None] = mapped_column(String(4), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped[User] = relationship(back_populates="credit_cards")
    payment_account: Mapped[Account | None] = relationship(
        back_populates="credit_cards"
    )
    invoices: Mapped[list[CreditCardInvoice]] = relationship(
        back_populates="credit_card"
    )
    transactions: Mapped[list[Transaction]] = relationship(back_populates="credit_card")


class CreditCardInvoice(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "credit_card_invoices"
    __table_args__ = (
        UniqueConstraint(
            "credit_card_id", "reference_month", name="uq_invoice_card_reference"
        ),
        Index("ix_invoices_user_status_due", "user_id", "status", "due_date"),
        CheckConstraint(
            "status IN ('open','closed','paid','overdue','cancelled')",
            name="ck_invoice_status",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    credit_card_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("credit_cards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Always the first day of the invoice's calendar month.
    reference_month: Mapped[date] = mapped_column(Date, nullable=False)
    closing_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=ZERO)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payment_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )

    credit_card: Mapped[CreditCard] = relationship(back_populates="invoices")
    user: Mapped[User] = relationship()
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="invoice", foreign_keys="Transaction.invoice_id"
    )
    installments: Mapped[list[Installment]] = relationship(back_populates="invoice")
    payment_transaction: Mapped[Transaction | None] = relationship(
        foreign_keys=[payment_transaction_id], post_update=True
    )


class Transaction(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_user_date", "user_id", "transaction_date"),
        Index(
            "ix_transactions_user_type_date",
            "user_id",
            "transaction_type",
            "transaction_date",
        ),
        Index("ix_transactions_account_date", "account_id", "transaction_date"),
        Index(
            "ix_transactions_destination_date",
            "destination_account_id",
            "transaction_date",
        ),
        Index("ix_transactions_category_date", "category_id", "transaction_date"),
        Index("ix_transactions_card_date", "credit_card_id", "transaction_date"),
        Index("ix_transactions_invoice", "invoice_id"),
        Index("ix_transactions_transfer_group", "transfer_group_id"),
        CheckConstraint("amount >= 0", name="ck_transaction_amount_nonnegative"),
        CheckConstraint(
            "transaction_type IN ('income','expense','transfer')",
            name="ck_transaction_type",
        ),
        CheckConstraint(
            "payment_method IS NULL OR payment_method IN "
            "('pix','cash','debit','credit','boleto','transfer','other')",
            name="ck_transaction_payment_method",
        ),
        CheckConstraint(
            "status IN ('pending','paid','cancelled','refunded')",
            name="ck_transaction_status",
        ),
        CheckConstraint(
            "transfer_direction IS NULL OR transfer_direction IN ('out','in')",
            name="ck_transfer_direction",
        ),
        CheckConstraint(
            "installment_number IS NULL OR installment_number >= 1",
            name="ck_transaction_installment_number",
        ),
        CheckConstraint(
            "installment_count IS NULL OR installment_count >= 1",
            name="ck_transaction_installment_count",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(12), nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    destination_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    credit_card_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("credit_cards.id", ondelete="SET NULL"), nullable=True
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("credit_card_invoices.id", ondelete="SET NULL"), nullable=True
    )
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    competence_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    installment_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    installment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    installment_group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    transfer_group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    transfer_direction: Mapped[str | None] = mapped_column(String(4), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="paid")
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_refund: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    refunded_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")

    user: Mapped[User] = relationship(back_populates="transactions")
    account: Mapped[Account | None] = relationship(
        back_populates="transactions", foreign_keys=[account_id]
    )
    destination_account: Mapped[Account | None] = relationship(
        back_populates="destination_transactions", foreign_keys=[destination_account_id]
    )
    category: Mapped[Category | None] = relationship(back_populates="transactions")
    credit_card: Mapped[CreditCard | None] = relationship(back_populates="transactions")
    invoice: Mapped[CreditCardInvoice | None] = relationship(
        back_populates="transactions", foreign_keys=[invoice_id]
    )
    refunded_transaction: Mapped[Transaction | None] = relationship(
        remote_side="Transaction.id", foreign_keys=[refunded_transaction_id]
    )
    installment: Mapped[Installment | None] = relationship(
        back_populates="transaction", uselist=False
    )


class Installment(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "installments"
    __table_args__ = (
        UniqueConstraint(
            "installment_group_id",
            "installment_number",
            name="uq_installment_group_number",
        ),
        Index("ix_installments_user_due", "user_id", "due_date"),
        Index("ix_installments_invoice", "invoice_id"),
        CheckConstraint("amount >= 0", name="ck_installment_amount_nonnegative"),
        CheckConstraint("installment_number >= 1", name="ck_installment_number"),
        CheckConstraint("installment_count >= 1", name="ck_installment_count"),
        CheckConstraint(
            "status IN ('pending','posted','paid','cancelled')",
            name="ck_installment_status",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    installment_group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    credit_card_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("credit_cards.id", ondelete="SET NULL"), nullable=True
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("credit_card_invoices.id", ondelete="SET NULL"), nullable=True
    )
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    installment_number: Mapped[int] = mapped_column(Integer, nullable=False)
    installment_count: Mapped[int] = mapped_column(Integer, nullable=False)
    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    competence_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending")

    transaction: Mapped[Transaction | None] = relationship(back_populates="installment")
    invoice: Mapped[CreditCardInvoice | None] = relationship(
        back_populates="installments"
    )
    user: Mapped[User] = relationship()
    credit_card: Mapped[CreditCard | None] = relationship()


class Bill(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "bills"
    __table_args__ = (
        Index("ix_bills_user_status_due", "user_id", "status", "due_date"),
        Index("ix_bills_recurring_due", "recurring_transaction_id", "due_date"),
        CheckConstraint("amount >= 0", name="ck_bill_amount_nonnegative"),
        CheckConstraint(
            "status IN ('pending','paid','overdue','cancelled')", name="ck_bill_status"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    recurring_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recurring_transactions.id", ondelete="SET NULL"), nullable=True
    )
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )
    recurrence_key: Mapped[str | None] = mapped_column(
        String(160), nullable=True, unique=True
    )
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending")
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship()
    category: Mapped[Category | None] = relationship()
    account: Mapped[Account | None] = relationship()
    recurring_transaction: Mapped[RecurringTransaction | None] = relationship()
    transaction: Mapped[Transaction | None] = relationship()


class RecurringTransaction(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "recurring_transactions"
    __table_args__ = (
        Index("ix_recurring_user_next", "user_id", "is_active", "next_run_date"),
        CheckConstraint("amount >= 0", name="ck_recurring_amount_nonnegative"),
        CheckConstraint(
            "transaction_type IN ('income','expense')", name="ck_recurring_type"
        ),
        CheckConstraint(
            "frequency IN ('weekly','monthly','yearly')", name="ck_recurring_frequency"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(12), nullable=False)
    frequency: Mapped[str] = mapped_column(String(12), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_run_date: Mapped[date] = mapped_column(Date, nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    credit_card_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("credit_cards.id", ondelete="SET NULL"), nullable=True
    )
    payment_method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auto_post: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user: Mapped[User] = relationship()
    category: Mapped[Category | None] = relationship()
    account: Mapped[Account | None] = relationship()
    credit_card: Mapped[CreditCard | None] = relationship()


class Budget(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "category_id", "month", name="uq_budget_category_month"
        ),
        Index("ix_budgets_user_month", "user_id", "month"),
        CheckConstraint("amount >= 0", name="ck_budget_amount_nonnegative"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    month: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    user: Mapped[User] = relationship()
    category: Mapped[Category] = relationship()


class FinancialGoal(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "financial_goals"
    __table_args__ = (
        Index("ix_goals_user_status", "user_id", "status"),
        CheckConstraint("target_amount >= 0", name="ck_goal_target_nonnegative"),
        CheckConstraint(
            "status IN ('active','completed','paused','cancelled')",
            name="ck_goal_status",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    target_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    initial_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=ZERO)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(40), nullable=True)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="active")

    contributions: Mapped[list[GoalContribution]] = relationship(
        back_populates="goal", cascade="all, delete-orphan"
    )
    user: Mapped[User] = relationship()


class GoalContribution(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "goal_contributions"
    __table_args__ = (
        Index("ix_contributions_goal_date", "goal_id", "contribution_date"),
        CheckConstraint("amount > 0", name="ck_contribution_amount_positive"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    goal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("financial_goals.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    contribution_date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    goal: Mapped[FinancialGoal] = relationship(back_populates="contributions")
    user: Mapped[User] = relationship()
    account: Mapped[Account | None] = relationship()


class Asset(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "assets"
    __table_args__ = (
        Index("ix_assets_user_active", "user_id", "is_active"),
        CheckConstraint("current_value >= 0", name="ck_asset_value_nonnegative"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False)
    current_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    acquired_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped[User] = relationship()


class Liability(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "liabilities"
    __table_args__ = (
        Index("ix_liabilities_user_active", "user_id", "is_active"),
        CheckConstraint(
            "current_balance >= 0", name="ck_liability_balance_nonnegative"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    liability_type: Mapped[str] = mapped_column(String(32), nullable=False)
    current_balance: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped[User] = relationship()


class Subscription(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("ix_subscriptions_user_next", "user_id", "is_active", "next_charge_date"),
        CheckConstraint("amount >= 0", name="ck_subscription_amount_nonnegative"),
        CheckConstraint(
            "frequency IN ('weekly','monthly','yearly')",
            name="ck_subscription_frequency",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    frequency: Mapped[str] = mapped_column(
        String(12), nullable=False, default="monthly"
    )
    next_charge_date: Mapped[date] = mapped_column(Date, nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    credit_card_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("credit_cards.id", ondelete="SET NULL"), nullable=True
    )
    recurring_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recurring_transactions.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped[User] = relationship()
    category: Mapped[Category | None] = relationship()
    account: Mapped[Account | None] = relationship()
    credit_card: Mapped[CreditCard | None] = relationship()
    recurring_transaction: Mapped[RecurringTransaction | None] = relationship()


class FavoriteTransaction(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "favorite_transactions"
    __table_args__ = (Index("ix_favorites_user_name", "user_id", "name"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    transaction_type: Mapped[str] = mapped_column(String(12), nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    credit_card_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("credit_cards.id", ondelete="SET NULL"), nullable=True
    )
    payment_method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship()
    category: Mapped[Category | None] = relationship()
    account: Mapped[Account | None] = relationship()
    credit_card: Mapped[CreditCard | None] = relationship()


class AppSettings(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "app_settings"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_app_settings_user"),
        CheckConstraint(
            "financial_month_start_day BETWEEN 1 AND 28",
            name="ck_settings_month_start",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")
    financial_month_start_day: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    default_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    default_category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    privacy_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    theme: Mapped[str] = mapped_column(
        String(24), nullable=False, default="dark_liquid"
    )
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    user: Mapped[User] = relationship(back_populates="settings")
    default_account: Mapped[Account | None] = relationship()
    default_category: Mapped[Category | None] = relationship()


class NetWorthSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "net_worth_snapshots"
    __table_args__ = (
        UniqueConstraint("user_id", "snapshot_date", name="uq_net_worth_user_date"),
        Index("ix_net_worth_user_date", "user_id", "snapshot_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    assets_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=ZERO)
    liabilities_total: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=ZERO
    )
    net_worth: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=ZERO)

    user: Mapped[User] = relationship()


# Public registry used by generic repository helpers and export tooling.
MODEL_BY_TABLE: dict[str, type[Base]] = {
    mapper.class_.__tablename__: mapper.class_ for mapper in Base.registry.mappers
}


__all__ = [
    "MODEL_BY_TABLE",
    "MONEY",
    "ZERO",
    "Account",
    "AppSettings",
    "Asset",
    "Base",
    "Bill",
    "Budget",
    "Category",
    "CreditCard",
    "CreditCardInvoice",
    "FavoriteTransaction",
    "FinancialGoal",
    "GoalContribution",
    "Installment",
    "Liability",
    "NetWorthSnapshot",
    "RecurringTransaction",
    "Subscription",
    "Transaction",
    "User",
]
