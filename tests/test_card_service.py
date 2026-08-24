from datetime import date

from services.card_service import calculate_invoice_dates, get_invoice_status


def test_purchase_on_or_before_closing_day_uses_current_cycle():
    before = calculate_invoice_dates(date(2026, 8, 24), closing_day=25, due_day=10)
    on_day = calculate_invoice_dates(date(2026, 8, 25), closing_day=25, due_day=10)

    assert before.closing_date == date(2026, 8, 25)
    assert on_day.closing_date == date(2026, 8, 25)
    assert before.due_date == date(2026, 9, 10)
    assert before.competence_date == date(2026, 9, 1)


def test_purchase_after_closing_day_uses_next_cycle():
    cycle = calculate_invoice_dates(date(2026, 8, 26), closing_day=25, due_day=10)

    assert cycle.closing_date == date(2026, 9, 25)
    assert cycle.due_date == date(2026, 10, 10)
    assert cycle.competence_date == date(2026, 10, 1)


def test_invoice_status_is_derived_without_persistence():
    assert (
        get_invoice_status("2026-08-25", "2026-09-10", as_of="2026-08-24")
        == "aberta"
    )
    assert (
        get_invoice_status("2026-08-25", "2026-09-10", as_of="2026-09-01")
        == "fechada"
    )
    assert (
        get_invoice_status("2026-08-25", "2026-09-10", as_of="2026-09-11")
        == "atrasada"
    )
    assert (
        get_invoice_status("2026-08-25", "2026-09-10", paid=True, as_of="2026-09-11")
        == "paga"
    )
