"""Core cash-balance and transfer rules.

All functions accept dictionaries as well as ORM-like objects so this module
stays independent from SQLAlchemy and Streamlit.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Hashable

from utils.currency import MoneyLike, ZERO, parse_brl_currency
from utils.dates import DateLike, parse_date
from utils.helpers import as_bool, get_value, normalize_token


INCOME_TYPES = {"receita", "income", "entrada", "credito", "credit"}
EXPENSE_TYPES = {
    "despesa",
    "expense",
    "saida",
    "debito",
    "debit",
    "invoice_payment",
    "pagamento_fatura",
}
TRANSFER_TYPES = {"transferencia", "transfer", "pix_transfer"}
CANCELLED_STATUSES = {
    "cancelado",
    "cancelada",
    "cancelled",
    "excluido",
    "excluida",
    "estornado",
    "estornada",
}
UNSETTLED_STATUSES = {
    "pendente",
    "pending",
    "agendado",
    "agendada",
    "scheduled",
    "aberto",
    "aberta",
    "open",
    "unpaid",
}
CREDIT_METHODS = {
    "credito",
    "credit",
    "credit_card",
    "cartao",
    "cartao_credito",
}


@dataclass(frozen=True, slots=True)
class Transfer:
    source_account_id: Hashable
    destination_account_id: Hashable
    amount: Decimal
    transfer_date: date
    transfer_id: Hashable | None = None
    description: str = "Transferencia"


@dataclass(frozen=True, slots=True)
class AccountMovement:
    """One side of a linked transfer, ready to map to a persistence model."""

    account_id: Hashable
    amount: Decimal
    direction: str
    transfer_id: Hashable | None
    transaction_date: date
    description: str
    transaction_type: str = "transferencia"

    @property
    def cash_effect(self) -> Decimal:
        return -self.amount if self.direction == "saida" else self.amount


@dataclass(frozen=True, slots=True)
class FinancialTotals:
    income: Decimal = ZERO
    expenses: Decimal = ZERO

    @property
    def net(self) -> Decimal:
        return self.income - self.expenses


def get_transaction_type(transaction: Any) -> str:
    return normalize_token(
        get_value(transaction, "transaction_type", "type", "tipo", default="")
    )


def is_credit_card_purchase(transaction: Any) -> bool:
    """Return whether a record is a purchase that belongs to a card invoice."""

    explicit = get_value(transaction, "is_credit_card_purchase", "compra_cartao")
    if explicit is not None:
        return as_bool(explicit)
    source = normalize_token(get_value(transaction, "source", "origem", default=""))
    if source in {"invoice_payment", "pagamento_fatura"}:
        return False
    if get_transaction_type(transaction) in {"invoice_payment", "pagamento_fatura"}:
        return False
    subtype = normalize_token(get_value(transaction, "subtype", "subtipo", default=""))
    if subtype in {"invoice_payment", "pagamento_fatura"}:
        return False
    if as_bool(get_value(transaction, "is_invoice_payment", "pagamento_de_fatura", default=False)):
        return False
    method = normalize_token(
        get_value(transaction, "payment_method", "forma_pagamento", default="")
    )
    card_id = get_value(transaction, "credit_card_id", "card_id", "cartao_id")
    return method in CREDIT_METHODS or card_id is not None


def transaction_affects_cash_balance(transaction: Any) -> bool:
    """Check whether a non-transfer record is already effective in cash."""

    if get_value(transaction, "deleted_at", "excluido_em") is not None:
        return False
    status = normalize_token(get_value(transaction, "status", default=""))
    if status in CANCELLED_STATUSES or status in UNSETTLED_STATUSES:
        return False
    paid_marker = get_value(transaction, "paid", "pago", default=None)
    if paid_marker is not None and not as_bool(paid_marker):
        return False
    if is_credit_card_purchase(transaction):
        # The purchase consumes card limit and invoice budget, not bank cash.
        return False
    return get_transaction_type(transaction) in INCOME_TYPES | EXPENSE_TYPES


def transaction_cash_effect(
    transaction: Any,
    *,
    account_id: Hashable | None = None,
    as_of: DateLike | None = None,
) -> Decimal:
    """Return a signed cash effect for an optional account.

    Globally, transfers always return zero. For one account, the source gets a
    negative effect and the destination an equal positive effect.
    """

    if get_value(transaction, "deleted_at", "excluido_em") is not None:
        return ZERO
    status = normalize_token(get_value(transaction, "status", default=""))
    if status in CANCELLED_STATUSES or status in UNSETTLED_STATUSES:
        return ZERO
    paid_marker = get_value(transaction, "paid", "pago", default=None)
    if paid_marker is not None and not as_bool(paid_marker):
        return ZERO
    event_date = get_value(
        transaction,
        "transaction_date",
        "transfer_date",
        "date",
        "data",
        "paid_at",
        "data_pagamento",
    )
    if as_of is not None and event_date is not None and parse_date(event_date) > parse_date(as_of):
        return ZERO

    kind = get_transaction_type(transaction)
    if kind in TRANSFER_TYPES or isinstance(transaction, (Transfer, AccountMovement)):
        return transfer_effect(transaction, account_id=account_id)
    if not transaction_affects_cash_balance(transaction):
        return ZERO

    record_account_id = get_value(transaction, "account_id", "conta_id")
    if account_id is not None:
        if record_account_id is None or not _same_id(record_account_id, account_id):
            return ZERO

    raw_amount = get_value(transaction, "amount", "value", "valor", default=ZERO)
    amount = abs(parse_brl_currency(raw_amount))
    if kind in INCOME_TYPES:
        return amount
    if kind in EXPENSE_TYPES:
        return -amount
    return ZERO


def calculate_account_balance(
    initial_balance: MoneyLike,
    transactions: Iterable[Any],
    *,
    account_id: Hashable | None = None,
    as_of: DateLike | None = None,
) -> Decimal:
    """Derive an account balance from the initial balance and effective cash flows."""

    balance = parse_brl_currency(initial_balance)
    for transaction in transactions:
        balance += transaction_cash_effect(transaction, account_id=account_id, as_of=as_of)
    return parse_brl_currency(balance)


def calculate_account_balances(
    initial_balances: Mapping[Hashable, MoneyLike],
    transactions: Iterable[Any],
    *,
    as_of: DateLike | None = None,
) -> dict[Hashable, Decimal]:
    """Calculate several account balances without mutating the input mapping."""

    transaction_list = tuple(transactions)
    return {
        account_id: calculate_account_balance(
            initial,
            transaction_list,
            account_id=account_id,
            as_of=as_of,
        )
        for account_id, initial in initial_balances.items()
    }


def calculate_available_balance(
    accounts: Iterable[Any],
    transactions: Iterable[Any],
    *,
    as_of: DateLike | None = None,
) -> Decimal:
    """Return the sum of all active cash-account balances."""

    account_list = tuple(accounts)
    transaction_list = tuple(transactions)
    total = ZERO
    for account in account_list:
        if get_value(account, "deleted_at", "excluido_em") is not None:
            continue
        active = get_value(account, "is_active", "active", "ativo", default=True)
        if not as_bool(active, default=True):
            continue
        account_id = get_value(account, "id", "account_id", "conta_id")
        initial = get_value(
            account,
            "initial_balance",
            "saldo_inicial",
            "balance",
            "saldo",
            default=ZERO,
        )
        total += calculate_account_balance(
            initial,
            transaction_list,
            account_id=account_id,
            as_of=as_of,
        )
    return parse_brl_currency(total)


def create_transfer(
    amount: MoneyLike,
    source_account_id: Hashable,
    destination_account_id: Hashable,
    transfer_date: DateLike,
    *,
    transfer_id: Hashable | None = None,
    description: str = "Transferencia",
) -> Transfer:
    """Validate and create an immutable account-to-account transfer."""

    if _same_id(source_account_id, destination_account_id):
        raise ValueError("As contas de origem e destino devem ser diferentes.")
    parsed_amount = parse_brl_currency(amount)
    if parsed_amount <= ZERO:
        raise ValueError("O valor da transferencia deve ser positivo.")
    return Transfer(
        source_account_id=source_account_id,
        destination_account_id=destination_account_id,
        amount=parsed_amount,
        transfer_date=parse_date(transfer_date),
        transfer_id=transfer_id,
        description=description.strip() or "Transferencia",
    )


def create_transfer_movements(transfer: Transfer) -> tuple[AccountMovement, AccountMovement]:
    """Return equal and opposite persistence-friendly transfer movements."""

    common = {
        "amount": transfer.amount,
        "transfer_id": transfer.transfer_id,
        "transaction_date": transfer.transfer_date,
        "description": transfer.description,
    }
    return (
        AccountMovement(account_id=transfer.source_account_id, direction="saida", **common),
        AccountMovement(account_id=transfer.destination_account_id, direction="entrada", **common),
    )


def transfer_effect(transfer: Any, *, account_id: Hashable | None = None) -> Decimal:
    """Calculate a transfer effect; without an account it is always neutral."""

    if account_id is None:
        return ZERO
    amount = abs(
        parse_brl_currency(get_value(transfer, "amount", "value", "valor", default=ZERO))
    )

    if isinstance(transfer, AccountMovement):
        if not _same_id(transfer.account_id, account_id):
            return ZERO
        return -amount if normalize_token(transfer.direction) in {"saida", "out"} else amount

    # Repository transfer pairs store each account and an explicit in/out side.
    record_account = get_value(transfer, "account_id", "conta_id")
    direction = normalize_token(
        get_value(transfer, "transfer_direction", "direction", "direcao", default="")
    )
    if direction and record_account is not None:
        if not _same_id(record_account, account_id):
            return ZERO
        if direction in {"saida", "out", "origem", "source"}:
            return -amount
        if direction in {"entrada", "in", "destino", "destination"}:
            return amount

    source = get_value(
        transfer,
        "source_account_id",
        "from_account_id",
        "conta_origem_id",
    )
    destination = get_value(
        transfer,
        "destination_account_id",
        "to_account_id",
        "conta_destino_id",
    )
    if source is not None or destination is not None:
        if source is not None and _same_id(source, account_id):
            return -amount
        if destination is not None and _same_id(destination, account_id):
            return amount
        return ZERO

    if record_account is None or not _same_id(record_account, account_id):
        return ZERO
    if direction in {"saida", "out", "origem", "source"}:
        return -amount
    if direction in {"entrada", "in", "destino", "destination"}:
        return amount
    return ZERO


def calculate_period_totals(
    transactions: Iterable[Any],
    start_date: DateLike,
    end_date: DateLike,
    *,
    cash_basis: bool = False,
) -> FinancialTotals:
    """Aggregate income and expenses, always excluding transfers."""

    start = parse_date(start_date)
    end = parse_date(end_date)
    if start > end:
        raise ValueError("start_date deve ser anterior ou igual a end_date.")
    income = ZERO
    expenses = ZERO
    for transaction in transactions:
        if get_value(transaction, "deleted_at", "excluido_em") is not None:
            continue
        status = normalize_token(get_value(transaction, "status", default=""))
        if status in CANCELLED_STATUSES:
            continue
        kind = get_transaction_type(transaction)
        if kind in TRANSFER_TYPES:
            continue
        source = normalize_token(get_value(transaction, "source", "origem", default=""))
        if not cash_basis and source in {"invoice_payment", "pagamento_fatura"}:
            # Accrual totals already contain the original card purchases.
            continue
        if cash_basis:
            tx_date = get_value(
                transaction,
                "transaction_date",
                "date",
                "data",
                "paid_at",
                "data_pagamento",
            )
        else:
            tx_date = get_value(
                transaction,
                "competence_date",
                "data_competencia",
                "transaction_date",
                "date",
                "data",
            )
        if tx_date is None or not start <= parse_date(tx_date) <= end:
            continue
        if cash_basis and not transaction_affects_cash_balance(transaction):
            continue
        amount = abs(
            parse_brl_currency(get_value(transaction, "amount", "value", "valor", default=ZERO))
        )
        if kind in INCOME_TYPES:
            income += amount
        elif kind in EXPENSE_TYPES:
            expenses += amount
    return FinancialTotals(parse_brl_currency(income), parse_brl_currency(expenses))


def _same_id(left: Any, right: Any) -> bool:
    return left == right or str(left) == str(right)


# Portuguese-friendly names used by some views.
calcular_saldo_conta = calculate_account_balance
calcular_saldo_disponivel = calculate_available_balance
