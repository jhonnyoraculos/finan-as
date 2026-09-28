from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.models import Base
from database.repository import FinanceRepository
from services.application_service import post_card_purchase


def _repository() -> tuple[Session, FinanceRepository]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    return session, FinanceRepository(session)


def test_create_and_pay_monthly_loan() -> None:
    session, repository = _repository()
    try:
        user = repository.create_user("Teste")
        account = repository.create_account(user.id, "Conta")
        loan = repository.create_loan(
            user.id,
            "Empréstimo pessoal",
            Decimal("1000.00"),
            Decimal("1200.00"),
            12,
            date(2026, 9, 10),
            account_id=account.id,
            paid_installments=2,
            disbursement_date=date(2026, 8, 24),
        )

        summary = repository.list_loan_summaries(user.id)[0]
        assert loan.disbursement_transaction_id is None
        assert summary.paid_installments == 2
        assert summary.remaining_installments == 10
        assert summary.outstanding_amount == Decimal("1000.00")
        assert repository.monthly_summary(user.id, date(2026, 8, 1)).income == Decimal(
            "0.00"
        )

        repository.pay_loan_installment(
            user.id, summary.next_installment.id, account_id=account.id
        )
        updated = repository.list_loan_summaries(user.id)[0]
        assert updated.paid_installments == 3
        assert updated.remaining_installments == 9
        assert repository.net_worth_summary(user.id)["loans"] == Decimal("900.00")
    finally:
        session.close()


def test_loan_disbursement_never_inflates_available_balance() -> None:
    session, repository = _repository()
    try:
        user = repository.create_user("Teste")
        account = repository.create_account(user.id, "Conta")
        loan = repository.create_loan(
            user.id,
            "Empréstimo pessoal",
            Decimal("4700.00"),
            Decimal("5200.00"),
            10,
            date(2026, 10, 10),
            account_id=account.id,
            record_disbursement=True,
            disbursement_date=date(2026, 9, 28),
        )

        assert loan.disbursement_transaction_id is not None
        assert repository.total_available_balance(user.id) == Decimal("0.00")
    finally:
        session.close()


def test_paying_card_invoice_reduces_remaining_months() -> None:
    session, repository = _repository()
    try:
        user = repository.create_user("Teste")
        account = repository.create_account(user.id, "Conta")
        card = repository.create_credit_card(
            user.id,
            "Cartão",
            Decimal("5000.00"),
            20,
            10,
            payment_account_id=account.id,
        )
        post_card_purchase(
            repository,
            user_id=user.id,
            card=card,
            description="Notebook",
            total_amount=Decimal("1200.00"),
            purchase_date=date(2026, 8, 24),
            installment_count=12,
        )
        invoice = min(
            repository.list_invoices(user.id, credit_card_id=card.id),
            key=lambda item: item.due_date,
        )

        repository.pay_invoice(user.id, invoice.id, account_id=account.id)

        plan = repository.list_installment_plans(
            user.id, credit_card_id=card.id
        )[0]
        assert plan.paid_installments == 1
        assert plan.remaining_installments == 11
        assert plan.remaining_amount == Decimal("1100.00")
    finally:
        session.close()
