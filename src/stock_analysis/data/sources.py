from __future__ import annotations

from dataclasses import dataclass, asdict

from stock_analysis.domain import ReportRequest


@dataclass(frozen=True)
class Source:
    name: str
    data_type: str
    url: str
    required: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def sources_for(request: ReportRequest) -> list[Source]:
    ticker = request.ticker
    if request.country == "india":
        exchange_url = (
            f"https://www.nseindia.com/get-quotes/equity?symbol={ticker}"
            if request.exchange == "nse"
            else f"https://www.bseindia.com/stock-share-price/x/{ticker}/"
        )
        return [
            Source("Screener.in consolidated", "financials, history and peers", f"https://www.screener.in/company/{ticker}/consolidated/", True),
            Source(request.exchange.upper(), "exchange quote and filings", exchange_url, True),
            Source("SEBI", "regulatory filings", "https://www.sebi.gov.in/"),
            Source("Company investor relations", "results and presentations", "Discover from the issuer's official website", True),
        ]
    sec_ticker = ticker.replace(".", "-")
    return [
        Source("SEC EDGAR", "regulatory filings", f"https://www.sec.gov/edgar/browse/?CIK={sec_ticker}&owner=exclude", True),
        Source(request.exchange.upper(), "quote and market data", f"https://www.nasdaq.com/market-activity/stocks/{ticker.lower()}", True),
        Source("Company investor relations", "results and presentations", "Discover from the issuer's official website", True),
    ]

