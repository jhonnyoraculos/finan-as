from decimal import Decimal

import pytest

from utils.currency import CurrencyParseError, format_brl_currency, parse_brl_currency
from utils.helpers import display_currency, mask_currency


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("R$ 1.234,56", Decimal("1234.56")),
        ("1234,5", Decimal("1234.50")),
        ("1.234", Decimal("1234.00")),
        ("-R$ 47,80", Decimal("-47.80")),
        ("(R$ 10,00)", Decimal("-10.00")),
        (Decimal("9.999"), Decimal("10.00")),
    ],
)
def test_parse_brl_currency(raw, expected):
    assert parse_brl_currency(raw) == expected


def test_currency_formatting_and_privacy():
    assert format_brl_currency("1234,56") == "R$ 1.234,56"
    assert format_brl_currency("-47,8") == "-R$ 47,80"
    assert display_currency("1234,56", private=True) == "R$ \u2022\u2022\u2022\u2022\u2022\u2022"
    assert mask_currency(None) == "R$ \u2022\u2022\u2022\u2022\u2022\u2022"


@pytest.mark.parametrize(
    "raw", ["", "R$ xyz", "1,2,3", "12.34,56", "1,234", None, True]
)
def test_invalid_currency_is_rejected(raw):
    with pytest.raises(CurrencyParseError):
        parse_brl_currency(raw)
