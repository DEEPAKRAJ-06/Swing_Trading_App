from __future__ import annotations

from statistics import mean, pstdev


def sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return mean(values[-period:])


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    output = mean(values[:period])
    for value in values[period:]:
        output = value * alpha + output * (1 - alpha)
    return output


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for idx in range(-period, 0):
        change = values[idx] - values[idx - 1]
        if change >= 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    avg_gain = mean(gains)
    avg_loss = mean(losses)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def bollinger(values: list[float], period: int = 20, deviations: float = 2.0) -> dict | None:
    if len(values) < period:
        return None
    window = values[-period:]
    middle = mean(window)
    sigma = pstdev(window)
    return {
        "middle": middle,
        "upper": middle + deviations * sigma,
        "lower": middle - deviations * sigma,
        "width_pct": ((deviations * sigma * 2) / middle * 100) if middle else 0,
    }


def adx(candles: list[dict], period: int = 14) -> float | None:
    if len(candles) < period * 2 + 1:
        return None
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    true_ranges: list[float] = []
    for idx in range(1, len(candles)):
        current = candles[idx]
        previous = candles[idx - 1]
        up_move = current["high"] - previous["high"]
        down_move = previous["low"] - current["low"]
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0)
        true_ranges.append(
            max(
                current["high"] - current["low"],
                abs(current["high"] - previous["close"]),
                abs(current["low"] - previous["close"]),
            )
        )
    dx_values: list[float] = []
    for idx in range(period, len(true_ranges) + 1):
        tr_sum = sum(true_ranges[idx - period : idx])
        if tr_sum == 0:
            continue
        plus_di = 100 * sum(plus_dm[idx - period : idx]) / tr_sum
        minus_di = 100 * sum(minus_dm[idx - period : idx]) / tr_sum
        total = plus_di + minus_di
        if total:
            dx_values.append(abs(plus_di - minus_di) / total * 100)
    if len(dx_values) < period:
        return None
    return mean(dx_values[-period:])


def rolling_high(values: list[float], period: int, exclude_latest: bool = False) -> float | None:
    source = values[:-1] if exclude_latest else values
    if len(source) < period:
        return None
    return max(source[-period:])


def rolling_low(values: list[float], period: int, exclude_latest: bool = False) -> float | None:
    source = values[:-1] if exclude_latest else values
    if len(source) < period:
        return None
    return min(source[-period:])


def pct_change(values: list[float], period: int) -> float | None:
    if len(values) <= period or values[-period - 1] == 0:
        return None
    return (values[-1] / values[-period - 1] - 1) * 100


def atr(candles: list[dict], period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None
    ranges: list[float] = []
    recent = candles[-period:]
    previous_close = candles[-period - 1]["close"]
    for candle in recent:
        high = candle["high"]
        low = candle["low"]
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        previous_close = candle["close"]
    return mean(ranges)


def zscore(value: float, values: list[float]) -> float:
    if not values:
        return 0
    sigma = pstdev(values)
    if sigma == 0:
        return 0
    return (value - mean(values)) / sigma


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
