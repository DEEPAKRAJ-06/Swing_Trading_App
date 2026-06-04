from __future__ import annotations

from cloud_app.services.indicators import adx, atr, bollinger, clamp, pct_change, rolling_high, rolling_low, rsi, sma
from cloud_app.services.strategies.base import SignalCandidate


def _liquid(latest: dict, avg_volume: float, min_turnover: float = 50_000_000) -> bool:
    return avg_volume > 250_000 and latest["turnover"] >= min_turnover


def _risk_box(entry: float, stop: float, target: float) -> bool:
    return stop > 0 and stop < entry < target and (target - entry) / max(entry - stop, 0.01) >= 1.15


class TrendContinuationStrategy:
    key = "trend_continuation_ma"
    name = "Trend Continuation MA"
    description = "Long setup when price trends above rising moving averages with improving momentum and liquidity."
    family = "trend_continuation"
    default_parameters = {"fast_ma": 20, "slow_ma": 50, "min_momentum_20d": 4.0, "min_score": 72}
    risk_config = {"target_atr_multiple": 2.8, "stop_atr_multiple": 1.4, "max_holding_days": 18}

    def evaluate(self, symbol: dict, candles: list[dict], benchmark: list[dict] | None = None) -> SignalCandidate | None:
        if len(candles) < 70:
            return None
        closes = [c["close"] for c in candles]
        volumes = [c["volume"] for c in candles]
        latest = candles[-1]
        ma20 = sma(closes, 20)
        ma50 = sma(closes, 50)
        ma50_prev = sma(closes[:-5], 50)
        avg_volume = sma(volumes, 20) or 0
        momentum = pct_change(closes, 20) or 0
        volatility = atr(candles, 14) or latest["close"] * 0.025
        if not ma20 or not ma50 or not ma50_prev:
            return None
        trend_ok = latest["close"] > ma20 > ma50 and ma50 > ma50_prev
        liquidity_ok = avg_volume > 250_000 and latest["turnover"] > 50_000_000
        momentum_ok = momentum >= self.default_parameters["min_momentum_20d"]
        if not (trend_ok and liquidity_ok and momentum_ok):
            return None
        trend_score = clamp(((latest["close"] / ma50) - 1) * 180, 0, 28)
        momentum_score = clamp(momentum * 2.4, 0, 28)
        volume_score = clamp((latest["volume"] / avg_volume - 1) * 24, 0, 18)
        rr_score = 18
        score = round(38 + trend_score + momentum_score + volume_score + rr_score, 1)
        if score < self.default_parameters["min_score"]:
            return None
        entry = latest["close"]
        stop = max(ma20 - 0.35 * volatility, entry - self.risk_config["stop_atr_multiple"] * volatility)
        target = entry + self.risk_config["target_atr_multiple"] * volatility
        return SignalCandidate(
            strategy_key=self.key,
            symbol=symbol["symbol"],
            direction="long",
            entry_low=round(entry * 0.995, 2),
            entry_high=round(entry * 1.01, 2),
            stop_loss=round(stop, 2),
            target_price=round(target, 2),
            expected_holding_days=12,
            confidence_score=min(score, 96),
            reason_summary="Price is above rising 20/50 day moving averages with positive 20-day momentum.",
            factor_breakdown={
                "trend_strength": round(trend_score, 1),
                "momentum_20d_pct": round(momentum, 2),
                "volume_vs_20d_avg": round(latest["volume"] / avg_volume, 2),
                "liquidity_turnover": round(latest["turnover"], 2),
            },
            invalidation={"close_below": round(stop, 2), "condition": "Daily close below stop or 20DMA failure"},
            ranking_explanation="Ranked well because trend alignment, liquidity, and recent momentum all confirmed together.",
        )


class BreakoutVolumeStrategy:
    key = "breakout_volume"
    name = "Breakout With Volume"
    description = "Long setup when price breaks a recent range high with volume confirmation."
    family = "breakout"
    default_parameters = {"lookback_days": 30, "min_volume_multiple": 1.35, "min_score": 74}
    risk_config = {"target_atr_multiple": 3.0, "stop_atr_multiple": 1.2, "max_holding_days": 15}

    def evaluate(self, symbol: dict, candles: list[dict], benchmark: list[dict] | None = None) -> SignalCandidate | None:
        if len(candles) < 45:
            return None
        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        volumes = [c["volume"] for c in candles]
        latest = candles[-1]
        prior_high = rolling_high(highs, self.default_parameters["lookback_days"], exclude_latest=True)
        avg_volume = sma(volumes[:-1], 20) or 0
        volatility = atr(candles, 14) or latest["close"] * 0.025
        if not prior_high or not avg_volume:
            return None
        breakout_pct = (latest["close"] / prior_high - 1) * 100
        volume_multiple = latest["volume"] / avg_volume
        ma50 = sma(closes, 50) or sma(closes, 30)
        if latest["close"] <= prior_high or volume_multiple < self.default_parameters["min_volume_multiple"]:
            return None
        if ma50 and latest["close"] < ma50:
            return None
        breakout_score = clamp(breakout_pct * 12, 0, 24)
        volume_score = clamp((volume_multiple - 1) * 32, 0, 30)
        liquidity_score = 12 if latest["turnover"] > 60_000_000 else 5
        score = round(42 + breakout_score + volume_score + liquidity_score, 1)
        if score < self.default_parameters["min_score"]:
            return None
        entry = latest["close"]
        stop = max(prior_high - 0.75 * volatility, entry - self.risk_config["stop_atr_multiple"] * volatility)
        target = entry + self.risk_config["target_atr_multiple"] * volatility
        return SignalCandidate(
            strategy_key=self.key,
            symbol=symbol["symbol"],
            direction="long",
            entry_low=round(prior_high * 0.998, 2),
            entry_high=round(entry * 1.012, 2),
            stop_loss=round(stop, 2),
            target_price=round(target, 2),
            expected_holding_days=10,
            confidence_score=min(score, 97),
            reason_summary="The stock closed above its recent range high with materially higher volume.",
            factor_breakdown={
                "breakout_above_30d_high_pct": round(breakout_pct, 2),
                "volume_multiple": round(volume_multiple, 2),
                "prior_range_high": round(prior_high, 2),
                "turnover": round(latest["turnover"], 2),
            },
            invalidation={"close_below": round(stop, 2), "condition": "Breakout fails back below support or stop"},
            ranking_explanation="Ranked highly because price expansion and volume expansion appeared on the same day.",
        )


class PullbackUptrendStrategy:
    key = "pullback_uptrend"
    name = "Pullback In Uptrend"
    description = "Long setup when a liquid uptrend pulls back near the 20DMA and starts to recover."
    family = "trend_pullback"
    default_parameters = {"fast_ma": 20, "slow_ma": 50, "min_score": 70}
    risk_config = {"target_atr_multiple": 2.4, "stop_atr_multiple": 1.25, "max_holding_days": 14}

    def evaluate(self, symbol: dict, candles: list[dict], benchmark: list[dict] | None = None) -> SignalCandidate | None:
        if len(candles) < 70:
            return None
        closes = [c["close"] for c in candles]
        lows = [c["low"] for c in candles]
        volumes = [c["volume"] for c in candles]
        latest = candles[-1]
        ma20 = sma(closes, 20)
        ma50 = sma(closes, 50)
        recent_low = rolling_low(lows, 5)
        avg_volume = sma(volumes, 20) or 0
        volatility = atr(candles, 14) or latest["close"] * 0.025
        if not ma20 or not ma50 or not recent_low:
            return None
        pullback_depth = (ma20 / recent_low - 1) * 100
        recovery = latest["close"] > candles[-2]["high"]
        if not (latest["close"] > ma50 and ma20 > ma50 and 0 <= pullback_depth <= 6 and recovery):
            return None
        liquidity_ok = avg_volume > 250_000 and latest["turnover"] > 40_000_000
        if not liquidity_ok:
            return None
        score = round(44 + clamp((latest["close"] / ma50 - 1) * 150, 0, 22) + clamp((6 - pullback_depth) * 3, 0, 18) + 10, 1)
        if score < self.default_parameters["min_score"]:
            return None
        entry = latest["close"]
        stop = min(recent_low, entry - self.risk_config["stop_atr_multiple"] * volatility)
        target = entry + self.risk_config["target_atr_multiple"] * volatility
        return SignalCandidate(
            strategy_key=self.key,
            symbol=symbol["symbol"],
            direction="long",
            entry_low=round(entry * 0.992, 2),
            entry_high=round(entry * 1.008, 2),
            stop_loss=round(stop, 2),
            target_price=round(target, 2),
            expected_holding_days=9,
            confidence_score=min(score, 92),
            reason_summary=(
                f"Uptrend pullback: price recovered above the prior day's high after a {round(pullback_depth, 1)}% "
                f"dip near the 20DMA, with the 20DMA still above the 50DMA."
            ),
            factor_breakdown={
                "pullback_depth_pct": round(pullback_depth, 2),
                "recovery_close": latest["close"],
                "ma20": round(ma20, 2),
                "ma50": round(ma50, 2),
            },
            invalidation={"close_below": round(stop, 2), "condition": "Pullback loses recent swing low or stop"},
            ranking_explanation="Ranked well because the setup offers controlled risk inside an existing uptrend.",
        )


class RelativeStrengthTrendStrategy:
    key = "relative_strength_trend"
    name = "Relative Strength Trend"
    description = "Long setup when a liquid stock is near multi-month highs with strong 3- and 6-month momentum."
    family = "relative_strength"
    default_parameters = {"min_momentum_63d": 8.0, "min_momentum_126d": 12.0, "min_score": 76}
    risk_config = {"target_atr_multiple": 3.0, "stop_atr_multiple": 1.35, "max_holding_days": 18}

    def evaluate(self, symbol: dict, candles: list[dict], benchmark: list[dict] | None = None) -> SignalCandidate | None:
        if len(candles) < 150:
            return None
        closes = [c["close"] for c in candles]
        volumes = [c["volume"] for c in candles]
        latest = candles[-1]
        ma20 = sma(closes, 20)
        ma50 = sma(closes, 50)
        ma50_prev = sma(closes[:-10], 50)
        high_63 = rolling_high(closes, 63)
        avg_volume = sma(volumes, 20) or 0
        momentum_63 = pct_change(closes, 63) or 0
        momentum_126 = pct_change(closes, 126) or 0
        volatility = atr(candles, 14) or latest["close"] * 0.025
        if not ma20 or not ma50 or not ma50_prev or not high_63:
            return None
        near_high = latest["close"] >= high_63 * 0.92
        if not (
            latest["close"] > ma20 > ma50
            and ma50 > ma50_prev
            and near_high
            and momentum_63 >= self.default_parameters["min_momentum_63d"]
            and momentum_126 >= self.default_parameters["min_momentum_126d"]
            and _liquid(latest, avg_volume)
        ):
            return None
        high_score = clamp((latest["close"] / high_63) * 24, 14, 24)
        momentum_score = clamp(momentum_63 * 1.4 + momentum_126 * 0.65, 0, 34)
        volume_score = clamp((latest["volume"] / avg_volume - 0.8) * 20, 0, 14)
        score = round(38 + high_score + momentum_score + volume_score, 1)
        if score < self.default_parameters["min_score"]:
            return None
        entry = latest["close"]
        stop = max(ma20 - 0.4 * volatility, entry - self.risk_config["stop_atr_multiple"] * volatility)
        target = entry + self.risk_config["target_atr_multiple"] * volatility
        if not _risk_box(entry, stop, target):
            return None
        return SignalCandidate(
            strategy_key=self.key,
            symbol=symbol["symbol"],
            direction="long",
            entry_low=round(entry * 0.995, 2),
            entry_high=round(entry * 1.01, 2),
            stop_loss=round(stop, 2),
            target_price=round(target, 2),
            expected_holding_days=14,
            confidence_score=min(score, 96),
            reason_summary=(
                f"Relative-strength trend: price is near its 63-day high with {round(momentum_63, 1)}% "
                f"3-month momentum and {round(momentum_126, 1)}% 6-month momentum."
            ),
            factor_breakdown={
                "momentum_63d_pct": round(momentum_63, 2),
                "momentum_126d_pct": round(momentum_126, 2),
                "distance_from_63d_high_pct": round((latest["close"] / high_63 - 1) * 100, 2),
                "volume_vs_20d_avg": round(latest["volume"] / avg_volume, 2),
                "ma20": round(ma20, 2),
                "ma50": round(ma50, 2),
            },
            invalidation={"close_below": round(stop, 2), "condition": "Exit if price loses the 20DMA support area or stop."},
            ranking_explanation="Ranked well because trend, multi-month momentum, liquidity, and proximity to highs aligned.",
        )


class VolatilityContractionBreakoutStrategy:
    key = "volatility_contraction_breakout"
    name = "Volatility Contraction Breakout"
    description = "Long setup when a tightening range breaks upward with volume while the medium-term trend is rising."
    family = "breakout"
    default_parameters = {"min_volume_multiple": 1.25, "max_recent_range_pct": 9.0, "min_score": 78}
    risk_config = {"target_atr_multiple": 3.2, "stop_atr_multiple": 1.2, "max_holding_days": 16}

    def evaluate(self, symbol: dict, candles: list[dict], benchmark: list[dict] | None = None) -> SignalCandidate | None:
        if len(candles) < 100:
            return None
        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        volumes = [c["volume"] for c in candles]
        latest = candles[-1]
        prior_20_high = rolling_high(highs, 20, exclude_latest=True)
        recent_10_high = rolling_high(highs, 10)
        recent_10_low = rolling_low(lows, 10)
        prior_40_high = rolling_high(highs[:-10], 40)
        prior_40_low = rolling_low(lows[:-10], 40)
        ma50 = sma(closes, 50)
        ma50_prev = sma(closes[:-10], 50)
        avg_volume = sma(volumes[:-1], 20) or 0
        volatility = atr(candles, 14) or latest["close"] * 0.025
        if not all([prior_20_high, recent_10_high, recent_10_low, prior_40_high, prior_40_low, ma50, ma50_prev, avg_volume]):
            return None
        recent_range_pct = (recent_10_high / recent_10_low - 1) * 100
        prior_range_pct = (prior_40_high / prior_40_low - 1) * 100
        volume_multiple = latest["volume"] / avg_volume
        contraction_ok = recent_range_pct <= min(self.default_parameters["max_recent_range_pct"], prior_range_pct * 0.72)
        breakout_ok = latest["close"] > prior_20_high and volume_multiple >= self.default_parameters["min_volume_multiple"]
        if not (contraction_ok and breakout_ok and latest["close"] > ma50 and ma50 > ma50_prev and _liquid(latest, avg_volume, 60_000_000)):
            return None
        score = round(
            42
            + clamp((prior_range_pct - recent_range_pct) * 1.8, 0, 22)
            + clamp((volume_multiple - 1) * 28, 0, 22)
            + clamp((latest["close"] / prior_20_high - 1) * 180, 0, 14),
            1,
        )
        if score < self.default_parameters["min_score"]:
            return None
        entry = latest["close"]
        stop = max(recent_10_low, entry - self.risk_config["stop_atr_multiple"] * volatility)
        target = entry + self.risk_config["target_atr_multiple"] * volatility
        if not _risk_box(entry, stop, target):
            return None
        return SignalCandidate(
            strategy_key=self.key,
            symbol=symbol["symbol"],
            direction="long",
            entry_low=round(prior_20_high * 0.997, 2),
            entry_high=round(entry * 1.012, 2),
            stop_loss=round(stop, 2),
            target_price=round(target, 2),
            expected_holding_days=12,
            confidence_score=min(score, 97),
            reason_summary=(
                f"Contraction breakout: the recent 10-day range tightened to {round(recent_range_pct, 1)}% "
                f"and price broke the 20-day range high on {round(volume_multiple, 2)}x volume."
            ),
            factor_breakdown={
                "recent_10d_range_pct": round(recent_range_pct, 2),
                "prior_40d_range_pct": round(prior_range_pct, 2),
                "volume_multiple": round(volume_multiple, 2),
                "breakout_level": round(prior_20_high, 2),
                "ma50": round(ma50, 2),
            },
            invalidation={"close_below": round(stop, 2), "condition": "Breakout failed if price closes back inside the tight base or hits stop."},
            ranking_explanation="Ranked well because volatility contracted before an upside break with volume expansion.",
        )


class BollingerSqueezeMomentumStrategy:
    key = "bollinger_squeeze_momentum"
    name = "Bollinger Squeeze Momentum"
    description = "Long setup when a low-volatility squeeze releases upward with trend and volume support."
    family = "volatility_expansion"
    default_parameters = {"min_volume_multiple": 1.15, "min_score": 76}
    risk_config = {"target_atr_multiple": 2.8, "stop_atr_multiple": 1.25, "max_holding_days": 12}

    def evaluate(self, symbol: dict, candles: list[dict], benchmark: list[dict] | None = None) -> SignalCandidate | None:
        if len(candles) < 120:
            return None
        closes = [c["close"] for c in candles]
        volumes = [c["volume"] for c in candles]
        latest = candles[-1]
        band = bollinger(closes, 20)
        prior_band = bollinger(closes[:-1], 20)
        widths = []
        for end_idx in range(max(20, len(closes) - 90), len(closes) + 1):
            prior = bollinger(closes[:end_idx], 20)
            if prior:
                widths.append(prior["width_pct"])
        ma50 = sma(closes, 50)
        avg_volume = sma(volumes[:-1], 20) or 0
        momentum_20 = pct_change(closes, 20) or 0
        volatility = atr(candles, 14) or latest["close"] * 0.025
        if not band or not prior_band or not ma50 or not widths or not avg_volume:
            return None
        squeeze_threshold = sorted(widths)[max(0, int(len(widths) * 0.25) - 1)]
        volume_multiple = latest["volume"] / avg_volume
        release_ok = prior_band["width_pct"] <= squeeze_threshold and latest["close"] > band["upper"]
        if not (
            release_ok
            and latest["close"] > ma50
            and momentum_20 > 2
            and volume_multiple >= self.default_parameters["min_volume_multiple"]
            and _liquid(latest, avg_volume)
        ):
            return None
        score = round(
            44
            + clamp((squeeze_threshold - prior_band["width_pct"]) * 2.5, 0, 18)
            + clamp((latest["close"] / band["upper"] - 1) * 220, 0, 16)
            + clamp(momentum_20 * 1.4, 0, 18)
            + clamp((volume_multiple - 1) * 20, 0, 12),
            1,
        )
        if score < self.default_parameters["min_score"]:
            return None
        entry = latest["close"]
        stop = max(band["middle"] - 0.2 * volatility, entry - self.risk_config["stop_atr_multiple"] * volatility)
        target = entry + self.risk_config["target_atr_multiple"] * volatility
        if not _risk_box(entry, stop, target):
            return None
        return SignalCandidate(
            strategy_key=self.key,
            symbol=symbol["symbol"],
            direction="long",
            entry_low=round(entry * 0.994, 2),
            entry_high=round(entry * 1.01, 2),
            stop_loss=round(stop, 2),
            target_price=round(target, 2),
            expected_holding_days=10,
            confidence_score=min(score, 95),
            reason_summary=(
                f"Bollinger squeeze release: volatility was in its lower quartile and price closed above the upper band "
                f"with {round(momentum_20, 1)}% 20-day momentum."
            ),
            factor_breakdown={
                "current_band_width_pct": round(band["width_pct"], 2),
                "prior_band_width_pct": round(prior_band["width_pct"], 2),
                "squeeze_threshold_pct": round(squeeze_threshold, 2),
                "momentum_20d_pct": round(momentum_20, 2),
                "volume_multiple": round(volume_multiple, 2),
            },
            invalidation={"close_below": round(stop, 2), "condition": "Squeeze release failed if price loses the middle band or stop."},
            ranking_explanation="Ranked well because a low-volatility base released upward with trend and momentum support.",
        )


class BullRangeRsiPullbackStrategy:
    key = "bull_range_rsi_pullback"
    name = "Bull Range RSI Pullback"
    description = "Long setup when an uptrend holds RSI in a bull range and turns up from a controlled pullback."
    family = "mean_reversion_trend"
    default_parameters = {"min_adx": 18.0, "min_score": 74}
    risk_config = {"target_atr_multiple": 2.3, "stop_atr_multiple": 1.15, "max_holding_days": 10}

    def evaluate(self, symbol: dict, candles: list[dict], benchmark: list[dict] | None = None) -> SignalCandidate | None:
        if len(candles) < 90:
            return None
        closes = [c["close"] for c in candles]
        lows = [c["low"] for c in candles]
        volumes = [c["volume"] for c in candles]
        latest = candles[-1]
        ma20 = sma(closes, 20)
        ma50 = sma(closes, 50)
        avg_volume = sma(volumes, 20) or 0
        rsi_14 = rsi(closes, 14)
        adx_14 = adx(candles[-45:], 14)
        recent_low = rolling_low(lows, 7)
        volatility = atr(candles, 14) or latest["close"] * 0.025
        if not ma20 or not ma50 or not rsi_14 or not adx_14 or not recent_low:
            return None
        pullback_to_ma = recent_low <= ma20 * 1.025 and latest["close"] > ma20
        turn_up = latest["close"] > candles[-2]["close"] and latest["close"] > candles[-2]["high"]
        if not (
            latest["close"] > ma50
            and ma20 > ma50
            and 45 <= rsi_14 <= 68
            and adx_14 >= self.default_parameters["min_adx"]
            and pullback_to_ma
            and turn_up
            and _liquid(latest, avg_volume, 40_000_000)
        ):
            return None
        score = round(
            40
            + clamp((adx_14 - 16) * 1.2, 0, 18)
            + clamp((68 - abs(56 - rsi_14)) * 0.28, 0, 18)
            + clamp((latest["close"] / ma50 - 1) * 120, 0, 18)
            + clamp((latest["volume"] / avg_volume - 0.8) * 15, 0, 10),
            1,
        )
        if score < self.default_parameters["min_score"]:
            return None
        entry = latest["close"]
        stop = min(recent_low, entry - self.risk_config["stop_atr_multiple"] * volatility)
        target = entry + self.risk_config["target_atr_multiple"] * volatility
        if not _risk_box(entry, stop, target):
            return None
        return SignalCandidate(
            strategy_key=self.key,
            symbol=symbol["symbol"],
            direction="long",
            entry_low=round(entry * 0.992, 2),
            entry_high=round(entry * 1.008, 2),
            stop_loss=round(stop, 2),
            target_price=round(target, 2),
            expected_holding_days=8,
            confidence_score=min(score, 94),
            reason_summary=(
                f"Bull-range pullback: RSI is {round(rsi_14, 1)}, ADX is {round(adx_14, 1)}, "
                "and price turned up after holding near the 20DMA."
            ),
            factor_breakdown={
                "rsi_14": round(rsi_14, 2),
                "adx_14": round(adx_14, 2),
                "ma20": round(ma20, 2),
                "ma50": round(ma50, 2),
                "recent_low": round(recent_low, 2),
                "volume_vs_20d_avg": round(latest["volume"] / avg_volume, 2),
            },
            invalidation={"close_below": round(stop, 2), "condition": "Pullback thesis failed if price breaks the recent swing low or stop."},
            ranking_explanation="Ranked well because a measured pullback turned up while trend-strength indicators stayed constructive.",
        )


class SectorLeaderBreakoutStrategy:
    key = "sector_leader_breakout"
    name = "Sector Leader Breakout"
    description = "Long setup when a liquid leadership stock breaks to multi-month highs with strong momentum and volume support."
    family = "leadership_breakout"
    default_parameters = {"min_momentum_63d": 10.0, "min_momentum_126d": 16.0, "min_volume_multiple": 1.1, "min_score": 80}
    risk_config = {"target_atr_multiple": 3.1, "stop_atr_multiple": 1.35, "max_holding_days": 16}

    def evaluate(self, symbol: dict, candles: list[dict], benchmark: list[dict] | None = None) -> SignalCandidate | None:
        if len(candles) < 150:
            return None
        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        volumes = [c["volume"] for c in candles]
        latest = candles[-1]
        ma20 = sma(closes, 20)
        ma50 = sma(closes, 50)
        ma50_prev = sma(closes[:-10], 50)
        high_55 = rolling_high(highs, 55, exclude_latest=True)
        high_126 = rolling_high(highs, 126)
        avg_volume = sma(volumes[:-1], 20) or 0
        momentum_63 = pct_change(closes, 63) or 0
        momentum_126 = pct_change(closes, 126) or 0
        volatility = atr(candles, 14) or latest["close"] * 0.025
        if not all([ma20, ma50, ma50_prev, high_55, high_126, avg_volume]):
            return None
        volume_multiple = latest["volume"] / avg_volume
        breakout_ok = latest["close"] > high_55 * 1.002 and latest["close"] >= high_126 * 0.94
        trend_ok = latest["close"] > ma20 > ma50 and ma50 > ma50_prev
        momentum_ok = momentum_63 >= self.default_parameters["min_momentum_63d"] and momentum_126 >= self.default_parameters["min_momentum_126d"]
        if not (
            breakout_ok
            and trend_ok
            and momentum_ok
            and volume_multiple >= self.default_parameters["min_volume_multiple"]
            and _liquid(latest, avg_volume, 70_000_000)
        ):
            return None
        score = round(
            40
            + clamp((latest["close"] / high_55 - 1) * 220, 0, 16)
            + clamp(momentum_63 * 1.1 + momentum_126 * 0.55, 0, 34)
            + clamp((volume_multiple - 1) * 24, 0, 16)
            + clamp((latest["close"] / ma50 - 1) * 90, 0, 12),
            1,
        )
        if score < self.default_parameters["min_score"]:
            return None
        entry = latest["close"]
        stop = max(ma20 - 0.35 * volatility, high_55 - 0.85 * volatility, entry - self.risk_config["stop_atr_multiple"] * volatility)
        target = entry + self.risk_config["target_atr_multiple"] * volatility
        if not _risk_box(entry, stop, target):
            return None
        return SignalCandidate(
            strategy_key=self.key,
            symbol=symbol["symbol"],
            direction="long",
            entry_low=round(high_55 * 0.998, 2),
            entry_high=round(entry * 1.012, 2),
            stop_loss=round(stop, 2),
            target_price=round(target, 2),
            expected_holding_days=12,
            confidence_score=min(score, 98),
            reason_summary=(
                f"Leadership breakout: price cleared a 55-day high with {round(momentum_63, 1)}% "
                f"3-month momentum and {round(volume_multiple, 2)}x volume."
            ),
            factor_breakdown={
                "breakout_level": round(high_55, 2),
                "momentum_63d_pct": round(momentum_63, 2),
                "momentum_126d_pct": round(momentum_126, 2),
                "volume_multiple": round(volume_multiple, 2),
                "distance_from_126d_high_pct": round((latest["close"] / high_126 - 1) * 100, 2),
                "ma20": round(ma20, 2),
                "ma50": round(ma50, 2),
            },
            invalidation={"close_below": round(stop, 2), "condition": "Breakout thesis failed if price closes back below support or stop."},
            ranking_explanation="Ranked well because price leadership, multi-month momentum, liquidity, and breakout volume aligned.",
        )


class BreakoutRetestStrategy:
    key = "breakout_retest"
    name = "Breakout Retest"
    description = "Long setup when a recent breakout holds its breakout level and turns up after a retest."
    family = "breakout_retest"
    default_parameters = {"breakout_lookback": 40, "retest_window": 12, "min_score": 76}
    risk_config = {"target_atr_multiple": 2.8, "stop_atr_multiple": 1.45, "max_holding_days": 12}

    def evaluate(self, symbol: dict, candles: list[dict], benchmark: list[dict] | None = None) -> SignalCandidate | None:
        if len(candles) < 120:
            return None
        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        volumes = [c["volume"] for c in candles]
        latest = candles[-1]
        ma20 = sma(closes, 20)
        ma50 = sma(closes, 50)
        ma50_prev = sma(closes[:-10], 50)
        avg_volume = sma(volumes, 20) or 0
        volatility = atr(candles, 14) or latest["close"] * 0.025
        if not all([ma20, ma50, ma50_prev, avg_volume]):
            return None

        breakout_idx = None
        breakout_level = None
        start_idx = max(self.default_parameters["breakout_lookback"], len(candles) - self.default_parameters["retest_window"] - 2)
        for idx in range(start_idx, len(candles) - 2):
            level = max(highs[idx - self.default_parameters["breakout_lookback"] : idx])
            local_avg_volume = sma(volumes[:idx], 20) or avg_volume
            if closes[idx] > level * 1.004 and volumes[idx] >= local_avg_volume * 1.1:
                breakout_idx = idx
                breakout_level = level
        if breakout_idx is None or breakout_level is None:
            return None

        days_since = len(candles) - 1 - breakout_idx
        retest_lows = lows[breakout_idx + 1 :]
        retest_low = min(retest_lows) if retest_lows else latest["low"]
        held_level = retest_low >= breakout_level * 0.965 and latest["close"] >= breakout_level * 0.995
        not_extended = latest["close"] <= breakout_level * 1.06
        turn_up = latest["close"] > candles[-2]["high"] or (latest["close"] > candles[-2]["close"] and latest["close"] > ma20)
        if not (
            2 <= days_since <= self.default_parameters["retest_window"]
            and held_level
            and not_extended
            and turn_up
            and latest["close"] > ma50
            and ma50 > ma50_prev
            and _liquid(latest, avg_volume, 50_000_000)
        ):
            return None
        score = round(
            42
            + clamp((breakout_level / retest_low - 1) * 140, 0, 18)
            + clamp((latest["close"] / breakout_level - 1) * 180, 0, 18)
            + clamp((latest["close"] / ma50 - 1) * 110, 0, 18)
            + clamp((latest["volume"] / avg_volume - 0.8) * 18, 0, 10),
            1,
        )
        if score < self.default_parameters["min_score"]:
            return None
        entry = latest["close"]
        stop = max(min(retest_low, breakout_level * 0.99), entry - self.risk_config["stop_atr_multiple"] * volatility)
        target = entry + self.risk_config["target_atr_multiple"] * volatility
        if not _risk_box(entry, stop, target):
            return None
        return SignalCandidate(
            strategy_key=self.key,
            symbol=symbol["symbol"],
            direction="long",
            entry_low=round(breakout_level * 0.995, 2),
            entry_high=round(entry * 1.008, 2),
            stop_loss=round(stop, 2),
            target_price=round(target, 2),
            expected_holding_days=9,
            confidence_score=min(score, 95),
            reason_summary=(
                f"Breakout retest: price broke out {days_since} sessions ago, held the breakout area, "
                "and turned up again without becoming extended."
            ),
            factor_breakdown={
                "breakout_level": round(breakout_level, 2),
                "days_since_breakout": days_since,
                "retest_low": round(retest_low, 2),
                "distance_above_breakout_pct": round((latest["close"] / breakout_level - 1) * 100, 2),
                "volume_vs_20d_avg": round(latest["volume"] / avg_volume, 2),
                "ma20": round(ma20, 2),
                "ma50": round(ma50, 2),
            },
            invalidation={"close_below": round(stop, 2), "condition": "Retest failed if price loses the breakout support area or stop."},
            ranking_explanation="Ranked well because the breakout level held and price restarted upward from a lower-risk retest zone.",
        )


class VolumeAccumulationTrendStrategy:
    key = "volume_accumulation_trend"
    name = "Volume Accumulation Trend"
    description = "Long setup when an uptrend shows net accumulation before price turns up from a tight range."
    family = "volume_accumulation"
    default_parameters = {"min_accumulation_ratio": 1.15, "max_tight_range_pct": 10.0, "min_score": 75}
    risk_config = {"target_atr_multiple": 2.6, "stop_atr_multiple": 1.25, "max_holding_days": 11}

    def evaluate(self, symbol: dict, candles: list[dict], benchmark: list[dict] | None = None) -> SignalCandidate | None:
        if len(candles) < 120:
            return None
        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        volumes = [c["volume"] for c in candles]
        latest = candles[-1]
        ma20 = sma(closes, 20)
        ma50 = sma(closes, 50)
        ma50_prev = sma(closes[:-10], 50)
        high_15 = rolling_high(highs, 15)
        low_15 = rolling_low(lows, 15)
        avg_volume = sma(volumes, 20) or 0
        volatility = atr(candles, 14) or latest["close"] * 0.025
        if not all([ma20, ma50, ma50_prev, high_15, low_15, avg_volume]):
            return None

        up_volume = 0
        down_volume = 0
        obv = [0]
        for idx in range(1, len(candles)):
            if closes[idx] > closes[idx - 1]:
                up_volume += volumes[idx] if idx >= len(candles) - 20 else 0
                obv.append(obv[-1] + volumes[idx])
            elif closes[idx] < closes[idx - 1]:
                down_volume += volumes[idx] if idx >= len(candles) - 20 else 0
                obv.append(obv[-1] - volumes[idx])
            else:
                obv.append(obv[-1])
        accumulation_ratio = up_volume / max(down_volume, 1)
        obv_20_change = obv[-1] - obv[-21]
        obv_40_change = obv[-21] - obv[-41]
        tight_range_pct = (high_15 / low_15 - 1) * 100
        turn_up = latest["close"] > candles[-2]["high"] or (latest["close"] > candles[-2]["close"] and latest["close"] > ma20)
        if not (
            latest["close"] > ma20 > ma50
            and ma50 > ma50_prev
            and accumulation_ratio >= self.default_parameters["min_accumulation_ratio"]
            and obv_20_change > 0
            and obv_20_change > max(0, obv_40_change * 0.55)
            and tight_range_pct <= self.default_parameters["max_tight_range_pct"]
            and turn_up
            and _liquid(latest, avg_volume, 45_000_000)
        ):
            return None
        score = round(
            40
            + clamp((accumulation_ratio - 1) * 18, 0, 22)
            + clamp((self.default_parameters["max_tight_range_pct"] - tight_range_pct) * 2.0, 0, 18)
            + clamp((latest["close"] / ma50 - 1) * 100, 0, 18)
            + clamp((latest["volume"] / avg_volume - 0.8) * 14, 0, 10),
            1,
        )
        if score < self.default_parameters["min_score"]:
            return None
        entry = latest["close"]
        stop = max(ma20 - 0.35 * volatility, entry - self.risk_config["stop_atr_multiple"] * volatility)
        target = entry + self.risk_config["target_atr_multiple"] * volatility
        if not _risk_box(entry, stop, target):
            return None
        return SignalCandidate(
            strategy_key=self.key,
            symbol=symbol["symbol"],
            direction="long",
            entry_low=round(entry * 0.992, 2),
            entry_high=round(entry * 1.008, 2),
            stop_loss=round(stop, 2),
            target_price=round(target, 2),
            expected_holding_days=9,
            confidence_score=min(score, 94),
            reason_summary=(
                f"Accumulation trend: up-day volume beat down-day volume by {round(accumulation_ratio, 2)}x "
                f"while price tightened into a {round(tight_range_pct, 1)}% range and turned up."
            ),
            factor_breakdown={
                "accumulation_ratio_20d": round(accumulation_ratio, 2),
                "obv_20d_change": round(obv_20_change, 2),
                "tight_range_15d_pct": round(tight_range_pct, 2),
                "volume_vs_20d_avg": round(latest["volume"] / avg_volume, 2),
                "ma20": round(ma20, 2),
                "ma50": round(ma50, 2),
            },
            invalidation={"close_below": round(stop, 2), "condition": "Accumulation thesis failed if price loses the 20DMA support area or stop."},
            ranking_explanation="Ranked well because volume accumulation, a tight range, and trend alignment appeared together.",
        )


class BeginnerSwingChecklistStrategy:
    key = "beginner_swing_checklist"
    name = "Beginner Swing Checklist"
    description = "Daily long-only plan using trend, momentum, volume, liquidity, and ATR risk."
    family = "beginner_checklist"
    default_parameters = {"min_score": 62, "momentum_days": 20}
    risk_config = {"target_atr_multiple": 2.0, "stop_atr_multiple": 1.15, "max_holding_days": 12}

    def evaluate(self, symbol: dict, candles: list[dict], benchmark: list[dict] | None = None) -> SignalCandidate | None:
        if len(candles) < 70:
            return None
        closes = [c["close"] for c in candles]
        volumes = [c["volume"] for c in candles]
        latest = candles[-1]
        ma20 = sma(closes, 20)
        ma50 = sma(closes, 50)
        ma50_prev = sma(closes[:-5], 50)
        avg_volume = sma(volumes, 20) or 0
        momentum = pct_change(closes, self.default_parameters["momentum_days"]) or 0
        volatility = atr(candles, 14) or latest["close"] * 0.025
        if not ma20 or not ma50 or not ma50_prev or not avg_volume:
            return None

        trend_score = 0
        if latest["close"] > ma20:
            trend_score += 14
        if latest["close"] > ma50:
            trend_score += 14
        if ma20 >= ma50:
            trend_score += 12
        if ma50 >= ma50_prev:
            trend_score += 8

        momentum_score = clamp(momentum * 2.2, -16, 22)
        volume_multiple = latest["volume"] / avg_volume
        volume_score = clamp((volume_multiple - 0.8) * 20, 0, 16)
        liquidity_score = 10 if latest["turnover"] >= 40_000_000 else 0
        volatility_pct = volatility / latest["close"] * 100
        volatility_score = 8 if 1.0 <= volatility_pct <= 5.5 else 3
        score = round(34 + trend_score + momentum_score + volume_score + liquidity_score + volatility_score, 1)
        if score < self.default_parameters["min_score"]:
            return None

        entry = latest["close"]
        stop = min(entry - self.risk_config["stop_atr_multiple"] * volatility, ma20 - 0.25 * volatility)
        target = entry + self.risk_config["target_atr_multiple"] * volatility
        if stop <= 0 or target <= entry:
            return None
        reason_bits = []
        reason_bits.append("price is above the 50-day average" if latest["close"] > ma50 else "price is near the 50-day average")
        if ma20 >= ma50:
            reason_bits.append("the short-term trend is still above the medium-term trend")
        if momentum > 0:
            reason_bits.append(f"20-day momentum is positive at {round(momentum, 1)}%")
        if volume_multiple >= 1:
            reason_bits.append("volume is at or above its recent average")
        return SignalCandidate(
            strategy_key=self.key,
            symbol=symbol["symbol"],
            direction="long",
            entry_low=round(entry * 0.99, 2),
            entry_high=round(entry * 1.01, 2),
            stop_loss=round(stop, 2),
            target_price=round(target, 2),
            expected_holding_days=10,
            confidence_score=min(score, 90),
            reason_summary="This is a beginner swing plan because " + ", ".join(reason_bits) + ".",
            factor_breakdown={
                "current_close": round(latest["close"], 2),
                "ma20": round(ma20, 2),
                "ma50": round(ma50, 2),
                "momentum_20d_pct": round(momentum, 2),
                "volume_vs_20d_avg": round(volume_multiple, 2),
                "atr_14": round(volatility, 2),
                "atr_pct": round(volatility_pct, 2),
                "liquidity_turnover": round(latest["turnover"], 2),
                "fundamental_context": "Manual review still required. Live fundamentals are not connected yet; this app only confirms the stock is in the beginner liquid NSE watchlist.",
            },
            invalidation={"close_below": round(stop, 2), "condition": "Exit or avoid if daily close breaks the stop-loss level."},
            ranking_explanation="Score combines trend alignment, recent momentum, volume participation, liquidity, and ATR-based risk. It is a quantified checklist, not a guarantee.",
        )


def all_strategies():
    return [
        BeginnerSwingChecklistStrategy(),
        TrendContinuationStrategy(),
        BreakoutVolumeStrategy(),
        PullbackUptrendStrategy(),
        RelativeStrengthTrendStrategy(),
        VolatilityContractionBreakoutStrategy(),
        BollingerSqueezeMomentumStrategy(),
        BullRangeRsiPullbackStrategy(),
        SectorLeaderBreakoutStrategy(),
        BreakoutRetestStrategy(),
        VolumeAccumulationTrendStrategy(),
    ]
