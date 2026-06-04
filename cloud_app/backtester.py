from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Callable

from sqlalchemy import text

from cloud_app.config import settings
from cloud_app.db import db, json_dumps, new_id, now_iso, set_state
from cloud_app.market_data import active_symbols, candles_for_symbol, latest_price
from cloud_app.services.strategies.swing import all_strategies


VALIDATION_RULES = {
    "min_trades": 60,
    "min_profit_factor": 1.15,
    "min_expectancy": 0,
    "max_drawdown_pct": 35,
    "min_recent_trades": 20,
    "min_recent_profit_factor": 1.0,
}

BACKTEST_MODES = {
    "fast": {"label": "Fast", "max_symbols": 25, "description": "Top 25 liquid names. Best for daily use."},
    "standard": {"label": "Standard", "max_symbols": 80, "description": "Top 80 liquid names. Broader validation."},
    "full": {"label": "Full", "max_symbols": 0, "description": "All active symbols. Slowest."},
}


def _exit_trade(candles: list[dict], start_idx: int, stop: float, target: float, max_days: int) -> tuple[float, str, str, int]:
    end_idx = min(start_idx + max_days, len(candles) - 1)
    for idx in range(start_idx, end_idx + 1):
        candle = candles[idx]
        if candle["low"] <= stop:
            return stop, "stop_loss", candle["trade_date"], idx - start_idx + 1
        if candle["high"] >= target:
            return target, "target_hit", candle["trade_date"], idx - start_idx + 1
    candle = candles[end_idx]
    return candle["close"], "time_exit", candle["trade_date"], end_idx - start_idx + 1


def _net_pnl(entry: float, exit_price: float, quantity: int) -> float:
    gross = (exit_price - entry) * quantity
    turnover = (entry + exit_price) * quantity
    costs = turnover * (settings.slippage_bps + settings.transaction_cost_bps) / 10_000
    return round(gross - costs, 2)


def _metrics(trades: list[dict], starting_equity: float, ending_equity: float) -> dict:
    wins = [trade for trade in trades if trade["pnl"] > 0]
    losses = [trade for trade in trades if trade["pnl"] <= 0]
    gross_gain = sum(trade["pnl"] for trade in wins)
    gross_loss = abs(sum(trade["pnl"] for trade in losses))
    equity = starting_equity
    peak = starting_equity
    max_drawdown = 0.0
    for trade in sorted(trades, key=lambda item: item["exit_date"]):
        equity += trade["pnl"]
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak * 100 if peak else 0)
    return {
        "trade_count": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100, 2) if trades else 0,
        "profit_factor": round(gross_gain / gross_loss, 2) if gross_loss else (round(gross_gain, 2) if gross_gain else 0),
        "expectancy": round((gross_gain - gross_loss) / len(trades), 2) if trades else 0,
        "avg_win": round(gross_gain / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(trade["pnl"] for trade in losses) / len(losses), 2) if losses else 0,
        "max_drawdown_pct": round(max_drawdown, 2),
        "ending_equity": round(ending_equity, 2),
    }


def _period_metrics(trades: list[dict]) -> dict:
    if not trades:
        return _metrics([], settings.paper_capital, settings.paper_capital)
    pnl = sum(trade["pnl"] for trade in trades)
    return _metrics(trades, settings.paper_capital, settings.paper_capital + pnl)


def _validation_failures(metrics: dict) -> list[str]:
    recent = metrics.get("recent_period", {})
    failures: list[str] = []
    if metrics.get("trade_count", 0) < VALIDATION_RULES["min_trades"]:
        failures.append(f"Needs at least {VALIDATION_RULES['min_trades']} historical trades")
    if metrics.get("profit_factor", 0) < VALIDATION_RULES["min_profit_factor"]:
        failures.append(f"Profit factor below {VALIDATION_RULES['min_profit_factor']}")
    if metrics.get("expectancy", 0) < VALIDATION_RULES["min_expectancy"]:
        failures.append("Expectancy is not positive after costs")
    if metrics.get("max_drawdown_pct", 0) > VALIDATION_RULES["max_drawdown_pct"]:
        failures.append(f"Drawdown above {VALIDATION_RULES['max_drawdown_pct']}%")
    if recent.get("trade_count", 0) < VALIDATION_RULES["min_recent_trades"]:
        failures.append(f"Recent period has fewer than {VALIDATION_RULES['min_recent_trades']} trades")
    if recent.get("profit_factor", 0) < VALIDATION_RULES["min_recent_profit_factor"]:
        failures.append(f"Recent profit factor below {VALIDATION_RULES['min_recent_profit_factor']}")
    return failures


def _reliability_score(metrics: dict) -> float:
    sample_score = min(metrics.get("trade_count", 0) / 90, 1) * 18
    win_score = max(0, metrics.get("win_rate", 0) - 42) * 0.9
    pf_score = min(max(metrics.get("profit_factor", 0) - 0.8, 0), 1.2) * 18
    recent_pf = metrics.get("recent_period", {}).get("profit_factor", 0)
    recent_score = min(max(recent_pf - 0.9, 0), 1.0) * 10
    dd_penalty = min(metrics.get("max_drawdown_pct", 0), 35) * 0.7
    return round(max(0, min(100, 34 + sample_score + win_score + pf_score + recent_score - dd_penalty)), 1)


def _selection_score(metrics: dict) -> float:
    recent = metrics.get("recent_period", {})
    return round(
        metrics.get("reliability_score", 0) * 0.35
        + min(metrics.get("profit_factor", 0), 2.5) * 18
        + min(recent.get("profit_factor", 0), 2.5) * 14
        + max(metrics.get("expectancy", 0), 0) / 45
        - min(metrics.get("max_drawdown_pct", 0), 50) * 0.35,
        2,
    )


def _select_strategy(strategy_metrics: dict) -> dict:
    evaluated = []
    for key, metrics in strategy_metrics.items():
        failures = _validation_failures(metrics)
        metrics["passes_validation"] = not failures
        metrics["validation_failures"] = failures
        metrics["selection_score"] = _selection_score(metrics)
        evaluated.append((metrics["passes_validation"], metrics["selection_score"], key, metrics))
    passed = [item for item in evaluated if item[0]]
    if not passed:
        return {
            "strategy_key": None,
            "strategy_name": None,
            "selection_score": 0,
            "mode": "none",
            "reason": "No strategy passed the strict validation gate today.",
            "validation_rules": VALIDATION_RULES,
        }
    _, score, key, metrics = sorted(passed, key=lambda item: item[1], reverse=True)[0]
    return {
        "strategy_key": key,
        "strategy_name": metrics.get("strategy_name", key),
        "selection_score": score,
        "mode": "validated",
        "reason": "Selected because it passed the strict validation gate and had the highest composite score.",
        "validation_rules": VALIDATION_RULES,
    }


def _ranked_symbols(mode: str) -> list[dict]:
    symbols = active_symbols()
    max_symbols = BACKTEST_MODES.get(mode, BACKTEST_MODES["fast"])["max_symbols"]
    ranked = []
    for symbol in symbols:
        candle = latest_price(symbol["symbol"])
        ranked.append(((candle or {}).get("turnover", 0), symbol))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if max_symbols == 0:
        return [symbol for _, symbol in ranked]
    return [symbol for _, symbol in ranked[:max_symbols]]


def run_walkforward_backtest(
    mode: str = "fast",
    strategy_key: str = "all",
    progress_callback: Callable[[dict], None] | None = None,
) -> dict:
    selected_mode = mode if mode in BACKTEST_MODES else "fast"
    strategies = all_strategies() if strategy_key == "all" else [item for item in all_strategies() if item.key == strategy_key]
    if not strategies:
        raise ValueError("Unknown strategy")

    start_date = (date.today() - timedelta(days=730)).isoformat()
    end_date = date.today().isoformat()
    symbols = _ranked_symbols(selected_mode)
    starting_equity = settings.paper_capital
    equity = starting_equity
    all_trades: list[dict] = []
    by_strategy: dict[str, list[dict]] = defaultdict(list)

    def report(step: str, progress_pct: int, symbols_done: int = 0) -> None:
        if progress_callback:
            progress_callback(
                {
                    "step": step,
                    "progress_pct": max(0, min(100, progress_pct)),
                    "symbols_done": symbols_done,
                    "symbols_total": len(symbols),
                }
            )

    report("Preparing symbol universe", 5)
    for symbol_idx, symbol in enumerate(symbols, start=1):
        candles = [c for c in candles_for_symbol(symbol["symbol"], limit=900) if start_date <= c["trade_date"] <= end_date]
        if len(candles) < 90:
            report(f"Skipping {symbol['symbol']} because history is too short", 8 + int(symbol_idx / max(len(symbols), 1) * 78), symbol_idx)
            continue
        cooldown_until: dict[str, int] = defaultdict(int)
        for idx in range(70, len(candles) - 2):
            for strategy in strategies:
                if idx < cooldown_until[strategy.key]:
                    continue
                candidate = strategy.evaluate(symbol, candles[: idx + 1])
                if not candidate:
                    continue
                entry_candle = candles[idx + 1]
                entry = entry_candle["open"]
                if entry <= 0 or entry > candidate.entry_high * 1.015 or entry < candidate.entry_low * 0.97:
                    continue
                risk_per_share = entry - candidate.stop_loss
                if risk_per_share <= 0:
                    continue
                quantity_by_risk = int((equity * 0.01) // risk_per_share)
                quantity_by_notional = int((equity * 0.10) // entry)
                quantity = max(0, min(quantity_by_risk, quantity_by_notional))
                if quantity <= 0:
                    continue
                exit_price, exit_reason, exit_date, holding_days = _exit_trade(
                    candles, idx + 1, candidate.stop_loss, candidate.target_price, candidate.expected_holding_days
                )
                pnl = _net_pnl(entry, exit_price, quantity)
                equity += pnl
                trade = {
                    "symbol": symbol["symbol"],
                    "strategy_key": strategy.key,
                    "strategy_name": strategy.name,
                    "signal_date": candles[idx]["trade_date"],
                    "entry_date": entry_candle["trade_date"],
                    "exit_date": exit_date,
                    "entry": round(entry, 2),
                    "stop": candidate.stop_loss,
                    "target": candidate.target_price,
                    "exit": round(exit_price, 2),
                    "exit_reason": exit_reason,
                    "quantity": quantity,
                    "pnl": pnl,
                    "holding_days": holding_days,
                }
                all_trades.append(trade)
                by_strategy[strategy.key].append(trade)
                cooldown_until[strategy.key] = idx + candidate.expected_holding_days
        report(f"Backtested {symbol['symbol']}", 8 + int(symbol_idx / max(len(symbols), 1) * 78), symbol_idx)

    report("Calculating validation metrics", 90, len(symbols))
    strategy_metrics = {}
    for strategy in strategies:
        strategy_trades = sorted(by_strategy[strategy.key], key=lambda item: item["signal_date"])
        split_idx = max(1, int(len(strategy_trades) * 0.65)) if strategy_trades else 0
        metrics = _metrics(strategy_trades, starting_equity, starting_equity + sum(t["pnl"] for t in strategy_trades))
        metrics["early_period"] = _period_metrics(strategy_trades[:split_idx])
        metrics["recent_period"] = _period_metrics(strategy_trades[split_idx:])
        metrics["reliability_score"] = _reliability_score(metrics)
        metrics["strategy_name"] = strategy.name
        metrics["strategy_family"] = strategy.family
        strategy_metrics[strategy.key] = metrics

    selected_strategy = _select_strategy(strategy_metrics)
    run_id = new_id()
    timestamp = now_iso()
    with db() as conn:
        for strategy in strategies:
            metrics = strategy_metrics[strategy.key]
            conn.execute(
                text(
                    """
                    INSERT INTO strategy_validations
                    (id, run_id, strategy_key, strategy_name, family, metrics_json, passes_validation,
                     selection_score, created_at)
                    VALUES (:id, :run_id, :strategy_key, :strategy_name, :family, :metrics_json,
                            :passes_validation, :selection_score, :created_at)
                    """
                ),
                {
                    "id": new_id(),
                    "run_id": run_id,
                    "strategy_key": strategy.key,
                    "strategy_name": strategy.name,
                    "family": strategy.family,
                    "metrics_json": json_dumps(metrics),
                    "passes_validation": 1 if metrics.get("passes_validation") else 0,
                    "selection_score": metrics.get("selection_score", 0),
                    "created_at": timestamp,
                },
            )

    payload = {
        "run_id": run_id,
        "mode": selected_mode,
        "created_at": timestamp,
        "universe_count": len(symbols),
        "strategy_metrics": strategy_metrics,
        "selected_strategy": selected_strategy,
        "trades": all_trades[-80:],
    }
    set_state("latest_validation", payload)
    report("Backtest complete", 100, len(symbols))
    return payload
