"""Local financial analytics and neutral, calculation-based insights."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from services.finance_service import (
    CANCELLED_STATUSES,
    EXPENSE_TYPES,
    INCOME_TYPES,
    TRANSFER_TYPES,
    get_transaction_type,
    transaction_affects_cash_balance,
)
from utils.currency import (
    MoneyLike,
    ZERO,
    format_brl_currency,
    format_brl_percentage,
    parse_brl_currency,
)
from utils.dates import DateLike, add_months, days_in_month, month_start, parse_date
from utils.helpers import get_value, normalize_token


@dataclass(frozen=True, slots=True)
class MonthlySummary:
    reference_month: date
    income: Decimal
    expenses: Decimal
    transaction_count: int = 0

    @property
    def savings(self) -> Decimal:
        return self.income - self.expenses

    @property
    def net(self) -> Decimal:
        return self.savings

    @property
    def savings_rate(self) -> Decimal | None:
        if self.income == ZERO:
            return None
        return (self.savings / self.income * Decimal("100")).quantize(Decimal("0.1"))


@dataclass(frozen=True, slots=True)
class BudgetUsage:
    category: str
    spent: Decimal
    limit: Decimal

    @property
    def remaining(self) -> Decimal:
        return self.limit - self.spent

    @property
    def percentage(self) -> Decimal:
        if self.limit <= ZERO:
            return ZERO
        return (self.spent / self.limit * Decimal("100")).quantize(Decimal("0.1"))


@dataclass(frozen=True, slots=True)
class RankedExpense:
    description: str
    amount: Decimal
    transaction_date: date
    category: str
    original: Any


def calculate_monthly_summary(
    transactions: Iterable[Any],
    reference_date: DateLike,
    *,
    date_basis: str = "competence",
) -> MonthlySummary:
    """Calculate accrual-style monthly income, expenses and savings.

    Transfers are excluded. Card purchases are included as expenses in their
    competence month even though they do not yet affect bank cash.
    """

    reference = month_start(reference_date)
    income = ZERO
    expenses = ZERO
    count = 0
    for transaction in transactions:
        if not _is_analytics_record(transaction):
            continue
        if not _include_for_basis(transaction, date_basis):
            continue
        tx_date = _analytics_date(transaction, date_basis)
        if tx_date is None or month_start(tx_date) != reference:
            continue
        kind = get_transaction_type(transaction)
        amount = _amount(transaction)
        if kind in INCOME_TYPES:
            income += amount
            count += 1
        elif kind in EXPENSE_TYPES:
            expenses += amount
            count += 1
    return MonthlySummary(
        reference,
        parse_brl_currency(income),
        parse_brl_currency(expenses),
        count,
    )


def monthly_summary(
    transactions: Iterable[Any],
    year: int | DateLike,
    month: int | None = None,
    *,
    date_basis: str = "competence",
) -> MonthlySummary:
    """Compatibility wrapper accepting either a reference date or year/month."""

    reference = parse_date(year) if month is None else date(int(year), month, 1)
    return calculate_monthly_summary(transactions, reference, date_basis=date_basis)


def monthly_series(
    transactions: Iterable[Any],
    *,
    months: int = 6,
    end_date: DateLike | None = None,
    date_basis: str = "competence",
) -> tuple[MonthlySummary, ...]:
    """Return chronological summaries for the latest N months."""

    if months < 1:
        raise ValueError("months deve ser maior que zero.")
    end_month = month_start(end_date or date.today())
    transaction_list = tuple(transactions)
    return tuple(
        calculate_monthly_summary(
            transaction_list,
            add_months(end_month, offset, preferred_day=1),
            date_basis=date_basis,
        )
        for offset in range(-(months - 1), 1)
    )


def spending_by_category(
    transactions: Iterable[Any],
    reference_date: DateLike,
    *,
    date_basis: str = "competence",
) -> dict[str, Decimal]:
    """Return expense totals grouped by display category."""

    reference = month_start(reference_date)
    totals: defaultdict[str, Decimal] = defaultdict(lambda: ZERO)
    for transaction in transactions:
        if not _is_analytics_record(transaction):
            continue
        if not _include_for_basis(transaction, date_basis):
            continue
        if get_transaction_type(transaction) not in EXPENSE_TYPES:
            continue
        tx_date = _analytics_date(transaction, date_basis)
        if tx_date is None or month_start(tx_date) != reference:
            continue
        totals[_category_name(transaction)] += _amount(transaction)
    return {
        category: parse_brl_currency(amount)
        for category, amount in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    }


def rank_expenses(
    transactions: Iterable[Any],
    reference_date: DateLike,
    *,
    limit: int = 5,
    date_basis: str = "competence",
) -> tuple[RankedExpense, ...]:
    """Return the highest expenses for a month."""

    if limit < 0:
        raise ValueError("limit nao pode ser negativo.")
    reference = month_start(reference_date)
    ranked: list[RankedExpense] = []
    for transaction in transactions:
        if not _is_analytics_record(transaction):
            continue
        if not _include_for_basis(transaction, date_basis):
            continue
        if get_transaction_type(transaction) not in EXPENSE_TYPES:
            continue
        tx_date = _analytics_date(transaction, date_basis)
        if tx_date is None or month_start(tx_date) != reference:
            continue
        ranked.append(
            RankedExpense(
                description=str(
                    get_value(transaction, "description", "descricao", default="Despesa")
                ),
                amount=_amount(transaction),
                transaction_date=tx_date,
                category=_category_name(transaction),
                original=transaction,
            )
        )
    ranked.sort(key=lambda item: item.amount, reverse=True)
    return tuple(ranked[:limit])


def percentage_change(current: MoneyLike, previous: MoneyLike) -> Decimal | None:
    """Return percentage change, or ``None`` when the comparison base is zero."""

    current_value = parse_brl_currency(current)
    previous_value = parse_brl_currency(previous)
    if previous_value == ZERO:
        return None
    return ((current_value - previous_value) / abs(previous_value) * Decimal("100")).quantize(
        Decimal("0.1")
    )


def calculate_budget_usage(
    budgets: Mapping[str, MoneyLike] | Iterable[Any],
    category_spending: Mapping[str, MoneyLike],
) -> tuple[BudgetUsage, ...]:
    """Match category spending against configured monthly budgets."""

    if isinstance(budgets, Mapping):
        budget_items = budgets.items()
    else:
        budget_items = (
            (
                _budget_category_name(item),
                get_value(item, "limit", "amount", "valor", "limite", default=ZERO),
            )
            for item in budgets
            if get_value(item, "deleted_at", "excluido_em") is None
        )
    normalized_spending = {
        normalize_token(category): parse_brl_currency(amount)
        for category, amount in category_spending.items()
    }
    result: list[BudgetUsage] = []
    for category, limit in budget_items:
        limit_value = parse_brl_currency(limit)
        spent = normalized_spending.get(normalize_token(category), ZERO)
        result.append(BudgetUsage(str(category), spent, limit_value))
    return tuple(sorted(result, key=lambda item: item.percentage, reverse=True))


def estimate_month_end_expenses(
    expenses_so_far: MoneyLike,
    as_of: DateLike,
) -> Decimal:
    """Linearly estimate month-end spending from the elapsed calendar days."""

    reference = parse_date(as_of)
    expenses = parse_brl_currency(expenses_so_far)
    estimate = expenses / reference.day * days_in_month(reference.year, reference.month)
    return parse_brl_currency(estimate)


def generate_financial_insights(
    transactions: Iterable[Any],
    reference_date: DateLike,
    *,
    budgets: Mapping[str, MoneyLike] | Iterable[Any] | None = None,
    subscriptions_total: MoneyLike | None = None,
    forecast_end_balance: MoneyLike | None = None,
    as_of: DateLike | None = None,
) -> tuple[str, ...]:
    """Generate concise, non-judgmental Portuguese insights using local math."""

    reference = parse_date(reference_date)
    transaction_list = tuple(transactions)
    current = calculate_monthly_summary(transaction_list, reference)
    previous_reference = add_months(reference, -1, preferred_day=1)
    previous = calculate_monthly_summary(transaction_list, previous_reference)
    current_categories = spending_by_category(transaction_list, reference)
    previous_categories = spending_by_category(transaction_list, previous_reference)
    insights: list[str] = []

    expense_change = percentage_change(current.expenses, previous.expenses)
    if expense_change is not None:
        if expense_change < ZERO:
            insights.append(
                f"As despesas do mes estao {format_brl_percentage(abs(expense_change))} "
                "abaixo do mes anterior."
            )
        elif expense_change > ZERO:
            insights.append(
                f"As despesas do mes estao {format_brl_percentage(expense_change)} "
                "acima do mes anterior."
            )

    for category, amount in current_categories.items():
        previous_amount = _mapping_value(previous_categories, category)
        change = percentage_change(amount, previous_amount)
        if change is None or change == ZERO:
            continue
        direction = "acima" if change > ZERO else "abaixo"
        insights.append(
            f"Os gastos com {category} estao {format_brl_percentage(abs(change))} "
            f"{direction} do mes anterior."
        )
        break

    if subscriptions_total is None:
        subscriptions_total = _mapping_value(current_categories, "Assinaturas")
    subscriptions = parse_brl_currency(subscriptions_total)
    if subscriptions > ZERO and current.income > ZERO:
        share = subscriptions / current.income * Decimal("100")
        insights.append(
            "As assinaturas representam "
            f"{format_brl_percentage(share)} da renda registrada no mes."
        )

    if budgets is not None:
        for usage in calculate_budget_usage(budgets, current_categories):
            if usage.limit > ZERO and usage.percentage >= Decimal("70"):
                insights.append(
                    f"O orcamento de {usage.category} esta em "
                    f"{format_brl_percentage(usage.percentage)} de utilizacao."
                )

    effective_as_of = parse_date(as_of or reference)
    if month_start(effective_as_of) == month_start(reference) and current.expenses > ZERO:
        estimate = estimate_month_end_expenses(current.expenses, effective_as_of)
        insights.append(
            "Mantido o ritmo atual, as despesas do mes ficam em aproximadamente "
            f"{format_brl_currency(estimate)}."
        )
    if forecast_end_balance is not None:
        insights.append(
            "O saldo previsto ao fim do periodo e "
            f"{format_brl_currency(forecast_end_balance)}."
        )
    return tuple(insights)


def _analytics_date(transaction: Any, date_basis: str) -> date | None:
    basis = normalize_token(date_basis)
    if basis in {"competence", "competencia", "accrual"}:
        raw = get_value(
            transaction,
            "competence_date",
            "data_competencia",
            "due_date",
            "data_vencimento",
            "transaction_date",
            "date",
            "data",
        )
    elif basis in {"cash", "caixa", "payment"}:
        raw = get_value(
            transaction,
            "transaction_date",
            "date",
            "data",
            "paid_at",
            "data_pagamento",
        )
    else:
        raise ValueError("date_basis deve ser 'competence' ou 'cash'.")
    return parse_date(raw) if raw is not None else None


def _is_analytics_record(transaction: Any) -> bool:
    if get_value(transaction, "deleted_at", "excluido_em") is not None:
        return False
    status = normalize_token(get_value(transaction, "status", default=""))
    if status in CANCELLED_STATUSES:
        return False
    return get_transaction_type(transaction) not in TRANSFER_TYPES


def _include_for_basis(transaction: Any, date_basis: str) -> bool:
    basis = normalize_token(date_basis)
    if basis in {"cash", "caixa", "payment"}:
        return transaction_affects_cash_balance(transaction)
    if basis in {"competence", "competencia", "accrual"}:
        source = normalize_token(get_value(transaction, "source", "origem", default=""))
        return source not in {
            "invoice_payment",
            "pagamento_fatura",
            "loan_disbursement",
            "loan_disbursement_cash",
            "emprestimo_recebido",
        }
    raise ValueError("date_basis deve ser 'competence' ou 'cash'.")


def _amount(transaction: Any) -> Decimal:
    return abs(
        parse_brl_currency(get_value(transaction, "amount", "value", "valor", default=ZERO))
    )


def _category_name(transaction: Any) -> str:
    direct = get_value(transaction, "category_name", "categoria_nome")
    if direct is not None:
        return str(direct)
    category = get_value(transaction, "category", "categoria")
    if category is not None:
        if isinstance(category, str):
            return category
        nested_name = get_value(category, "name", "nome")
        if nested_name is not None:
            return str(nested_name)
    category_id = get_value(transaction, "category_id", "categoria_id")
    return str(category_id) if category_id is not None else "Outros"


def _mapping_value(values: Mapping[str, MoneyLike], wanted: str) -> Decimal:
    normalized = normalize_token(wanted)
    for key, value in values.items():
        if normalize_token(key) == normalized:
            return parse_brl_currency(value)
    return ZERO


def _budget_category_name(budget: Any) -> str:
    direct = get_value(budget, "category_name", "categoria_nome")
    if direct is not None:
        return str(direct)
    category = get_value(budget, "category", "categoria")
    if category is not None:
        if isinstance(category, str):
            return category
        nested = get_value(category, "name", "nome")
        if nested is not None:
            return str(nested)
    category_id = get_value(budget, "category_id", "categoria_id")
    return str(category_id) if category_id is not None else "Outros"


# UI-friendly aliases.
get_monthly_summary = calculate_monthly_summary
get_category_spending = spending_by_category
generate_insights = generate_financial_insights
top_expenses = rank_expenses
