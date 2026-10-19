from stock_analysis.reports.chart_payload import ChartPayload, PriceLevel


def test_chart_payload_rejects_too_many_markers() -> None:
    payload = ChartPayload(
        candles=[{"time": "2026-10-19", "open": 1, "high": 2, "low": 1, "close": 2}],
        volume=[],
        markers=[{}] * 9,
    )
    try:
        payload.as_template_data()
    except ValueError as error:
        assert "eight" in str(error)
    else:
        raise AssertionError("expected marker budget validation")


def test_chart_payload_serializes_levels() -> None:
    payload = ChartPayload(
        candles=[{"time": "2026-10-19", "open": 1, "high": 2, "low": 1, "close": 2}],
        volume=[],
        levels=[PriceLevel(100, "Support", "#16804b")],
    )
    assert payload.as_template_data()["levels"][0]["label"] == "Support"
