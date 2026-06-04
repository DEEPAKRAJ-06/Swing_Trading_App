from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderCandle:
    symbol: str
    provider_symbol: str
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float
    volume: int
    source: str
    synthetic: bool
    metadata: dict

    @property
    def turnover(self) -> float:
        return round(self.close * self.volume, 2)


class MarketDataProvider:
    name = "base"
    data_mode = "demo"

    def fetch_daily(self, symbols: list[str], lookback_days: int = 260) -> list[ProviderCandle]:
        raise NotImplementedError
