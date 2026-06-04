from __future__ import annotations

import csv
import io
import urllib.request
from functools import lru_cache


NIFTY200_CSV_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty200list.csv"

NIFTY200_FALLBACK = [
    ("RELIANCE", "Reliance Industries Ltd.", "Oil Gas & Consumable Fuels"),
    ("TCS", "Tata Consultancy Services Ltd.", "Information Technology"),
    ("HDFCBANK", "HDFC Bank Ltd.", "Financial Services"),
    ("BHARTIARTL", "Bharti Airtel Ltd.", "Telecommunication"),
    ("ICICIBANK", "ICICI Bank Ltd.", "Financial Services"),
    ("INFY", "Infosys Ltd.", "Information Technology"),
    ("SBIN", "State Bank of India", "Financial Services"),
    ("LT", "Larsen & Toubro Ltd.", "Construction"),
    ("SUNPHARMA", "Sun Pharmaceutical Industries Ltd.", "Healthcare"),
    ("MARUTI", "Maruti Suzuki India Ltd.", "Automobile"),
    ("TITAN", "Titan Company Ltd.", "Consumer Durables"),
    ("AXISBANK", "Axis Bank Ltd.", "Financial Services"),
    ("KOTAKBANK", "Kotak Mahindra Bank Ltd.", "Financial Services"),
    ("BAJFINANCE", "Bajaj Finance Ltd.", "Financial Services"),
    ("ASIANPAINT", "Asian Paints Ltd.", "Consumer Durables"),
    ("HINDUNILVR", "Hindustan Unilever Ltd.", "Fast Moving Consumer Goods"),
    ("ITC", "ITC Ltd.", "Fast Moving Consumer Goods"),
    ("ULTRACEMCO", "UltraTech Cement Ltd.", "Construction Materials"),
    ("NESTLEIND", "Nestle India Ltd.", "Fast Moving Consumer Goods"),
    ("POWERGRID", "Power Grid Corporation of India Ltd.", "Power"),
]


@lru_cache(maxsize=1)
def fetch_nifty200_universe() -> tuple[list[tuple[str, str, str]], dict]:
    request = urllib.request.Request(NIFTY200_CSV_URL, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            text = response.read().decode("utf-8-sig")
        output = []
        for row in csv.DictReader(io.StringIO(text)):
            symbol = (row.get("Symbol") or "").strip().upper()
            series = (row.get("Series") or "").strip().upper()
            name = (row.get("Company Name") or symbol).strip()
            industry = (row.get("Industry") or "NSE 200").strip()
            if symbol and series == "EQ":
                output.append((symbol, name, industry))
        if output:
            return output, {"source": "official_nse_csv", "count": len(output), "url": NIFTY200_CSV_URL}
    except Exception as exc:
        return NIFTY200_FALLBACK, {"source": "fallback", "error": str(exc), "count": len(NIFTY200_FALLBACK)}
    return NIFTY200_FALLBACK, {"source": "fallback", "error": "Official CSV had no EQ rows.", "count": len(NIFTY200_FALLBACK)}

