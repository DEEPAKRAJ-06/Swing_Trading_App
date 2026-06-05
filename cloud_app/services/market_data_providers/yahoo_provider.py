from __future__ import annotations

import json
import contextlib
import io
import os
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone

from cloud_app.services.market_data_providers.base import MarketDataProvider, ProviderCandle


def yahoo_symbol(symbol: str) -> str:
    clean = symbol.upper().strip()
    return clean if clean.endswith(".NS") else f"{clean}.NS"


class YahooFinanceProvider(MarketDataProvider):
    name = "yahoo_finance"
    data_mode = "real"

    def fetch_daily(self, symbols: list[str], lookback_days: int = 260) -> list[ProviderCandle]:
        candles: list[ProviderCandle] = []
        period = "1y" if lookback_days <= 366 else "3y"
        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = {executor.submit(self._fetch_one, symbol, period): symbol for symbol in symbols}
            completed = 0
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    candles.extend(future.result())
                except Exception as exc:
                    print(f"market_data_skip symbol={symbol} error={type(exc).__name__}", flush=True)
                completed += 1
                if completed % 25 == 0 or completed == len(futures):
                    print(f"market_data_progress fetched={completed}/{len(futures)} candles={len(candles)}", flush=True)
        if not candles:
            raise RuntimeError("Yahoo Finance returned no NSE candles for the watchlist.")
        return candles

    def _fetch_one(self, symbol: str, period: str) -> list[ProviderCandle]:
        provider_symbol = yahoo_symbol(symbol)
        candles = self._fetch_with_chart_api(symbol, provider_symbol, period)
        if candles:
            return candles
        if os.getenv("ENABLE_YFINANCE_FALLBACK") != "1":
            return []
        return self._fetch_with_yfinance(symbol, provider_symbol, period)

    def _fetch_with_yfinance(self, symbol: str, provider_symbol: str, period: str) -> list[ProviderCandle]:
        try:
            import yfinance as yf
        except ImportError:
            return []
        try:
            ticker = yf.Ticker(provider_symbol)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                history = ticker.history(period=period, interval="1d", auto_adjust=False)
        except Exception:
            return []
        if history.empty:
            return []
        history = history.dropna(subset=["Open", "High", "Low", "Close"])
        candles: list[ProviderCandle] = []
        for index, row in history.iterrows():
            trade_date = index.date() if hasattr(index, "date") else date.fromisoformat(str(index)[:10])
            close = float(row["Close"])
            adjusted = float(row.get("Adj Close", close) or close)
            candles.append(
                ProviderCandle(
                    symbol=symbol,
                    provider_symbol=provider_symbol,
                    trade_date=trade_date.isoformat(),
                    open=round(float(row["Open"]), 2),
                    high=round(float(row["High"]), 2),
                    low=round(float(row["Low"]), 2),
                    close=round(close, 2),
                    adjusted_close=round(adjusted, 2),
                    volume=int(row.get("Volume", 0) or 0),
                    source=self.name,
                    synthetic=False,
                    metadata={
                        "synthetic": False,
                        "data_mode": "real",
                        "provider_symbol": provider_symbol,
                        "transport": "yfinance",
                    },
                )
            )
        return candles

    def _fetch_with_chart_api(self, symbol: str, provider_symbol: str, period: str) -> list[ProviderCandle]:
        encoded = urllib.parse.quote(provider_symbol)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range={period}&interval=1d"
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return []
        result = (payload.get("chart", {}).get("result") or [None])[0]
        if not result:
            return []
        timestamps = result.get("timestamp") or []
        quote = (result.get("indicators", {}).get("quote") or [{}])[0]
        adjusted = (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or quote.get("close") or []
        candles: list[ProviderCandle] = []
        for idx, ts in enumerate(timestamps):
            open_price = _nth(quote.get("open"), idx)
            high = _nth(quote.get("high"), idx)
            low = _nth(quote.get("low"), idx)
            close = _nth(quote.get("close"), idx)
            if None in {open_price, high, low, close}:
                continue
            trade_date = datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
            candles.append(
                ProviderCandle(
                    symbol=symbol,
                    provider_symbol=provider_symbol,
                    trade_date=trade_date,
                    open=round(float(open_price), 2),
                    high=round(float(high), 2),
                    low=round(float(low), 2),
                    close=round(float(close), 2),
                    adjusted_close=round(float(_nth(adjusted, idx) or close), 2),
                    volume=int(_nth(quote.get("volume"), idx) or 0),
                    source=self.name,
                    synthetic=False,
                    metadata={
                        "synthetic": False,
                        "data_mode": "real",
                        "provider_symbol": provider_symbol,
                        "transport": "yahoo_chart_api",
                    },
                )
            )
        return candles


def _nth(values, idx: int):
    if not values or idx >= len(values):
        return None
    return values[idx]
