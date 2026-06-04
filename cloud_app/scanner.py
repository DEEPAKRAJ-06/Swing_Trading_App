from __future__ import annotations

from datetime import date

from sqlalchemy import text

from cloud_app.config import settings
from cloud_app.db import db, get_state, json_dumps, new_id, now_iso, rows, set_state
from cloud_app.market_data import active_symbols, candles_for_symbol
from cloud_app.market_filters import market_sector_context, sector_gate_for_symbol
from cloud_app.services.strategies.swing import all_strategies


def latest_strategy_payload() -> dict:
    return get_state("latest_validation", {}) or {}


def latest_strategy_selection() -> dict:
    return latest_strategy_payload().get(
        "selected_strategy",
        {"strategy_key": None, "strategy_name": None, "mode": "none", "selection_score": 0, "reason": "Run Strategy Lab first."},
    )


def latest_strategy_validation() -> dict:
    return latest_strategy_payload().get("strategy_metrics", {})


def _strategy_passes_validation(validation: dict) -> bool:
    return bool(validation and validation.get("passes_validation"))


def _calibrated_confidence(technical_score: float, validation: dict) -> float:
    reliability = validation.get("reliability_score", 50) if validation else 50
    sample = validation.get("trade_count", 0) if validation else 0
    sample_penalty = 8 if sample < 20 else 0
    return round(max(1, min(99, technical_score * 0.58 + reliability * 0.42 - sample_penalty)), 1)


def _candidate_rank_score(candidate) -> float:
    factors = candidate.factor_breakdown or {}
    momentum_63 = float(factors.get("momentum_63d_pct", 0) or 0)
    momentum_126 = float(factors.get("momentum_126d_pct", 0) or 0)
    sector_score = float(factors.get("sector_strength_score", 0) or 0)
    return round(
        candidate.confidence_score
        + min(candidate.risk_reward_ratio, 3.0) * 2.5
        + min(max(momentum_63, 0), 50) * 0.08
        + min(max(momentum_126, 0), 80) * 0.05
        + min(max(sector_score, -10), 30) * 0.12,
        2,
    )


def run_daily_scan() -> dict:
    symbols = active_symbols()
    selection = latest_strategy_selection()
    selected_key = selection.get("strategy_key")
    validations = latest_strategy_validation()
    strategies = [strategy for strategy in all_strategies() if strategy.key == selected_key] if selected_key else []
    market_filter = market_sector_context()
    signal_date = date.today().isoformat()
    timestamp = now_iso()
    candidates = []

    with db() as conn:
        conn.execute(text("DELETE FROM signals WHERE signal_date = :signal_date"), {"signal_date": signal_date})

    if not selected_key:
        payload = {
            "universe_size": len(symbols),
            "candidates_found": 0,
            "signals_promoted": 0,
            "selected_strategy": selection,
            "market_filter": market_filter,
            "message": selection.get("reason", "No selected strategy."),
        }
        set_state("latest_scan", payload)
        return payload

    if not market_filter.get("market", {}).get("long_allowed", True):
        payload = {
            "universe_size": len(symbols),
            "candidates_found": 0,
            "signals_promoted": 0,
            "selected_strategy": selection,
            "market_filter": market_filter,
            "message": "Broad market filter blocked new long setups.",
        }
        set_state("latest_scan", payload)
        return payload

    for symbol in symbols:
        sector_ok, sector_info = sector_gate_for_symbol(symbol, market_filter)
        if not sector_ok:
            continue
        candles = candles_for_symbol(symbol["symbol"], limit=260)
        if len(candles) < 90:
            continue
        for strategy in strategies:
            validation = validations.get(strategy.key, {})
            if not _strategy_passes_validation(validation):
                continue
            candidate = strategy.evaluate(symbol, candles)
            if not candidate:
                continue
            sector_bonus = max(-4, min(5, float(sector_info.get("strength_score", 0) or 0) * 0.12))
            candidate.confidence_score = round(max(1, min(99, _calibrated_confidence(candidate.confidence_score, validation) + sector_bonus)), 1)
            candidate.factor_breakdown = {
                **candidate.factor_breakdown,
                "market_regime": market_filter.get("market", {}).get("regime"),
                "market_above_50dma_pct": market_filter.get("market", {}).get("above_50dma_pct"),
                "sector_rank": sector_info.get("rank"),
                "sector_strength_score": sector_info.get("strength_score"),
                "sector_momentum_63d_pct": sector_info.get("momentum_63d_pct"),
                "sector_filter": "pass",
            }
            candidates.append((_candidate_rank_score(candidate), candidate, symbol, strategy, validation, sector_info))

    candidates.sort(key=lambda item: item[0], reverse=True)
    promoted = candidates[: settings.max_daily_setups]
    with db() as conn:
        for _, candidate, symbol, strategy, validation, sector_info in promoted:
            conn.execute(
                text(
                    """
                    INSERT INTO signals
                    (id, symbol, company_name, sector, strategy_key, strategy_name, signal_date,
                     entry_low, entry_high, stop_loss, target_price, expected_holding_days,
                     risk_reward_ratio, confidence_score, reason_summary, factor_breakdown_json,
                     backtest_summary_json, source_metadata_json, ranking_explanation, status,
                     created_at, updated_at)
                    VALUES (:id, :symbol, :company_name, :sector, :strategy_key, :strategy_name,
                            :signal_date, :entry_low, :entry_high, :stop_loss, :target_price,
                            :expected_holding_days, :risk_reward_ratio, :confidence_score,
                            :reason_summary, :factor_breakdown_json, :backtest_summary_json,
                            :source_metadata_json, :ranking_explanation, 'new', :created_at, :updated_at)
                    """
                ),
                {
                    "id": new_id(),
                    "symbol": symbol["symbol"],
                    "company_name": symbol["company_name"],
                    "sector": symbol["sector"],
                    "strategy_key": strategy.key,
                    "strategy_name": strategy.name,
                    "signal_date": signal_date,
                    "entry_low": candidate.entry_low,
                    "entry_high": candidate.entry_high,
                    "stop_loss": candidate.stop_loss,
                    "target_price": candidate.target_price,
                    "expected_holding_days": candidate.expected_holding_days,
                    "risk_reward_ratio": candidate.risk_reward_ratio,
                    "confidence_score": candidate.confidence_score,
                    "reason_summary": candidate.reason_summary,
                    "factor_breakdown_json": json_dumps(candidate.factor_breakdown),
                    "backtest_summary_json": json_dumps(
                        {
                            "sample_size": validation.get("trade_count", 0),
                            "win_rate": validation.get("win_rate", 0),
                            "profit_factor": validation.get("profit_factor", 0),
                            "max_drawdown": validation.get("max_drawdown_pct", 0),
                            "reliability_score": validation.get("reliability_score", 0),
                            "expectancy": validation.get("expectancy", 0),
                        }
                    ),
                    "source_metadata_json": json_dumps(
                        {
                            "scanner": "cloud_daily_v1",
                            "market": "NSE",
                            "provider": "yahoo_finance",
                            "selected_strategy": selection,
                            "market_filter": {
                                "version": market_filter.get("filter_version"),
                                "regime": market_filter.get("market", {}).get("regime"),
                                "allowed_sectors": market_filter.get("allowed_sectors", []),
                                "sector": sector_info,
                            },
                        }
                    ),
                    "ranking_explanation": candidate.ranking_explanation,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            )

    payload = {
        "universe_size": len(symbols),
        "candidates_found": len(candidates),
        "signals_promoted": len(promoted),
        "selected_strategy": selection,
        "market_filter": market_filter,
    }
    set_state("latest_scan", payload)
    return payload


def list_signals(limit: int = 20) -> list[dict]:
    with db() as conn:
        return rows(
            conn.execute(
                text(
                    """
                    SELECT * FROM signals
                    ORDER BY signal_date DESC, confidence_score DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
        )
