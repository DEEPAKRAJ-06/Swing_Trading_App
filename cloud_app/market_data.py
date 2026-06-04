from __future__ import annotations

from sqlalchemy import text

from cloud_app.db import db, json_dumps, now_iso, row, rows
from cloud_app.services.market_data_providers import YahooFinanceProvider
from cloud_app.universe import fetch_nifty200_universe


def sync_symbols() -> dict:
    universe, meta = fetch_nifty200_universe()
    timestamp = now_iso()
    with db() as conn:
        for symbol, company_name, sector in universe:
            conn.execute(
                text(
                    """
                    INSERT INTO symbols (symbol, company_name, sector, is_active, updated_at)
                    VALUES (:symbol, :company_name, :sector, 1, :updated_at)
                    ON CONFLICT (symbol) DO UPDATE SET
                      company_name = excluded.company_name,
                      sector = excluded.sector,
                      is_active = 1,
                      updated_at = excluded.updated_at
                    """
                ),
                {"symbol": symbol, "company_name": company_name, "sector": sector, "updated_at": timestamp},
            )
    return {"symbols": len(universe), "source": meta.get("source"), "metadata": meta}


def active_symbols() -> list[dict]:
    sync_symbols()
    with db() as conn:
        return rows(conn.execute(text("SELECT * FROM symbols WHERE is_active = 1 ORDER BY symbol")))


def store_candles(candles) -> int:
    timestamp = now_iso()
    stored = 0
    with db() as conn:
        for candle in candles:
            conn.execute(
                text(
                    """
                    INSERT INTO market_data_daily
                    (symbol, trade_date, open, high, low, close, adjusted_close, volume, turnover,
                     source, source_metadata_json, created_at)
                    VALUES (:symbol, :trade_date, :open, :high, :low, :close, :adjusted_close, :volume,
                            :turnover, :source, :source_metadata_json, :created_at)
                    ON CONFLICT (symbol, trade_date) DO UPDATE SET
                      open = excluded.open,
                      high = excluded.high,
                      low = excluded.low,
                      close = excluded.close,
                      adjusted_close = excluded.adjusted_close,
                      volume = excluded.volume,
                      turnover = excluded.turnover,
                      source = excluded.source,
                      source_metadata_json = excluded.source_metadata_json
                    """
                ),
                {
                    "symbol": candle.symbol,
                    "trade_date": candle.trade_date,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "adjusted_close": candle.adjusted_close,
                    "volume": candle.volume,
                    "turnover": candle.turnover,
                    "source": candle.source,
                    "source_metadata_json": json_dumps(candle.metadata),
                    "created_at": timestamp,
                },
            )
            stored += 1
    return stored


def sync_market_data(lookback_days: int = 760) -> dict:
    symbols = [item["symbol"] for item in active_symbols()]
    candles = YahooFinanceProvider().fetch_daily(symbols, lookback_days=lookback_days)
    return {"mode": "real", "provider": "yahoo_finance", "candles_stored": store_candles(candles), "symbols": len(symbols)}


def candles_for_symbol(symbol: str, limit: int = 900) -> list[dict]:
    with db() as conn:
        return list(
            reversed(
                rows(
                    conn.execute(
                        text(
                            """
                            SELECT md.*, sym.company_name, sym.sector
                            FROM market_data_daily md
                            JOIN symbols sym ON sym.symbol = md.symbol
                            WHERE md.symbol = :symbol
                            ORDER BY md.trade_date DESC
                            LIMIT :limit
                            """
                        ),
                        {"symbol": symbol, "limit": limit},
                    )
                )
            )
        )


def latest_prices() -> list[dict]:
    with db() as conn:
        return rows(
            conn.execute(
                text(
                    """
                    SELECT sym.symbol, sym.company_name, sym.sector, md.trade_date, md.close, md.source
                    FROM symbols sym
                    JOIN market_data_daily md ON md.symbol = sym.symbol
                    WHERE md.trade_date = (
                      SELECT MAX(inner_md.trade_date)
                      FROM market_data_daily inner_md
                      WHERE inner_md.symbol = sym.symbol
                    )
                    ORDER BY sym.symbol
                    """
                )
            )
        )


def latest_price(symbol: str) -> dict | None:
    with db() as conn:
        return row(
            conn.execute(
                text(
                    """
                    SELECT * FROM market_data_daily
                    WHERE symbol = :symbol
                    ORDER BY trade_date DESC
                    LIMIT 1
                    """
                ),
                {"symbol": symbol},
            )
        )
