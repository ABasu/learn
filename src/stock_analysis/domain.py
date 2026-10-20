from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date


EXCHANGE_COUNTRIES = {
    "nse": "india",
    "bse": "india",
    "nasdaq": "us",
    "nyse": "us",
}


@dataclass(frozen=True)
class ReportRequest:
    ticker: str
    exchange: str
    risk: str = "moderate"
    technical_horizon: str = "4-8 weeks"
    fundamental_horizon: str = "1 year"
    as_of: str = date.today().isoformat()

    def __post_init__(self) -> None:
        ticker = self.ticker.strip().upper()
        exchange = self.exchange.strip().lower()
        risk = self.risk.strip().lower()
        if not ticker or not ticker.replace("-", "").replace(".", "").isalnum():
            raise ValueError("ticker must contain letters, numbers, a dash or a dot")
        if exchange not in EXCHANGE_COUNTRIES:
            raise ValueError(f"unsupported exchange: {exchange}")
        if risk not in {"conservative", "moderate", "aggressive"}:
            raise ValueError("risk must be conservative, moderate or aggressive")
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "exchange", exchange)
        object.__setattr__(self, "risk", risk)

    @property
    def country(self) -> str:
        return EXCHANGE_COUNTRIES[self.exchange]

    def as_dict(self) -> dict:
        return {**asdict(self), "country": self.country}

