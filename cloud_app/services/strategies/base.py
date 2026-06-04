from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class SignalCandidate:
    strategy_key: str
    symbol: str
    direction: str
    entry_low: float
    entry_high: float
    stop_loss: float
    target_price: float
    expected_holding_days: int
    confidence_score: float
    reason_summary: str
    factor_breakdown: dict
    invalidation: dict
    ranking_explanation: str

    @property
    def risk_reward_ratio(self) -> float:
        entry = (self.entry_low + self.entry_high) / 2
        risk = max(entry - self.stop_loss, 0.01)
        reward = max(self.target_price - entry, 0.01)
        return round(reward / risk, 2)


class Strategy(Protocol):
    key: str
    name: str
    description: str
    family: str
    default_parameters: dict
    risk_config: dict

    def evaluate(self, symbol: dict, candles: list[dict], benchmark: list[dict] | None = None) -> SignalCandidate | None:
        ...
