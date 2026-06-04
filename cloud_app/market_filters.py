from __future__ import annotations

from collections import defaultdict
from statistics import mean, median

from cloud_app.market_data import active_symbols, candles_for_symbol
from cloud_app.services.indicators import pct_change, sma


def _avg(values: list[float]) -> float:
    return mean(values) if values else 0.0


def market_sector_context() -> dict:
    rows: list[dict] = []
    sector_rows: dict[str, list[dict]] = defaultdict(list)
    for symbol in active_symbols():
        candles = candles_for_symbol(symbol["symbol"], limit=160)
        if len(candles) < 70:
            continue
        closes = [c["close"] for c in candles]
        ma20 = sma(closes, 20)
        ma50 = sma(closes, 50)
        if not ma20 or not ma50:
            continue
        item = {
            "symbol": symbol["symbol"],
            "sector": symbol.get("sector") or "Unclassified",
            "above_20dma": closes[-1] >= ma20,
            "above_50dma": closes[-1] >= ma50,
            "momentum_20d_pct": pct_change(closes, 20) or 0.0,
            "momentum_63d_pct": pct_change(closes, 63) or 0.0,
            "momentum_126d_pct": pct_change(closes, 126) or 0.0,
        }
        rows.append(item)
        sector_rows[item["sector"]].append(item)

    usable = len(rows)
    above_50_pct = round(sum(1 for item in rows if item["above_50dma"]) / usable * 100, 2) if usable else 0
    above_20_pct = round(sum(1 for item in rows if item["above_20dma"]) / usable * 100, 2) if usable else 0
    median_20 = round(median([item["momentum_20d_pct"] for item in rows]), 2) if rows else 0
    median_63 = round(median([item["momentum_63d_pct"] for item in rows]), 2) if rows else 0
    long_allowed = usable < 20 or (above_50_pct >= 42 and median_20 >= -4.5 and median_63 >= -8)
    regime = "constructive" if above_50_pct >= 55 and median_20 >= 0 else "mixed_tradable" if long_allowed else "defensive"

    sectors = {}
    for sector, items in sector_rows.items():
        count = len(items)
        sector_above_50 = sum(1 for item in items if item["above_50dma"]) / count * 100 if count else 0
        avg_20 = _avg([item["momentum_20d_pct"] for item in items])
        avg_63 = _avg([item["momentum_63d_pct"] for item in items])
        avg_126 = _avg([item["momentum_126d_pct"] for item in items])
        score = round(avg_63 * 0.55 + avg_20 * 0.25 + avg_126 * 0.10 + (sector_above_50 - 50) * 0.18, 2)
        sectors[sector] = {
            "sector": sector,
            "symbol_count": count,
            "above_50dma_pct": round(sector_above_50, 2),
            "momentum_20d_pct": round(avg_20, 2),
            "momentum_63d_pct": round(avg_63, 2),
            "momentum_126d_pct": round(avg_126, 2),
            "strength_score": score,
            "allowed": False,
            "rank": None,
        }

    ranked = sorted(sectors.values(), key=lambda item: item["strength_score"], reverse=True)
    allowed_count = max(3, int(len(ranked) * 0.4)) if ranked else 0
    allowed_sectors = set()
    for idx, item in enumerate(ranked, start=1):
        item["rank"] = idx
        allowed = idx <= allowed_count and item["strength_score"] >= -6 and item["above_50dma_pct"] >= 35
        item["allowed"] = allowed
        if allowed:
            allowed_sectors.add(item["sector"])
    if long_allowed and ranked and not allowed_sectors:
        for item in ranked[: min(3, len(ranked))]:
            item["allowed"] = True
            allowed_sectors.add(item["sector"])

    return {
        "market": {
            "regime": regime,
            "long_allowed": long_allowed,
            "symbols_evaluated": usable,
            "above_20dma_pct": above_20_pct,
            "above_50dma_pct": above_50_pct,
            "median_momentum_20d_pct": median_20,
            "median_momentum_63d_pct": median_63,
        },
        "sectors": sectors,
        "allowed_sectors": sorted(allowed_sectors),
        "top_sectors": ranked[:5],
        "filter_version": "cloud_market_sector_v1",
    }


def sector_gate_for_symbol(symbol: dict, context: dict) -> tuple[bool, dict]:
    sector = symbol.get("sector") or "Unclassified"
    info = context.get("sectors", {}).get(sector, {"sector": sector, "strength_score": 0, "allowed": True})
    if not context.get("market", {}).get("long_allowed", True):
        return False, info
    allowed = set(context.get("allowed_sectors") or [])
    return (not allowed or sector in allowed), info
