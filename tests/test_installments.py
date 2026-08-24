from datetime import date
from decimal import Decimal

import pytest

from services.installment_service import (
    generate_installment_schedule,
    split_installment_amounts,
)


def test_split_installments_adjusts_last_cent_and_preserves_total():
    parts = split_installment_amounts("R$ 100,00", 3)

    assert parts == (Decimal("33.33"), Decimal("33.33"), Decimal("33.34"))
    assert sum(parts) == Decimal("100.00")


def test_card_installment_schedule_uses_each_invoice_month():
    schedule = generate_installment_schedule(
        "1200,01",
        3,
        date(2026, 8, 24),
        closing_day=25,
        due_day=10,
        description="Notebook",
        group_id="purchase-1",
    )

    assert [item.label for item in schedule] == ["1/3", "2/3", "3/3"]
    assert [item.amount for item in schedule] == [
        Decimal("400.00"),
        Decimal("400.00"),
        Decimal("400.01"),
    ]
    assert [item.due_date for item in schedule] == [
        date(2026, 9, 10),
        date(2026, 10, 10),
        date(2026, 11, 10),
    ]
    assert sum((item.amount for item in schedule), Decimal("0")) == Decimal("1200.01")


def test_installment_count_must_be_positive():
    with pytest.raises(ValueError):
        split_installment_amounts("100,00", 0)
