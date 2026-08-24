from datetime import date
from decimal import Decimal

from services.recurring_service import (
    generate_recurrence_dates,
    generate_recurrence_occurrences,
)


def test_monthly_recurrence_keeps_anchor_day_after_short_month():
    dates = generate_recurrence_dates(
        "2026-01-31", "2026-04-30", "mensal"
    )

    assert dates == (
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
    )


def test_recurrence_generation_skips_existing_occurrence_without_duplication():
    rule = {
        "id": 7,
        "descricao": "Internet",
        "valor": "119,90",
        "data_inicio": "2026-01-31",
        "frequencia": "mensal",
        "tipo": "despesa",
    }

    occurrences = generate_recurrence_occurrences(
        rule,
        "2026-01-01",
        "2026-04-30",
        existing_occurrences=[{"recurrence_id": 7, "due_date": "2026-02-28"}],
    )

    assert [item.occurrence_date for item in occurrences] == [
        date(2026, 1, 31),
        date(2026, 3, 31),
        date(2026, 4, 30),
    ]
    assert [item.sequence for item in occurrences] == [1, 3, 4]
    assert all(item.amount == Decimal("119.90") for item in occurrences)


def test_persisted_recurrence_key_can_be_used_for_pure_deduplication():
    rule = {
        "id": "rule-1",
        "descricao": "Academia",
        "valor": "90,00",
        "data_inicio": "2026-08-10",
        "frequencia": "mensal",
    }
    initial = generate_recurrence_occurrences(rule, "2026-08-01", "2026-08-31")

    repeated = generate_recurrence_occurrences(
        rule,
        "2026-08-01",
        "2026-08-31",
        existing_occurrences=[initial[0].persistence_key],
    )

    assert initial[0].persistence_key == "rule-1:2026-08-10"
    assert repeated == ()
