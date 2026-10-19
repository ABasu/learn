from stock_analysis.reports.formatting import format_currency


def test_indian_convention_uses_lakhs_and_crores() -> None:
    assert format_currency(123_456, "INR", "indian") == "₹1.2 lakh"
    assert format_currency(1_234_500_000, "INR", "indian") == "₹123.5 crore"
    assert format_currency(12_345_000_000, "INR", "indian") == "₹1,234.5 crore"


def test_international_convention_uses_millions_and_billions() -> None:
    assert format_currency(1_234_500, "USD", "international") == "$1.2 million"
    assert format_currency(1_234_500_000, "USD", "international") == "$1.2 billion"
