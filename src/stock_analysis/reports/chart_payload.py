"""Validated chart data passed from report research to the HTML template."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal


@dataclass(frozen=True)
class PriceLevel:
    price: float
    label: str
    color: str


@dataclass(frozen=True)
class ChartNote:
    label: str
    text: str


@dataclass
class ChartPayload:
    """Serializable data contract for the full-width Lightweight Charts view.

    `candles` uses Lightweight Charts' ``{time, open, high, low, close}``
    format. Values must be chronological ISO dates and raw prices. Volume bars
    must carry an explicit green/red color determined by the candle direction.
    """

    candles: list[dict]
    volume: list[dict]
    indicators: list[dict] = field(default_factory=list)
    levels: list[PriceLevel] = field(default_factory=list)
    markers: list[dict] = field(default_factory=list)
    rsi: list[dict] = field(default_factory=list)
    notes: list[ChartNote] = field(default_factory=list)

    def as_template_data(self) -> dict:
        """Return JSON-ready data after enforcing a readable annotation budget."""
        if len(self.markers) > 8:
            raise ValueError("Use at most eight chart markers to prevent clutter.")
        if len(self.levels) > 7:
            raise ValueError("Use at most seven decision-relevant price levels.")
        if not self.candles:
            raise ValueError("Candlestick data is required for every report chart.")
        return {
            "candles": self.candles,
            "volume": self.volume,
            "indicators": self.indicators,
            "levels": [asdict(level) for level in self.levels],
            "markers": self.markers,
            "rsi": self.rsi,
            "notes": [asdict(note) for note in self.notes],
        }
