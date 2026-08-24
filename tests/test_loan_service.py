from datetime import date
from decimal import Decimal

import pytest

from services.loan_service import generate_loan_schedule


def test_loan_schedule_preserves_total_and_tracks_paid_installments() -> None:
    schedule = generate_loan_schedule(
        Decimal("1000.00"),
        3,
        date(2026, 1, 31),
        paid_installments=1,
    )

    assert [item.amount for item in schedule] == [
        Decimal("333.33"),
        Decimal("333.33"),
        Decimal("333.34"),
    ]
    assert [item.due_date for item in schedule] == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
    ]
    assert [item.initially_paid for item in schedule] == [True, False, False]


def test_loan_schedule_rejects_invalid_paid_count() -> None:
    with pytest.raises(ValueError, match="parcelas pagas"):
        generate_loan_schedule(
            Decimal("100.00"),
            2,
            date(2026, 1, 10),
            paid_installments=3,
        )
