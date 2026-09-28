"""Transactional repositories and efficient finance read models.

Methods flush but do not commit. Use :func:`repository_context` for an atomic
unit of work, or pass a caller-managed SQLAlchemy ``Session``.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Generic, TypeVar, cast

from sqlalchemy import Engine, and_, case, func, or_, select
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session, joinedload

from .connection import session_scope
from .models import (
    ZERO,
    Account,
    AppSettings,
    Asset,
    Base,
    Bill,
    Budget,
    Category,
    CreditCard,
    CreditCardInvoice,
    FavoriteTransaction,
    FinancialGoal,
    GoalContribution,
    Installment,
    Liability,
    Loan,
    LoanInstallment,
    NetWorthSnapshot,
    RecurringTransaction,
    SoftDeleteMixin,
    Subscription,
    Transaction,
    User,
)

ModelT = TypeVar("ModelT", bound=Base)
MONEY_QUANTUM = Decimal("0.01")


class RepositoryError(RuntimeError):
    """Base persistence exception safe to handle at the UI boundary."""


class RecordNotFoundError(RepositoryError):
    """Requested record does not exist for the current user."""


class ValidationError(RepositoryError):
    """A write would violate a financial invariant."""


@dataclass(frozen=True, slots=True)
class Page(Generic[ModelT]):
    items: list[ModelT]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        return math.ceil(self.total / self.page_size) if self.total else 0

    @property
    def has_next(self) -> bool:
        return self.page < self.pages

    @property
    def has_previous(self) -> bool:
        return self.page > 1


@dataclass(frozen=True, slots=True)
class AccountBalance:
    account: Account
    balance: Decimal


@dataclass(frozen=True, slots=True)
class MonthlySummary:
    income: Decimal
    expenses: Decimal
    balance: Decimal
    transaction_count: int


@dataclass(frozen=True, slots=True)
class CardSummary:
    card: CreditCard
    open_amount: Decimal
    available_limit: Decimal
    utilization_percent: Decimal


@dataclass(frozen=True, slots=True)
class InstallmentPlanSummary:
    group_id: uuid.UUID
    description: str
    credit_card_id: uuid.UUID | None
    total_installments: int
    paid_installments: int
    remaining_installments: int
    remaining_amount: Decimal
    next_due_date: date | None
    end_date: date


@dataclass(frozen=True, slots=True)
class LoanSummary:
    loan: Loan
    paid_installments: int
    remaining_installments: int
    outstanding_amount: Decimal
    next_installment: LoanInstallment | None
    end_date: date


@dataclass(frozen=True, slots=True)
class BackupStats:
    transaction_count: int
    last_transaction_date: date | None


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("Identificador inválido.") from exc


def _money(value: Decimal | int | str) -> Decimal:
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
        amount = amount.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    except Exception as exc:
        raise ValidationError("Valor monetário inválido.") from exc
    if not amount.is_finite():
        raise ValidationError("Valor monetário inválido.")
    return amount


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _next_month(value: date) -> date:
    return date(value.year + (value.month == 12), value.month % 12 + 1, 1)


def _search_pattern(value: str) -> str:
    escaped = (
        value.strip()
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


class FinanceRepository:
    """Persistence facade bound to a caller-owned SQLAlchemy session."""

    def __init__(self, session: Session):
        self.session = session

    def _owned_reference(
        self,
        model: type[ModelT],
        value: uuid.UUID | str | None,
        user_id: uuid.UUID,
    ) -> uuid.UUID | None:
        if value is None:
            return None
        record_id = _as_uuid(value)
        self.require(model, record_id, user_id=user_id)
        return record_id

    # Generic ownership-aware CRUD -------------------------------------------------
    def create(self, model: type[ModelT], /, **values: Any) -> ModelT:
        record = model(**values)
        self.session.add(record)
        self.session.flush()
        return record

    def get(
        self,
        model: type[ModelT],
        record_id: uuid.UUID | str,
        *,
        user_id: uuid.UUID | str | None = None,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> ModelT | None:
        query = select(model).where(model.id == _as_uuid(record_id))  # type: ignore[attr-defined]
        if user_id is not None and hasattr(model, "user_id"):
            query = query.where(model.user_id == _as_uuid(user_id))  # type: ignore[attr-defined]
        if not include_deleted and hasattr(model, "deleted_at"):
            query = query.where(model.deleted_at.is_(None))  # type: ignore[attr-defined]
        if for_update:
            query = query.with_for_update()
        return self.session.scalar(query)

    def require(
        self,
        model: type[ModelT],
        record_id: uuid.UUID | str,
        *,
        user_id: uuid.UUID | str | None = None,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> ModelT:
        record = self.get(
            model,
            record_id,
            user_id=user_id,
            include_deleted=include_deleted,
            for_update=for_update,
        )
        if record is None:
            raise RecordNotFoundError(f"{model.__name__} não encontrado.")
        return record

    def update_fields(
        self,
        model: type[ModelT],
        record_id: uuid.UUID | str,
        values: Mapping[str, Any],
        *,
        user_id: uuid.UUID | str | None = None,
    ) -> ModelT:
        if model is Transaction:
            if user_id is None:
                raise ValidationError("Informe o usuário para editar uma transação.")
            return cast(ModelT, self.update_transaction(user_id, record_id, **dict(values)))
        record = self.require(model, record_id, user_id=user_id, for_update=True)
        writable = {column.key for column in inspect(model).columns} - {
            "id",
            "user_id",
            "created_at",
            "updated_at",
            "deleted_at",
        }
        unknown = set(values) - writable
        if unknown:
            raise ValidationError(f"Campos não editáveis: {', '.join(sorted(unknown))}")
        for key, value in values.items():
            setattr(record, key, value)
        self.session.flush()
        return record

    def soft_delete(
        self,
        model: type[ModelT],
        record_id: uuid.UUID | str,
        *,
        user_id: uuid.UUID | str | None = None,
    ) -> ModelT:
        if model is Transaction:
            if user_id is None:
                raise ValidationError("Informe o usuário para excluir uma transação.")
            target_id = _as_uuid(record_id)
            existing = self.get(
                Transaction, target_id, user_id=user_id, include_deleted=True
            )
            if existing is None:
                raise RecordNotFoundError("Transaction não encontrado.")
            if existing.deleted_at is not None:
                return cast(ModelT, existing)
            records = self.soft_delete_transaction(user_id, target_id)
            return cast(ModelT, next(item for item in records if item.id == target_id))
        if not issubclass(model, SoftDeleteMixin):
            raise ValidationError(f"{model.__name__} não suporta exclusão reversível.")
        record = self.require(model, record_id, user_id=user_id, for_update=True)
        record.deleted_at = datetime.now(timezone.utc)  # type: ignore[attr-defined]
        if hasattr(record, "is_active"):
            record.is_active = False  # type: ignore[attr-defined]
        self.session.flush()
        return record

    def restore(
        self,
        model: type[ModelT],
        record_id: uuid.UUID | str,
        *,
        user_id: uuid.UUID | str | None = None,
    ) -> ModelT:
        record = self.require(
            model,
            record_id,
            user_id=user_id,
            include_deleted=True,
            for_update=True,
        )
        if not hasattr(record, "deleted_at"):
            raise ValidationError(f"{model.__name__} não suporta restauração.")
        record.deleted_at = None  # type: ignore[attr-defined]
        self.session.flush()
        return record

    def list_records(
        self,
        model: type[ModelT],
        user_id: uuid.UUID | str,
        *,
        page: int = 1,
        page_size: int = 50,
        include_deleted: bool = False,
        active_only: bool = False,
    ) -> Page[ModelT]:
        if not hasattr(model, "user_id"):
            raise ValidationError(f"{model.__name__} não é um registro por usuário.")
        page, page_size = max(1, int(page)), min(100, max(1, int(page_size)))
        filters: list[Any] = [model.user_id == _as_uuid(user_id)]  # type: ignore[attr-defined]
        if not include_deleted and hasattr(model, "deleted_at"):
            filters.append(model.deleted_at.is_(None))  # type: ignore[attr-defined]
        if active_only and hasattr(model, "is_active"):
            filters.append(model.is_active.is_(True))  # type: ignore[attr-defined]
        total = int(
            self.session.scalar(select(func.count(model.id)).where(*filters)) or 0  # type: ignore[attr-defined]
        )
        order_column = model.created_at if hasattr(model, "created_at") else model.id  # type: ignore[attr-defined]
        items = list(
            self.session.scalars(
                select(model)
                .where(*filters)
                .order_by(order_column.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return Page(items, total, page, page_size)

    # Users/settings/accounts/categories ------------------------------------------
    def create_user(
        self, name: str, *, email: str | None = None, currency: str = "BRL"
    ) -> User:
        return self.create(User, name=name.strip(), email=email, currency=currency.upper())

    def first_active_user(self) -> User | None:
        return self.session.scalar(
            select(User)
            .where(User.deleted_at.is_(None), User.is_active.is_(True))
            .order_by(User.created_at)
            .limit(1)
        )

    def get_settings(self, user_id: uuid.UUID | str) -> AppSettings:
        uid = _as_uuid(user_id)
        settings = self.session.scalar(select(AppSettings).where(AppSettings.user_id == uid))
        return settings or self.create(AppSettings, user_id=uid)

    def update_settings(self, user_id: uuid.UUID | str, **values: Any) -> AppSettings:
        uid = _as_uuid(user_id)
        settings = self.get_settings(uid)
        allowed = {
            "currency",
            "financial_month_start_day",
            "default_account_id",
            "default_category_id",
            "privacy_mode",
            "theme",
            "extra",
        }
        if set(values) - allowed:
            raise ValidationError("Uma ou mais configurações não são editáveis.")
        if values.get("default_account_id") is not None:
            values["default_account_id"] = self._owned_reference(
                Account, values["default_account_id"], uid
            )
        if values.get("default_category_id") is not None:
            values["default_category_id"] = self._owned_reference(
                Category, values["default_category_id"], uid
            )
        for key, value in values.items():
            setattr(settings, key, value)
        self.session.flush()
        return settings

    def create_account(
        self,
        user_id: uuid.UUID | str,
        name: str,
        *,
        initial_balance: Decimal | int | str = ZERO,
        institution: str | None = None,
        account_type: str = "checking",
        icon: str | None = None,
        color: str | None = None,
    ) -> Account:
        if not name.strip():
            raise ValidationError("Informe o nome da conta.")
        return self.create(
            Account,
            user_id=_as_uuid(user_id),
            name=name.strip(),
            initial_balance=_money(initial_balance),
            institution=institution,
            account_type=account_type,
            icon=icon,
            color=color,
        )

    def list_accounts(
        self,
        user_id: uuid.UUID | str,
        *,
        active_only: bool = True,
        include_deleted: bool = False,
    ) -> list[Account]:
        query = select(Account).where(Account.user_id == _as_uuid(user_id))
        if not include_deleted:
            query = query.where(Account.deleted_at.is_(None))
        if active_only:
            query = query.where(Account.is_active.is_(True))
        return list(self.session.scalars(query.order_by(Account.created_at, Account.name)))

    def get_account_balances(
        self,
        user_id: uuid.UUID | str,
        *,
        as_of: date | None = None,
        active_only: bool = True,
    ) -> list[AccountBalance]:
        cutoff = as_of or date.today()  # noqa: DTZ011 - local financial date
        tx_filters: list[Any] = [
            Transaction.deleted_at.is_(None),
            Transaction.status == "paid",
            Transaction.source != "loan_disbursement",
            Transaction.transaction_date <= cutoff,
        ]
        effect = case(
            (
                and_(Transaction.transaction_type == "income", Transaction.account_id == Account.id),
                Transaction.amount,
            ),
            (
                and_(
                    Transaction.transaction_type == "expense",
                    Transaction.account_id == Account.id,
                    Transaction.credit_card_id.is_(None),
                ),
                -Transaction.amount,
            ),
            (
                and_(
                    Transaction.transaction_type == "transfer",
                    Transaction.account_id == Account.id,
                    Transaction.transfer_direction == "in",
                ),
                Transaction.amount,
            ),
            (
                and_(
                    Transaction.transaction_type == "transfer",
                    Transaction.account_id == Account.id,
                    or_(
                        Transaction.transfer_direction == "out",
                        Transaction.transfer_direction.is_(None),
                    ),
                ),
                -Transaction.amount,
            ),
            else_=ZERO,
        )
        source_total = (
            select(func.coalesce(func.sum(effect), ZERO))
            .where(*tx_filters)
            .correlate(Account)
            .scalar_subquery()
        )
        destination_filters: list[Any] = [
            Transaction.deleted_at.is_(None),
            Transaction.status == "paid",
            Transaction.transaction_type == "transfer",
            Transaction.transfer_direction.is_(None),
            Transaction.destination_account_id == Account.id,
            Transaction.transaction_date <= cutoff,
        ]
        destination_total = (
            select(func.coalesce(func.sum(Transaction.amount), ZERO))
            .where(*destination_filters)
            .correlate(Account)
            .scalar_subquery()
        )
        query = select(
            Account,
            (Account.initial_balance + source_total + destination_total).label("balance"),
        ).where(Account.user_id == _as_uuid(user_id), Account.deleted_at.is_(None))
        if active_only:
            query = query.where(Account.is_active.is_(True))
        return [
            AccountBalance(account=row[0], balance=_money(row.balance))
            for row in self.session.execute(query.order_by(Account.created_at))
        ]

    def total_available_balance(
        self, user_id: uuid.UUID | str, *, as_of: date | None = None
    ) -> Decimal:
        return sum(
            (item.balance for item in self.get_account_balances(user_id, as_of=as_of)),
            ZERO,
        )

    def create_category(
        self,
        user_id: uuid.UUID | str,
        name: str,
        *,
        kind: str = "expense",
        icon: str | None = None,
        color: str | None = None,
        parent_id: uuid.UUID | str | None = None,
    ) -> Category:
        uid = _as_uuid(user_id)
        return self.create(
            Category,
            user_id=uid,
            name=name.strip(),
            kind=kind,
            icon=icon,
            color=color,
            parent_id=self._owned_reference(Category, parent_id, uid),
        )

    def list_categories(
        self,
        user_id: uuid.UUID | str,
        *,
        kind: str | None = None,
        active_only: bool = True,
    ) -> list[Category]:
        query = select(Category).where(
            Category.user_id == _as_uuid(user_id), Category.deleted_at.is_(None)
        )
        if kind:
            query = query.where(or_(Category.kind == kind, Category.kind == "both"))
        if active_only:
            query = query.where(Category.is_active.is_(True))
        return list(self.session.scalars(query.order_by(Category.name)))

    # Transactions ----------------------------------------------------------------
    def create_transaction(
        self,
        user_id: uuid.UUID | str,
        description: str,
        amount: Decimal | int | str,
        transaction_type: str,
        transaction_date: date,
        *,
        competence_date: date | None = None,
        category_id: uuid.UUID | str | None = None,
        account_id: uuid.UUID | str | None = None,
        destination_account_id: uuid.UUID | str | None = None,
        credit_card_id: uuid.UUID | str | None = None,
        invoice_id: uuid.UUID | str | None = None,
        payment_method: str | None = None,
        notes: str | None = None,
        status: str = "paid",
        paid_at: datetime | None = None,
        is_recurring: bool = False,
        installment_number: int | None = None,
        installment_count: int | None = None,
        installment_group_id: uuid.UUID | str | None = None,
        is_refund: bool = False,
        refunded_transaction_id: uuid.UUID | str | None = None,
        source: str = "manual",
    ) -> Transaction:
        normalized = _money(amount)
        if normalized <= ZERO:
            raise ValidationError("O valor da transação deve ser maior que zero.")
        if transaction_type not in {"income", "expense"}:
            if transaction_type == "transfer":
                raise ValidationError("Use create_transfer para registrar uma transferência.")
            raise ValidationError("Tipo de transação inválido.")
        if not account_id and not credit_card_id:
            raise ValidationError("Selecione uma conta ou cartão.")
        if payment_method == "credit" and not credit_card_id:
            raise ValidationError("Compras no crédito exigem um cartão.")
        uid = _as_uuid(user_id)
        invoice_ref = self._owned_reference(CreditCardInvoice, invoice_id, uid)
        card_ref = self._owned_reference(CreditCard, credit_card_id, uid)
        if invoice_ref:
            invoice = self.require(CreditCardInvoice, invoice_ref, user_id=uid)
            if card_ref and card_ref != invoice.credit_card_id:
                raise ValidationError("A fatura não pertence ao cartão informado.")
            card_ref = invoice.credit_card_id
        return self.create(
            Transaction,
            user_id=uid,
            description=description.strip(),
            amount=normalized,
            transaction_type=transaction_type,
            transaction_date=transaction_date,
            competence_date=competence_date or transaction_date,
            category_id=self._owned_reference(Category, category_id, uid),
            account_id=self._owned_reference(Account, account_id, uid),
            destination_account_id=self._owned_reference(
                Account, destination_account_id, uid
            ),
            credit_card_id=card_ref,
            invoice_id=invoice_ref,
            payment_method=payment_method,
            notes=notes,
            status=status,
            paid_at=paid_at or (datetime.now(timezone.utc) if status == "paid" else None),
            is_recurring=is_recurring,
            installment_number=installment_number,
            installment_count=installment_count,
            installment_group_id=(
                _as_uuid(installment_group_id) if installment_group_id else None
            ),
            is_refund=is_refund,
            refunded_transaction_id=self._owned_reference(
                Transaction, refunded_transaction_id, uid
            ),
            source=source,
        )

    def create_transfer(
        self,
        user_id: uuid.UUID | str,
        source_account_id: uuid.UUID | str,
        destination_account_id: uuid.UUID | str,
        amount: Decimal | int | str,
        transaction_date: date,
        *,
        description: str = "Transferência",
        notes: str | None = None,
    ) -> tuple[Transaction, Transaction]:
        uid = _as_uuid(user_id)
        source_id, destination_id = _as_uuid(source_account_id), _as_uuid(destination_account_id)
        if source_id == destination_id:
            raise ValidationError("As contas de origem e destino devem ser diferentes.")
        normalized = _money(amount)
        if normalized <= ZERO:
            raise ValidationError("O valor da transferência deve ser maior que zero.")
        self.require(Account, source_id, user_id=uid, for_update=True)
        self.require(Account, destination_id, user_id=uid, for_update=True)
        group_id, now = uuid.uuid4(), datetime.now(timezone.utc)
        common = {
            "user_id": uid,
            "description": description.strip(),
            "amount": normalized,
            "transaction_type": "transfer",
            "transaction_date": transaction_date,
            "competence_date": transaction_date,
            "payment_method": "transfer",
            "notes": notes,
            "status": "paid",
            "paid_at": now,
            "transfer_group_id": group_id,
            "source": "transfer",
        }
        outgoing = Transaction(
            **common,
            account_id=source_id,
            destination_account_id=destination_id,
            transfer_direction="out",
        )
        incoming = Transaction(
            **common,
            account_id=destination_id,
            destination_account_id=source_id,
            transfer_direction="in",
        )
        self.session.add_all((outgoing, incoming))
        self.session.flush()
        return outgoing, incoming

    def list_transactions(
        self,
        user_id: uuid.UUID | str,
        *,
        page: int = 1,
        page_size: int = 25,
        start_date: date | None = None,
        end_date: date | None = None,
        account_id: uuid.UUID | str | None = None,
        category_id: uuid.UUID | str | None = None,
        credit_card_id: uuid.UUID | str | None = None,
        transaction_type: str | None = None,
        payment_method: str | None = None,
        status: str | None = None,
        min_amount: Decimal | int | str | None = None,
        max_amount: Decimal | int | str | None = None,
        search: str | None = None,
        include_deleted: bool = False,
        sort_descending: bool = True,
    ) -> Page[Transaction]:
        page, page_size = max(1, int(page)), min(100, max(1, int(page_size)))
        filters: list[Any] = [Transaction.user_id == _as_uuid(user_id)]
        if not include_deleted:
            filters.append(Transaction.deleted_at.is_(None))
        if start_date:
            filters.append(Transaction.transaction_date >= start_date)
        if end_date:
            filters.append(Transaction.transaction_date <= end_date)
        if account_id:
            aid = _as_uuid(account_id)
            filters.append(
                or_(
                    Transaction.account_id == aid,
                    and_(
                        Transaction.transfer_direction.is_(None),
                        Transaction.destination_account_id == aid,
                    ),
                )
            )
        if category_id:
            filters.append(Transaction.category_id == _as_uuid(category_id))
        if credit_card_id:
            filters.append(Transaction.credit_card_id == _as_uuid(credit_card_id))
        if transaction_type:
            filters.append(Transaction.transaction_type == transaction_type)
        if payment_method:
            filters.append(Transaction.payment_method == payment_method)
        if status:
            filters.append(Transaction.status == status)
        if min_amount is not None:
            filters.append(Transaction.amount >= _money(min_amount))
        if max_amount is not None:
            filters.append(Transaction.amount <= _money(max_amount))
        if search and search.strip():
            filters.append(Transaction.description.ilike(_search_pattern(search), escape="\\"))
        total = int(
            self.session.scalar(select(func.count(Transaction.id)).where(*filters)) or 0
        )
        order = (
            (Transaction.transaction_date.desc(), Transaction.created_at.desc())
            if sort_descending
            else (Transaction.transaction_date.asc(), Transaction.created_at.asc())
        )
        query = (
            select(Transaction)
            .options(
                joinedload(Transaction.account),
                joinedload(Transaction.category),
                joinedload(Transaction.credit_card),
                joinedload(Transaction.invoice),
            )
            .where(*filters)
            .order_by(*order)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return Page(
            list(self.session.scalars(query).unique()), total, page, page_size
        )

    def update_transaction(
        self,
        user_id: uuid.UUID | str,
        transaction_id: uuid.UUID | str,
        **values: Any,
    ) -> Transaction:
        uid = _as_uuid(user_id)
        transaction = self.require(
            Transaction, transaction_id, user_id=uid, for_update=True
        )
        allowed = {
            "description",
            "amount",
            "category_id",
            "account_id",
            "destination_account_id",
            "credit_card_id",
            "invoice_id",
            "transaction_date",
            "competence_date",
            "payment_method",
            "notes",
            "status",
            "paid_at",
            "is_refund",
            "refunded_transaction_id",
        }
        unknown = set(values) - allowed
        if unknown:
            raise ValidationError(f"Campos não editáveis: {', '.join(sorted(unknown))}")
        if "amount" in values:
            values["amount"] = _money(values["amount"])
            if values["amount"] <= ZERO:
                raise ValidationError("O valor da transação deve ser maior que zero.")
        ref_models: dict[str, type[Base]] = {
            "category_id": Category,
            "account_id": Account,
            "destination_account_id": Account,
            "credit_card_id": CreditCard,
            "invoice_id": CreditCardInvoice,
            "refunded_transaction_id": Transaction,
        }
        for field, model in ref_models.items():
            if field in values and values[field] is not None:
                values[field] = self._owned_reference(model, values[field], uid)
        old_invoice_id = transaction.invoice_id
        if transaction.transfer_group_id:
            if set(values) - {"description", "amount", "transaction_date", "notes"}:
                raise ValidationError(
                    "Contas e direção de uma transferência não podem ser alteradas."
                )
            movements = list(
                self.session.scalars(
                    select(Transaction)
                    .where(
                        Transaction.user_id == uid,
                        Transaction.transfer_group_id == transaction.transfer_group_id,
                        Transaction.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
            )
            for movement in movements:
                for key, value in values.items():
                    setattr(movement, key, value)
                if "transaction_date" in values:
                    movement.competence_date = values["transaction_date"]
        else:
            selected_account = values.get("account_id", transaction.account_id)
            selected_card = values.get("credit_card_id", transaction.credit_card_id)
            selected_invoice = values.get("invoice_id", transaction.invoice_id)
            if selected_invoice:
                invoice = self.require(CreditCardInvoice, selected_invoice, user_id=uid)
                if selected_card and selected_card != invoice.credit_card_id:
                    raise ValidationError("A fatura não pertence ao cartão informado.")
                values["credit_card_id"] = selected_card = invoice.credit_card_id
            if not selected_account and not selected_card:
                raise ValidationError("Selecione uma conta ou cartão.")
            if values.get("payment_method", transaction.payment_method) == "credit" and not selected_card:
                raise ValidationError("Compras no crédito exigem um cartão.")
            if values.get("status") == "paid" and "paid_at" not in values:
                values["paid_at"] = datetime.now(timezone.utc)
            if values.get("status") == "pending" and "paid_at" not in values:
                values["paid_at"] = None
            for key, value in values.items():
                setattr(transaction, key, value)
            installment = self.session.scalar(
                select(Installment)
                .where(
                    Installment.transaction_id == transaction.id,
                    Installment.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if installment:
                mapping = {
                    "description": "description",
                    "amount": "amount",
                    "transaction_date": "purchase_date",
                    "competence_date": "competence_date",
                    "credit_card_id": "credit_card_id",
                    "invoice_id": "invoice_id",
                }
                for source, target in mapping.items():
                    if source in values:
                        setattr(installment, target, values[source])
                if values.get("invoice_id"):
                    target_invoice = self.require(
                        CreditCardInvoice, values["invoice_id"], user_id=uid
                    )
                    installment.due_date = target_invoice.due_date
                if values.get("status") in {"cancelled", "refunded"}:
                    installment.status = "cancelled"
        self.session.flush()
        for invoice_id in {old_invoice_id, transaction.invoice_id} - {None}:
            self.recalculate_invoice_total(invoice_id, user_id=uid)
        return transaction

    def soft_delete_transaction(
        self, user_id: uuid.UUID | str, transaction_id: uuid.UUID | str
    ) -> list[Transaction]:
        uid, target_id = _as_uuid(user_id), _as_uuid(transaction_id)
        target = self.get(
            Transaction, target_id, user_id=uid, include_deleted=True, for_update=True
        )
        if target is None:
            raise RecordNotFoundError("Transaction não encontrado.")
        if target.deleted_at is not None:
            return [target]
        if target.transfer_group_id:
            records = list(
                self.session.scalars(
                    select(Transaction)
                    .where(
                        Transaction.user_id == uid,
                        Transaction.transfer_group_id == target.transfer_group_id,
                        Transaction.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
            )
        else:
            records = [target]
        now = datetime.now(timezone.utc)
        record_ids = {record.id for record in records}
        invoice_ids = {record.invoice_id for record in records if record.invoice_id}
        for record in records:
            record.deleted_at = now
        for installment in self.session.scalars(
            select(Installment).where(
                Installment.user_id == uid,
                Installment.transaction_id.in_(record_ids),
                Installment.deleted_at.is_(None),
            )
        ):
            installment.deleted_at, installment.status = now, "cancelled"
        self.session.flush()
        for invoice_id in invoice_ids:
            self.recalculate_invoice_total(invoice_id, user_id=uid)
        for bill in self.session.scalars(
            select(Bill).where(
                Bill.user_id == uid,
                Bill.transaction_id.in_(record_ids),
                Bill.deleted_at.is_(None),
            )
        ):
            bill.status, bill.paid_at, bill.transaction_id = "pending", None, None
        loan_installments = list(
            self.session.scalars(
                select(LoanInstallment)
                .where(
                    LoanInstallment.user_id == uid,
                    LoanInstallment.transaction_id.in_(record_ids),
                    LoanInstallment.deleted_at.is_(None),
                )
                .with_for_update()
            )
        )
        affected_loan_ids: set[uuid.UUID] = set()
        for installment in loan_installments:
            installment.status = (
                "overdue"
                if installment.due_date < datetime.now(timezone.utc).date()
                else "pending"
            )
            installment.paid_at, installment.transaction_id = None, None
            affected_loan_ids.add(installment.loan_id)
        if affected_loan_ids:
            for loan in self.session.scalars(
                select(Loan).where(Loan.id.in_(affected_loan_ids)).with_for_update()
            ):
                loan.status = "active"
        paid_invoices = list(
            self.session.scalars(
                select(CreditCardInvoice)
                .where(
                    CreditCardInvoice.user_id == uid,
                    CreditCardInvoice.payment_transaction_id.in_(record_ids),
                    CreditCardInvoice.deleted_at.is_(None),
                )
                .with_for_update()
            )
        )
        today = datetime.now(timezone.utc).date()
        for invoice in paid_invoices:
            invoice.payment_transaction_id, invoice.paid_at = None, None
            invoice.status = (
                "overdue"
                if today > invoice.due_date
                else "closed"
                if today > invoice.closing_date
                else "open"
            )
            reopened_installments = list(
                self.session.scalars(
                    select(Installment).where(
                        Installment.invoice_id == invoice.id,
                        Installment.deleted_at.is_(None),
                        Installment.status == "paid",
                    )
                )
            )
            reopened_transaction_ids = [
                item.transaction_id for item in reopened_installments if item.transaction_id
            ]
            for installment in reopened_installments:
                installment.status = "posted"
            if reopened_transaction_ids:
                for transaction in self.session.scalars(
                    select(Transaction).where(Transaction.id.in_(reopened_transaction_ids))
                ):
                    transaction.status, transaction.paid_at = "pending", None
        self.session.flush()
        return records

    delete_transaction = soft_delete_transaction

    # Aggregates ------------------------------------------------------------------
    def monthly_summary(
        self, user_id: uuid.UUID | str, month: date
    ) -> MonthlySummary:
        start, end = _month_start(month), _next_month(_month_start(month))
        filters = and_(
            Transaction.user_id == _as_uuid(user_id),
            Transaction.deleted_at.is_(None),
            Transaction.competence_date >= start,
            Transaction.competence_date < end,
            Transaction.status.in_(("paid", "pending")),
            Transaction.transaction_type.in_(("income", "expense")),
            Transaction.source.not_in(("invoice_payment", "loan_disbursement")),
        )
        row = self.session.execute(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (Transaction.transaction_type == "income", Transaction.amount),
                            else_=ZERO,
                        )
                    ),
                    ZERO,
                ).label("income"),
                func.coalesce(
                    func.sum(
                        case(
                            (Transaction.transaction_type == "expense", Transaction.amount),
                            else_=ZERO,
                        )
                    ),
                    ZERO,
                ).label("expenses"),
                func.count(Transaction.id).label("transaction_count"),
            ).where(filters)
        ).one()
        income, expenses = _money(row.income), _money(row.expenses)
        return MonthlySummary(income, expenses, income - expenses, int(row.transaction_count))

    def monthly_cashflow(
        self,
        user_id: uuid.UUID | str,
        *,
        start_month: date,
        end_month: date,
    ) -> list[dict[str, Any]]:
        start, last = _month_start(start_month), _month_start(end_month)
        if start > last:
            raise ValidationError("O mês inicial não pode ser posterior ao mês final.")
        year_expr = func.extract("year", Transaction.competence_date)
        month_expr = func.extract("month", Transaction.competence_date)
        query = (
            select(
                year_expr.label("year"),
                month_expr.label("month"),
                func.coalesce(
                    func.sum(
                        case(
                            (Transaction.transaction_type == "income", Transaction.amount),
                            else_=ZERO,
                        )
                    ),
                    ZERO,
                ).label("income"),
                func.coalesce(
                    func.sum(
                        case(
                            (Transaction.transaction_type == "expense", Transaction.amount),
                            else_=ZERO,
                        )
                    ),
                    ZERO,
                ).label("expenses"),
            )
            .where(
                Transaction.user_id == _as_uuid(user_id),
                Transaction.deleted_at.is_(None),
                Transaction.competence_date >= start,
                Transaction.competence_date < _next_month(last),
                Transaction.status.in_(("paid", "pending")),
                Transaction.transaction_type.in_(("income", "expense")),
                Transaction.source.not_in(("invoice_payment", "loan_disbursement")),
            )
            .group_by(year_expr, month_expr)
            .order_by(year_expr, month_expr)
        )
        grouped = {
            date(int(row.year), int(row.month), 1): (_money(row.income), _money(row.expenses))
            for row in self.session.execute(query)
        }
        result: list[dict[str, Any]] = []
        current = start
        while current <= last:
            income, expenses = grouped.get(current, (ZERO, ZERO))
            result.append(
                {
                    "month": current,
                    "income": income,
                    "expenses": expenses,
                    "balance": income - expenses,
                }
            )
            current = _next_month(current)
        return result

    def expenses_by_category(
        self,
        user_id: uuid.UUID | str,
        *,
        start_date: date,
        end_date: date,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        query = (
            select(
                Category.id,
                func.coalesce(Category.name, "Sem categoria").label("name"),
                Category.color,
                func.sum(Transaction.amount).label("amount"),
            )
            .select_from(Transaction)
            .outerjoin(Category, Category.id == Transaction.category_id)
            .where(
                Transaction.user_id == _as_uuid(user_id),
                Transaction.deleted_at.is_(None),
                Transaction.transaction_type == "expense",
                Transaction.status.in_(("paid", "pending")),
                Transaction.source.not_in(("invoice_payment", "loan_disbursement")),
                Transaction.competence_date >= start_date,
                Transaction.competence_date <= end_date,
            )
            .group_by(Category.id, Category.name, Category.color)
            .order_by(func.sum(Transaction.amount).desc())
            .limit(max(1, min(limit, 100)))
        )
        return [
            {
                "category_id": row.id,
                "name": row.name,
                "color": row.color,
                "amount": _money(row.amount),
            }
            for row in self.session.execute(query)
        ]

    def largest_expenses(
        self,
        user_id: uuid.UUID | str,
        *,
        start_date: date,
        end_date: date,
        limit: int = 5,
    ) -> list[Transaction]:
        query = (
            select(Transaction)
            .options(joinedload(Transaction.category), joinedload(Transaction.account))
            .where(
                Transaction.user_id == _as_uuid(user_id),
                Transaction.deleted_at.is_(None),
                Transaction.transaction_type == "expense",
                Transaction.status.in_(("paid", "pending")),
                Transaction.source.not_in(("invoice_payment", "loan_disbursement")),
                Transaction.competence_date >= start_date,
                Transaction.competence_date <= end_date,
            )
            .order_by(Transaction.amount.desc())
            .limit(max(1, min(limit, 50)))
        )
        return list(self.session.scalars(query).unique())

    # Credit cards/invoices --------------------------------------------------------
    def create_credit_card(
        self,
        user_id: uuid.UUID | str,
        name: str,
        credit_limit: Decimal | int | str,
        closing_day: int,
        due_day: int,
        *,
        bank: str | None = None,
        payment_account_id: uuid.UUID | str | None = None,
        color: str | None = None,
        last_four_digits: str | None = None,
    ) -> CreditCard:
        if not 1 <= closing_day <= 31 or not 1 <= due_day <= 31:
            raise ValidationError(
                "Dias de fechamento e vencimento devem estar entre 1 e 31."
            )
        uid, limit = _as_uuid(user_id), _money(credit_limit)
        if limit < ZERO:
            raise ValidationError("O limite do cartão não pode ser negativo.")
        return self.create(
            CreditCard,
            user_id=uid,
            name=name.strip(),
            bank=bank,
            credit_limit=limit,
            closing_day=closing_day,
            due_day=due_day,
            payment_account_id=self._owned_reference(
                Account, payment_account_id, uid
            ),
            color=color,
            last_four_digits=last_four_digits,
        )

    def list_credit_cards(
        self, user_id: uuid.UUID | str, *, active_only: bool = True
    ) -> list[CreditCard]:
        query = (
            select(CreditCard)
            .options(joinedload(CreditCard.payment_account))
            .where(
                CreditCard.user_id == _as_uuid(user_id),
                CreditCard.deleted_at.is_(None),
            )
        )
        if active_only:
            query = query.where(CreditCard.is_active.is_(True))
        return list(self.session.scalars(query.order_by(CreditCard.created_at)).unique())

    def get_or_create_invoice(
        self,
        user_id: uuid.UUID | str,
        credit_card_id: uuid.UUID | str,
        reference_month: date,
        *,
        closing_date: date,
        due_date: date,
    ) -> CreditCardInvoice:
        uid, card_id = _as_uuid(user_id), _as_uuid(credit_card_id)
        reference = _month_start(reference_month)
        invoice = self.session.scalar(
            select(CreditCardInvoice)
            .where(
                CreditCardInvoice.user_id == uid,
                CreditCardInvoice.credit_card_id == card_id,
                CreditCardInvoice.reference_month == reference,
            )
            .with_for_update()
        )
        if invoice:
            if invoice.deleted_at is not None:
                invoice.deleted_at = None
                invoice.closing_date, invoice.due_date = closing_date, due_date
                invoice.status, invoice.total_amount = "open", ZERO
                invoice.paid_at, invoice.payment_transaction_id = None, None
                self.session.flush()
            return invoice
        self.require(CreditCard, card_id, user_id=uid)
        return self.create(
            CreditCardInvoice,
            user_id=uid,
            credit_card_id=card_id,
            reference_month=reference,
            closing_date=closing_date,
            due_date=due_date,
            total_amount=ZERO,
            status="open",
        )

    def list_invoices(
        self,
        user_id: uuid.UUID | str,
        *,
        credit_card_id: uuid.UUID | str | None = None,
        statuses: Sequence[str] | None = None,
        start_due_date: date | None = None,
        end_due_date: date | None = None,
        limit: int = 24,
    ) -> list[CreditCardInvoice]:
        query = (
            select(CreditCardInvoice)
            .options(joinedload(CreditCardInvoice.credit_card))
            .where(
                CreditCardInvoice.user_id == _as_uuid(user_id),
                CreditCardInvoice.deleted_at.is_(None),
            )
        )
        if credit_card_id:
            query = query.where(
                CreditCardInvoice.credit_card_id == _as_uuid(credit_card_id)
            )
        if statuses:
            query = query.where(CreditCardInvoice.status.in_(tuple(statuses)))
        if start_due_date:
            query = query.where(CreditCardInvoice.due_date >= start_due_date)
        if end_due_date:
            query = query.where(CreditCardInvoice.due_date <= end_due_date)
        return list(
            self.session.scalars(
                query.order_by(CreditCardInvoice.due_date.desc()).limit(
                    max(1, min(limit, 120))
                )
            ).unique()
        )

    def recalculate_invoice_total(
        self, invoice_id: uuid.UUID | str, *, user_id: uuid.UUID | str
    ) -> Decimal:
        invoice = self.require(
            CreditCardInvoice, invoice_id, user_id=user_id, for_update=True
        )
        total = self.session.scalar(
            select(func.coalesce(func.sum(Transaction.amount), ZERO)).where(
                Transaction.invoice_id == invoice.id,
                Transaction.deleted_at.is_(None),
                Transaction.status.not_in(("cancelled", "refunded")),
            )
        )
        invoice.total_amount = _money(total or ZERO)
        self.session.flush()
        return invoice.total_amount

    def list_card_summaries(
        self, user_id: uuid.UUID | str
    ) -> list[CardSummary]:
        result: list[CardSummary] = []
        for card in self.list_credit_cards(user_id):
            open_amount = _money(
                self.session.scalar(
                    select(
                        func.coalesce(func.sum(CreditCardInvoice.total_amount), ZERO)
                    ).where(
                        CreditCardInvoice.credit_card_id == card.id,
                        CreditCardInvoice.deleted_at.is_(None),
                        CreditCardInvoice.status.in_(("open", "closed", "overdue")),
                    )
                )
                or ZERO
            )
            available = max(ZERO, card.credit_limit - open_amount)
            utilization = (
                (open_amount / card.credit_limit * Decimal(100)).quantize(
                    Decimal("0.1"), rounding=ROUND_HALF_UP
                )
                if card.credit_limit > ZERO
                else ZERO
            )
            result.append(CardSummary(card, open_amount, available, utilization))
        return result

    def pay_invoice(
        self,
        user_id: uuid.UUID | str,
        invoice_id: uuid.UUID | str,
        *,
        account_id: uuid.UUID | str | None = None,
        payment_date: date | None = None,
    ) -> Transaction:
        uid = _as_uuid(user_id)
        invoice = self.require(
            CreditCardInvoice, invoice_id, user_id=uid, for_update=True
        )
        if invoice.status == "paid":
            raise ValidationError("Esta fatura já foi paga.")
        card = self.require(CreditCard, invoice.credit_card_id, user_id=uid)
        selected_account = _as_uuid(account_id) if account_id else card.payment_account_id
        if selected_account is None:
            raise ValidationError("Selecione a conta usada para pagar a fatura.")
        self.require(Account, selected_account, user_id=uid, for_update=True)
        amount = self.recalculate_invoice_total(invoice.id, user_id=uid)
        if amount <= ZERO:
            raise ValidationError("A fatura não possui saldo para pagamento.")
        paid_on = payment_date or datetime.now(timezone.utc).date()
        payment = self.create_transaction(
            uid,
            f"Pagamento da fatura {card.name}",
            amount,
            "expense",
            paid_on,
            competence_date=paid_on,
            account_id=selected_account,
            payment_method="boleto",
            source="invoice_payment",
        )
        invoice.status = "paid"
        invoice.paid_at = datetime.now(timezone.utc)
        invoice.payment_transaction_id = payment.id
        invoice_installments = list(
            self.session.scalars(
                select(Installment).where(
                    Installment.invoice_id == invoice.id,
                    Installment.deleted_at.is_(None),
                    Installment.status.not_in(("cancelled", "paid")),
                )
            )
        )
        transaction_ids = [item.transaction_id for item in invoice_installments if item.transaction_id]
        for item in invoice_installments:
            item.status = "paid"
        if transaction_ids:
            transactions = list(
                self.session.scalars(
                    select(Transaction).where(Transaction.id.in_(transaction_ids))
                )
            )
            for transaction in transactions:
                transaction.status = "paid"
                transaction.paid_at = invoice.paid_at
        self.session.flush()
        return payment

    def list_installment_plans(
        self,
        user_id: uuid.UUID | str,
        *,
        credit_card_id: uuid.UUID | str | None = None,
        active_only: bool = True,
    ) -> list[InstallmentPlanSummary]:
        """Group card installments and expose how many monthly payments remain."""

        query = (
            select(Installment)
            .options(joinedload(Installment.invoice))
            .where(
                Installment.user_id == _as_uuid(user_id),
                Installment.deleted_at.is_(None),
                Installment.status != "cancelled",
            )
        )
        if credit_card_id is not None:
            query = query.where(Installment.credit_card_id == _as_uuid(credit_card_id))
        rows = list(
            self.session.scalars(
                query.order_by(
                    Installment.installment_group_id,
                    Installment.installment_number,
                )
            )
        )
        grouped: dict[uuid.UUID, list[Installment]] = {}
        for item in rows:
            grouped.setdefault(item.installment_group_id, []).append(item)
        result: list[InstallmentPlanSummary] = []
        for group_id, items in grouped.items():
            def is_paid(item: Installment) -> bool:
                return item.status == "paid" or getattr(item.invoice, "status", None) == "paid"

            remaining = [item for item in items if not is_paid(item)]
            if active_only and not remaining:
                continue
            result.append(
                InstallmentPlanSummary(
                    group_id=group_id,
                    description=items[0].description,
                    credit_card_id=items[0].credit_card_id,
                    total_installments=max(item.installment_count for item in items),
                    paid_installments=sum(is_paid(item) for item in items),
                    remaining_installments=len(remaining),
                    remaining_amount=_money(sum((item.amount for item in remaining), ZERO)),
                    next_due_date=min((item.due_date for item in remaining), default=None),
                    end_date=max(item.due_date for item in items),
                )
            )
        return sorted(
            result,
            key=lambda item: (item.next_due_date or date.max, item.description.casefold()),
        )

    # Loans ----------------------------------------------------------------------
    def create_loan(
        self,
        user_id: uuid.UUID | str,
        name: str,
        principal_amount: Decimal | int | str,
        total_amount: Decimal | int | str,
        total_installments: int,
        first_due_date: date,
        *,
        lender: str | None = None,
        paid_installments: int = 0,
        account_id: uuid.UUID | str | None = None,
        category_id: uuid.UUID | str | None = None,
        interest_rate: Decimal | int | str | None = None,
        record_disbursement: bool = False,
        disbursement_date: date | None = None,
        notes: str | None = None,
    ) -> Loan:
        from services.loan_service import generate_loan_schedule

        uid = _as_uuid(user_id)
        principal, payable = _money(principal_amount), _money(total_amount)
        installment_total, paid_count = int(total_installments), int(paid_installments)
        if not name.strip():
            raise ValidationError("Informe um nome para o empréstimo.")
        if principal <= ZERO or payable <= ZERO:
            raise ValidationError("Os valores do empréstimo devem ser maiores que zero.")
        if payable < principal:
            raise ValidationError("O total a pagar não pode ser menor que o valor recebido.")
        try:
            schedule = generate_loan_schedule(
                payable,
                installment_total,
                first_due_date,
                paid_installments=paid_count,
            )
        except (TypeError, ValueError) as exc:
            raise ValidationError(str(exc)) from exc
        account_ref = self._owned_reference(Account, account_id, uid)
        category_ref = self._owned_reference(Category, category_id, uid)
        if record_disbursement and account_ref is None:
            raise ValidationError("Selecione a conta que recebeu o empréstimo.")
        normalized_rate = None
        if interest_rate is not None:
            try:
                normalized_rate = Decimal(str(interest_rate)).quantize(Decimal("0.0001"))
            except Exception as exc:
                raise ValidationError("Taxa de juros inválida.") from exc
            if normalized_rate < ZERO:
                raise ValidationError("A taxa de juros não pode ser negativa.")
        disbursement = None
        if record_disbursement:
            received_on = disbursement_date or datetime.now(timezone.utc).date()
            disbursement = self.create_transaction(
                uid,
                f"Empréstimo recebido · {name.strip()}",
                principal,
                "income",
                received_on,
                competence_date=received_on,
                account_id=account_ref,
                payment_method="transfer",
                notes=notes,
                source="loan_disbursement",
            )
        loan = self.create(
            Loan,
            user_id=uid,
            name=name.strip(),
            lender=lender.strip() if lender and lender.strip() else None,
            principal_amount=principal,
            total_amount=payable,
            total_installments=installment_total,
            first_due_date=first_due_date,
            interest_rate=normalized_rate,
            account_id=account_ref,
            category_id=category_ref,
            disbursement_transaction_id=getattr(disbursement, "id", None),
            status="paid" if paid_count == installment_total else "active",
            notes=notes,
        )
        now = datetime.now(timezone.utc)
        for item in schedule:
            self.create(
                LoanInstallment,
                user_id=uid,
                loan_id=loan.id,
                installment_number=item.number,
                amount=item.amount,
                due_date=item.due_date,
                status="paid" if item.initially_paid else "pending",
                paid_at=now if item.initially_paid else None,
            )
        self.session.flush()
        return loan

    def list_loans(
        self,
        user_id: uuid.UUID | str,
        *,
        statuses: Sequence[str] | None = None,
    ) -> list[Loan]:
        query = select(Loan).where(
            Loan.user_id == _as_uuid(user_id), Loan.deleted_at.is_(None)
        )
        if statuses:
            query = query.where(Loan.status.in_(tuple(statuses)))
        return list(self.session.scalars(query.order_by(Loan.created_at.desc())))

    def list_loan_installments(
        self,
        user_id: uuid.UUID | str,
        *,
        loan_id: uuid.UUID | str | None = None,
        statuses: Sequence[str] | None = None,
    ) -> list[LoanInstallment]:
        query = select(LoanInstallment).join(Loan).where(
            LoanInstallment.user_id == _as_uuid(user_id),
            LoanInstallment.deleted_at.is_(None),
            Loan.deleted_at.is_(None),
        )
        if loan_id is not None:
            query = query.where(LoanInstallment.loan_id == _as_uuid(loan_id))
        if statuses:
            query = query.where(LoanInstallment.status.in_(tuple(statuses)))
        return list(
            self.session.scalars(
                query.order_by(LoanInstallment.due_date, LoanInstallment.installment_number)
            )
        )

    def list_loan_summaries(
        self, user_id: uuid.UUID | str, *, active_only: bool = False
    ) -> list[LoanSummary]:
        statuses = ("active",) if active_only else None
        result: list[LoanSummary] = []
        for loan in self.list_loans(user_id, statuses=statuses):
            installments = self.list_loan_installments(user_id, loan_id=loan.id)
            open_items = [
                item for item in installments if item.status not in ("paid", "cancelled")
            ]
            result.append(
                LoanSummary(
                    loan=loan,
                    paid_installments=sum(item.status == "paid" for item in installments),
                    remaining_installments=len(open_items),
                    outstanding_amount=_money(sum((item.amount for item in open_items), ZERO)),
                    next_installment=min(open_items, key=lambda item: item.due_date)
                    if open_items
                    else None,
                    end_date=max((item.due_date for item in installments), default=loan.first_due_date),
                )
            )
        return result

    def pay_loan_installment(
        self,
        user_id: uuid.UUID | str,
        installment_id: uuid.UUID | str,
        *,
        account_id: uuid.UUID | str | None = None,
        payment_date: date | None = None,
        payment_method: str = "boleto",
    ) -> Transaction:
        uid = _as_uuid(user_id)
        installment = self.require(
            LoanInstallment, installment_id, user_id=uid, for_update=True
        )
        if installment.status == "paid":
            raise ValidationError("Esta parcela já foi paga.")
        if installment.status == "cancelled":
            raise ValidationError("Esta parcela foi cancelada.")
        loan = self.require(Loan, installment.loan_id, user_id=uid, for_update=True)
        selected_account = _as_uuid(account_id) if account_id else loan.account_id
        if selected_account is None:
            raise ValidationError("Selecione a conta usada no pagamento.")
        paid_on = payment_date or datetime.now(timezone.utc).date()
        transaction = self.create_transaction(
            uid,
            f"Parcela {installment.installment_number}/{loan.total_installments} · {loan.name}",
            installment.amount,
            "expense",
            paid_on,
            competence_date=installment.due_date,
            category_id=loan.category_id,
            account_id=selected_account,
            payment_method=payment_method,
            source="loan_payment",
        )
        installment.status = "paid"
        installment.paid_at = datetime.now(timezone.utc)
        installment.transaction_id = transaction.id
        remaining = self.session.scalar(
            select(func.count(LoanInstallment.id)).where(
                LoanInstallment.loan_id == loan.id,
                LoanInstallment.id != installment.id,
                LoanInstallment.deleted_at.is_(None),
                LoanInstallment.status.not_in(("paid", "cancelled")),
            )
        )
        if not remaining:
            loan.status = "paid"
        self.session.flush()
        return transaction

    # Bills and recurring ----------------------------------------------------------
    def create_bill(
        self,
        user_id: uuid.UUID | str,
        description: str,
        amount: Decimal | int | str,
        due_date: date,
        *,
        category_id: uuid.UUID | str | None = None,
        account_id: uuid.UUID | str | None = None,
        recurring_transaction_id: uuid.UUID | str | None = None,
        recurrence_key: str | None = None,
        notes: str | None = None,
    ) -> Bill:
        uid, normalized = _as_uuid(user_id), _money(amount)
        if normalized <= ZERO:
            raise ValidationError("O valor da conta deve ser maior que zero.")
        if recurrence_key:
            existing = self.session.scalar(
                select(Bill)
                .where(Bill.recurrence_key == recurrence_key)
                .with_for_update()
            )
            if existing:
                if existing.user_id != uid:
                    raise ValidationError("Chave de recorrência já utilizada.")
                return existing
        return self.create(
            Bill,
            user_id=uid,
            description=description.strip(),
            amount=normalized,
            due_date=due_date,
            category_id=self._owned_reference(Category, category_id, uid),
            account_id=self._owned_reference(Account, account_id, uid),
            recurring_transaction_id=self._owned_reference(
                RecurringTransaction, recurring_transaction_id, uid
            ),
            recurrence_key=recurrence_key,
            notes=notes,
            status="pending",
        )

    def list_bills(
        self,
        user_id: uuid.UUID | str,
        *,
        statuses: Sequence[str] | None = None,
        start_due_date: date | None = None,
        end_due_date: date | None = None,
        limit: int = 50,
    ) -> list[Bill]:
        query = select(Bill).where(
            Bill.user_id == _as_uuid(user_id), Bill.deleted_at.is_(None)
        )
        if statuses:
            query = query.where(Bill.status.in_(tuple(statuses)))
        if start_due_date:
            query = query.where(Bill.due_date >= start_due_date)
        if end_due_date:
            query = query.where(Bill.due_date <= end_due_date)
        return list(
            self.session.scalars(
                query.order_by(Bill.due_date).limit(max(1, min(limit, 200)))
            )
        )

    def mark_bill_paid(
        self,
        user_id: uuid.UUID | str,
        bill_id: uuid.UUID | str,
        *,
        account_id: uuid.UUID | str | None = None,
        payment_date: date | None = None,
        payment_method: str = "boleto",
    ) -> Transaction:
        uid = _as_uuid(user_id)
        bill = self.require(Bill, bill_id, user_id=uid, for_update=True)
        if bill.status == "paid":
            raise ValidationError("Esta conta já foi paga.")
        selected_account = _as_uuid(account_id) if account_id else bill.account_id
        if selected_account is None:
            raise ValidationError("Selecione a conta usada no pagamento.")
        paid_on = payment_date or datetime.now(timezone.utc).date()
        transaction = self.create_transaction(
            uid,
            bill.description,
            bill.amount,
            "expense",
            paid_on,
            competence_date=bill.due_date,
            category_id=bill.category_id,
            account_id=selected_account,
            payment_method=payment_method,
            source="bill",
        )
        bill.status, bill.paid_at, bill.transaction_id = (
            "paid",
            datetime.now(timezone.utc),
            transaction.id,
        )
        self.session.flush()
        return transaction

    def list_due_recurring(
        self, user_id: uuid.UUID | str, *, through_date: date
    ) -> list[RecurringTransaction]:
        return list(
            self.session.scalars(
                select(RecurringTransaction)
                .where(
                    RecurringTransaction.user_id == _as_uuid(user_id),
                    RecurringTransaction.deleted_at.is_(None),
                    RecurringTransaction.is_active.is_(True),
                    RecurringTransaction.next_run_date <= through_date,
                    or_(
                        RecurringTransaction.end_date.is_(None),
                        RecurringTransaction.end_date
                        >= RecurringTransaction.next_run_date,
                    ),
                )
                .order_by(RecurringTransaction.next_run_date)
            )
        )

    def create_recurring_transaction(
        self,
        user_id: uuid.UUID | str,
        description: str,
        amount: Decimal | int | str,
        transaction_type: str,
        frequency: str,
        start_date: date,
        *,
        next_run_date: date | None = None,
        end_date: date | None = None,
        category_id: uuid.UUID | str | None = None,
        account_id: uuid.UUID | str | None = None,
        credit_card_id: uuid.UUID | str | None = None,
        payment_method: str | None = None,
        auto_post: bool = False,
    ) -> RecurringTransaction:
        normalized = _money(amount)
        if normalized <= ZERO:
            raise ValidationError("O valor recorrente deve ser maior que zero.")
        if transaction_type not in {"income", "expense"}:
            raise ValidationError("Recorrências devem ser receita ou despesa.")
        if frequency not in {"weekly", "monthly", "yearly"}:
            raise ValidationError("Frequência recorrente inválida.")
        if end_date and end_date < start_date:
            raise ValidationError("O fim da recorrência não pode preceder o início.")
        uid = _as_uuid(user_id)
        return self.create(
            RecurringTransaction,
            user_id=uid,
            description=description.strip(),
            amount=normalized,
            transaction_type=transaction_type,
            frequency=frequency,
            start_date=start_date,
            end_date=end_date,
            next_run_date=next_run_date or start_date,
            category_id=self._owned_reference(Category, category_id, uid),
            account_id=self._owned_reference(Account, account_id, uid),
            credit_card_id=self._owned_reference(CreditCard, credit_card_id, uid),
            payment_method=payment_method,
            auto_post=auto_post,
        )

    # Budgets/goals/subscriptions/patrimônio --------------------------------------
    def upsert_budget(
        self,
        user_id: uuid.UUID | str,
        category_id: uuid.UUID | str,
        month: date,
        amount: Decimal | int | str,
    ) -> Budget:
        uid = _as_uuid(user_id)
        category = self._owned_reference(Category, category_id, uid)
        if category is None:
            raise ValidationError("Selecione uma categoria para o orçamento.")
        normalized = _money(amount)
        if normalized < ZERO:
            raise ValidationError("O orçamento não pode ser negativo.")
        month_value = _month_start(month)
        budget = self.session.scalar(
            select(Budget)
            .where(
                Budget.user_id == uid,
                Budget.category_id == category,
                Budget.month == month_value,
            )
            .with_for_update()
        )
        if budget:
            budget.deleted_at, budget.amount = None, normalized
            self.session.flush()
            return budget
        return self.create(
            Budget,
            user_id=uid,
            category_id=category,
            month=month_value,
            amount=normalized,
        )

    def budget_progress(
        self, user_id: uuid.UUID | str, month: date
    ) -> list[dict[str, Any]]:
        start, end, uid = _month_start(month), _next_month(_month_start(month)), _as_uuid(user_id)
        spent = (
            select(
                Transaction.category_id.label("category_id"),
                func.sum(Transaction.amount).label("spent"),
            )
            .where(
                Transaction.user_id == uid,
                Transaction.deleted_at.is_(None),
                Transaction.transaction_type == "expense",
                Transaction.status.in_(("paid", "pending")),
                Transaction.source != "invoice_payment",
                Transaction.competence_date >= start,
                Transaction.competence_date < end,
            )
            .group_by(Transaction.category_id)
            .subquery()
        )
        query = (
            select(Budget, Category, func.coalesce(spent.c.spent, ZERO).label("spent"))
            .join(Category, Category.id == Budget.category_id)
            .outerjoin(spent, spent.c.category_id == Budget.category_id)
            .where(
                Budget.user_id == uid,
                Budget.month == start,
                Budget.deleted_at.is_(None),
            )
            .order_by(Category.name)
        )
        result: list[dict[str, Any]] = []
        for budget, category, spent_value in self.session.execute(query):
            amount = _money(spent_value)
            percentage = (
                (amount / budget.amount * Decimal(100)).quantize(Decimal("0.1"))
                if budget.amount > ZERO
                else ZERO
            )
            result.append(
                {
                    "budget": budget,
                    "category": category,
                    "spent": amount,
                    "remaining": budget.amount - amount,
                    "percentage": percentage,
                }
            )
        return result

    def create_financial_goal(
        self,
        user_id: uuid.UUID | str,
        name: str,
        target_amount: Decimal | int | str,
        *,
        initial_amount: Decimal | int | str = ZERO,
        target_date: date | None = None,
        icon: str | None = None,
        color: str | None = None,
    ) -> FinancialGoal:
        target, saved = _money(target_amount), _money(initial_amount)
        if target <= ZERO or saved < ZERO:
            raise ValidationError("Os valores da meta são inválidos.")
        return self.create(
            FinancialGoal,
            user_id=_as_uuid(user_id),
            name=name.strip(),
            target_amount=target,
            initial_amount=saved,
            target_date=target_date,
            icon=icon,
            color=color,
            status="completed" if saved >= target else "active",
        )

    def add_goal_contribution(
        self,
        user_id: uuid.UUID | str,
        goal_id: uuid.UUID | str,
        amount: Decimal | int | str,
        contribution_date: date,
        *,
        account_id: uuid.UUID | str | None = None,
        notes: str | None = None,
    ) -> GoalContribution:
        uid = _as_uuid(user_id)
        goal = self.require(FinancialGoal, goal_id, user_id=uid, for_update=True)
        normalized = _money(amount)
        if normalized <= ZERO:
            raise ValidationError("O aporte deve ser maior que zero.")
        contribution = self.create(
            GoalContribution,
            user_id=uid,
            goal_id=goal.id,
            amount=normalized,
            contribution_date=contribution_date,
            account_id=self._owned_reference(Account, account_id, uid),
            notes=notes,
        )
        total = goal.initial_amount + cast(
            Decimal,
            self.session.scalar(
                select(func.coalesce(func.sum(GoalContribution.amount), ZERO)).where(
                    GoalContribution.goal_id == goal.id,
                    GoalContribution.deleted_at.is_(None),
                )
            ),
        )
        if total >= goal.target_amount:
            goal.status = "completed"
        self.session.flush()
        return contribution

    def goal_progress(
        self, user_id: uuid.UUID | str, *, active_only: bool = False
    ) -> list[dict[str, Any]]:
        contributions = (
            select(
                GoalContribution.goal_id,
                func.sum(GoalContribution.amount).label("contributions"),
            )
            .where(GoalContribution.deleted_at.is_(None))
            .group_by(GoalContribution.goal_id)
            .subquery()
        )
        query = (
            select(
                FinancialGoal,
                func.coalesce(contributions.c.contributions, ZERO).label("contributions"),
            )
            .outerjoin(contributions, contributions.c.goal_id == FinancialGoal.id)
            .where(
                FinancialGoal.user_id == _as_uuid(user_id),
                FinancialGoal.deleted_at.is_(None),
            )
        )
        if active_only:
            query = query.where(FinancialGoal.status == "active")
        result: list[dict[str, Any]] = []
        for goal, contribution_total in self.session.execute(
            query.order_by(FinancialGoal.created_at)
        ):
            saved = goal.initial_amount + _money(contribution_total)
            percentage = (
                min(
                    Decimal(100),
                    (saved / goal.target_amount * Decimal(100)).quantize(Decimal("0.1")),
                )
                if goal.target_amount > ZERO
                else ZERO
            )
            result.append({"goal": goal, "saved": saved, "percentage": percentage})
        return result

    def create_subscription(
        self,
        user_id: uuid.UUID | str,
        name: str,
        amount: Decimal | int | str,
        next_charge_date: date,
        *,
        frequency: str = "monthly",
        category_id: uuid.UUID | str | None = None,
        account_id: uuid.UUID | str | None = None,
        credit_card_id: uuid.UUID | str | None = None,
        recurring_transaction_id: uuid.UUID | str | None = None,
    ) -> Subscription:
        normalized = _money(amount)
        if normalized <= ZERO:
            raise ValidationError("O valor da assinatura deve ser maior que zero.")
        if frequency not in {"weekly", "monthly", "yearly"}:
            raise ValidationError("Frequência da assinatura inválida.")
        uid = _as_uuid(user_id)
        return self.create(
            Subscription,
            user_id=uid,
            name=name.strip(),
            amount=normalized,
            frequency=frequency,
            next_charge_date=next_charge_date,
            category_id=self._owned_reference(Category, category_id, uid),
            account_id=self._owned_reference(Account, account_id, uid),
            credit_card_id=self._owned_reference(CreditCard, credit_card_id, uid),
            recurring_transaction_id=self._owned_reference(
                RecurringTransaction, recurring_transaction_id, uid
            ),
        )

    def subscription_totals(self, user_id: uuid.UUID | str) -> dict[str, Decimal]:
        monthly = ZERO
        for subscription in self.session.scalars(
            select(Subscription).where(
                Subscription.user_id == _as_uuid(user_id),
                Subscription.deleted_at.is_(None),
                Subscription.is_active.is_(True),
            )
        ):
            if subscription.frequency == "weekly":
                monthly += subscription.amount * Decimal(52) / Decimal(12)
            elif subscription.frequency == "yearly":
                monthly += subscription.amount / Decimal(12)
            else:
                monthly += subscription.amount
        monthly = _money(monthly)
        return {"monthly": monthly, "yearly": _money(monthly * Decimal(12))}

    def create_asset(
        self,
        user_id: uuid.UUID | str,
        name: str,
        asset_type: str,
        current_value: Decimal | int | str,
        *,
        acquired_at: date | None = None,
        notes: str | None = None,
    ) -> Asset:
        value = _money(current_value)
        if value < ZERO:
            raise ValidationError("O valor do ativo não pode ser negativo.")
        return self.create(
            Asset,
            user_id=_as_uuid(user_id),
            name=name.strip(),
            asset_type=asset_type,
            current_value=value,
            acquired_at=acquired_at,
            notes=notes,
        )

    def create_liability(
        self,
        user_id: uuid.UUID | str,
        name: str,
        liability_type: str,
        current_balance: Decimal | int | str,
        *,
        due_date: date | None = None,
        interest_rate: Decimal | int | str | None = None,
        notes: str | None = None,
    ) -> Liability:
        balance = _money(current_balance)
        if balance < ZERO:
            raise ValidationError("O saldo do passivo não pode ser negativo.")
        rate = (
            Decimal(str(interest_rate)).quantize(Decimal("0.0001"))
            if interest_rate is not None
            else None
        )
        return self.create(
            Liability,
            user_id=_as_uuid(user_id),
            name=name.strip(),
            liability_type=liability_type,
            current_balance=balance,
            due_date=due_date,
            interest_rate=rate,
            notes=notes,
        )

    def create_favorite_transaction(
        self,
        user_id: uuid.UUID | str,
        name: str,
        description: str,
        transaction_type: str,
        *,
        amount: Decimal | int | str | None = None,
        category_id: uuid.UUID | str | None = None,
        account_id: uuid.UUID | str | None = None,
        credit_card_id: uuid.UUID | str | None = None,
        payment_method: str | None = None,
        notes: str | None = None,
    ) -> FavoriteTransaction:
        uid = _as_uuid(user_id)
        return self.create(
            FavoriteTransaction,
            user_id=uid,
            name=name.strip(),
            description=description.strip(),
            amount=_money(amount) if amount is not None else None,
            transaction_type=transaction_type,
            category_id=self._owned_reference(Category, category_id, uid),
            account_id=self._owned_reference(Account, account_id, uid),
            credit_card_id=self._owned_reference(CreditCard, credit_card_id, uid),
            payment_method=payment_method,
            notes=notes,
        )

    def net_worth_summary(self, user_id: uuid.UUID | str) -> dict[str, Decimal]:
        uid = _as_uuid(user_id)
        accounts = self.total_available_balance(uid)
        registered_assets = _money(
            self.session.scalar(
                select(func.coalesce(func.sum(Asset.current_value), ZERO)).where(
                    Asset.user_id == uid,
                    Asset.deleted_at.is_(None),
                    Asset.is_active.is_(True),
                )
            )
            or ZERO
        )
        registered_liabilities = _money(
            self.session.scalar(
                select(func.coalesce(func.sum(Liability.current_balance), ZERO)).where(
                    Liability.user_id == uid,
                    Liability.deleted_at.is_(None),
                    Liability.is_active.is_(True),
                )
            )
            or ZERO
        )
        invoices = _money(
            self.session.scalar(
                select(
                    func.coalesce(func.sum(CreditCardInvoice.total_amount), ZERO)
                ).where(
                    CreditCardInvoice.user_id == uid,
                    CreditCardInvoice.deleted_at.is_(None),
                    CreditCardInvoice.status.in_(("open", "closed", "overdue")),
                )
            )
            or ZERO
        )
        loans = _money(
            self.session.scalar(
                select(func.coalesce(func.sum(LoanInstallment.amount), ZERO))
                .join(Loan, Loan.id == LoanInstallment.loan_id)
                .where(
                    LoanInstallment.user_id == uid,
                    LoanInstallment.deleted_at.is_(None),
                    LoanInstallment.status.in_(("pending", "overdue")),
                    Loan.deleted_at.is_(None),
                    Loan.status == "active",
                )
            )
            or ZERO
        )
        assets = accounts + registered_assets
        liabilities = registered_liabilities + invoices + loans
        return {
            "accounts": accounts,
            "registered_assets": registered_assets,
            "assets": assets,
            "registered_liabilities": registered_liabilities,
            "card_invoices": invoices,
            "loans": loans,
            "liabilities": liabilities,
            "net_worth": assets - liabilities,
        }

    def create_net_worth_snapshot(
        self, user_id: uuid.UUID | str, *, snapshot_date: date | None = None
    ) -> NetWorthSnapshot:
        uid, day = _as_uuid(user_id), snapshot_date or datetime.now(timezone.utc).date()
        totals = self.net_worth_summary(uid)
        snapshot = self.session.scalar(
            select(NetWorthSnapshot)
            .where(
                NetWorthSnapshot.user_id == uid,
                NetWorthSnapshot.snapshot_date == day,
            )
            .with_for_update()
        )
        if snapshot is None:
            return self.create(
                NetWorthSnapshot,
                user_id=uid,
                snapshot_date=day,
                assets_total=totals["assets"],
                liabilities_total=totals["liabilities"],
                net_worth=totals["net_worth"],
            )
        snapshot.assets_total = totals["assets"]
        snapshot.liabilities_total = totals["liabilities"]
        snapshot.net_worth = totals["net_worth"]
        self.session.flush()
        return snapshot

    def list_upcoming_events(
        self,
        user_id: uuid.UUID | str,
        *,
        start_date: date,
        end_date: date,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for bill in self.list_bills(
            user_id,
            statuses=("pending", "overdue"),
            start_due_date=start_date,
            end_due_date=end_date,
            limit=limit,
        ):
            events.append(
                {
                    "kind": "bill",
                    "date": bill.due_date,
                    "description": bill.description,
                    "amount": bill.amount,
                    "record": bill,
                }
            )
        for invoice in self.list_invoices(
            user_id,
            statuses=("open", "closed", "overdue"),
            start_due_date=start_date,
            end_due_date=end_date,
            limit=limit,
        ):
            events.append(
                {
                    "kind": "invoice",
                    "date": invoice.due_date,
                    "description": f"Fatura {invoice.credit_card.name}",
                    "amount": invoice.total_amount,
                    "record": invoice,
                }
            )
        installments = self.list_loan_installments(
            user_id, statuses=("pending", "overdue")
        )
        loan_by_id = {loan.id: loan for loan in self.list_loans(user_id)}
        for installment in installments:
            if not start_date <= installment.due_date <= end_date:
                continue
            loan = loan_by_id.get(installment.loan_id)
            if loan is None:
                continue
            events.append(
                {
                    "kind": "loan",
                    "date": installment.due_date,
                    "description": (
                        f"{loan.name} · parcela {installment.installment_number}/"
                        f"{loan.total_installments}"
                    ),
                    "amount": installment.amount,
                    "record": installment,
                }
            )
        events.sort(key=lambda item: (item["date"], item["kind"]))
        return events[: max(1, min(limit, 200))]

    def backup_stats(self, user_id: uuid.UUID | str) -> BackupStats:
        row = self.session.execute(
            select(
                func.count(Transaction.id).label("count"),
                func.max(Transaction.transaction_date).label("last_date"),
            ).where(
                Transaction.user_id == _as_uuid(user_id),
                Transaction.deleted_at.is_(None),
            )
        ).one()
        return BackupStats(int(row.count), row.last_date)


@contextmanager
def repository_context(
    database_url: str | None = None, *, engine: Engine | None = None
) -> Iterator[FinanceRepository]:
    """Yield a repository inside one automatic commit/rollback transaction."""

    with session_scope(database_url, engine=engine) as session:
        yield FinanceRepository(session)


__all__ = [
    "AccountBalance",
    "BackupStats",
    "CardSummary",
    "FinanceRepository",
    "InstallmentPlanSummary",
    "LoanSummary",
    "MonthlySummary",
    "Page",
    "RecordNotFoundError",
    "RepositoryError",
    "ValidationError",
    "repository_context",
]
