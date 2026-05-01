"""Build the daily Taiwan-market universe (TWSE + TPEx + ETFs), ranked by
20-day average dollar volume.

Pipeline:
1. Pull yesterday's all-stock summary from the TWSE & TPEx OpenAPIs
   (covers ~1,300 listed names + ~10,000 OTC entries).
2. Keep regular equities and ETFs; drop warrants, ETN special classes, etc.
3. Take the top ~600 by single-day turnover as the candidate pool.
4. Use yfinance bulk download (Yahoo) to pull the last 30 trading days
   for those ~600 symbols and re-rank by 20-day mean of (Close × Volume).
5. Cache the final ordered DataFrame to data/universe/{YYYY-MM-DD}.parquet.

The cache is what morning_brief.py and event_study.py read."""
from __future__ import annotations

import datetime as dt
import logging
import re
from pathlib import Path

import pandas as pd
import yfinance as yf
from curl_cffi import requests as cr

LOG = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data" / "universe"
DATA_DIR.mkdir(parents=True, exist_ok=True)

CANDIDATE_POOL = 600  # top-by-yesterday-turnover pulled from Yahoo
TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"

_CODE_TWSE = re.compile(r"^\d{4}$|^00\d{2,3}$")  # 4-digit equity OR 00xxx ETF
_CODE_TPEX = re.compile(r"^\d{4}$|^\d{6}$")  # 4-digit equity OR 6-digit ETF


def _http_get_json(url: str) -> list[dict]:
    r = cr.get(url, timeout=30, impersonate="chrome")
    r.raise_for_status()
    return r.json()


def _to_float(v) -> float:
    if v is None:
        return 0.0
    s = str(v).replace(",", "").strip()
    if not s or s in {"--", "----"}:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def fetch_twse_summary() -> pd.DataFrame:
    raw = _http_get_json(TWSE_URL)
    rows = []
    for d in raw:
        code = (d.get("Code") or "").strip()
        if not _CODE_TWSE.match(code):
            continue
        rows.append({
            "code": code,
            "name": (d.get("Name") or "").strip(),
            "market": "TWSE",
            "yf_symbol": f"{code}.TW",
            "value_today": _to_float(d.get("TradeValue")),
        })
    return pd.DataFrame(rows)


def fetch_tpex_summary() -> pd.DataFrame:
    raw = _http_get_json(TPEX_URL)
    rows = []
    for d in raw:
        code = (d.get("SecuritiesCompanyCode") or "").strip()
        if not _CODE_TPEX.match(code):
            continue
        rows.append({
            "code": code,
            "name": (d.get("CompanyName") or "").strip(),
            "market": "TPEx",
            "yf_symbol": f"{code}.TWO",
            "value_today": _to_float(d.get("TransactionAmount")),
        })
    return pd.DataFrame(rows)


def fetch_full_market() -> pd.DataFrame:
    twse = fetch_twse_summary()
    tpex = fetch_tpex_summary()
    LOG.info("TWSE %d  TPEx %d", len(twse), len(tpex))
    full = pd.concat([twse, tpex], ignore_index=True)
    full = full[full["value_today"] > 0].copy()
    full = full.drop_duplicates(subset=["yf_symbol"])
    full = full.sort_values("value_today", ascending=False).reset_index(drop=True)
    return full


def _yf_bulk_history(symbols: list[str], days: int = 45) -> dict[str, pd.DataFrame]:
    """Bulk-download daily OHLCV from Yahoo, return {symbol: df}."""
    end = dt.date.today() + dt.timedelta(days=1)
    start = end - dt.timedelta(days=days + 14)
    LOG.info("yfinance bulk download: %d symbols", len(symbols))
    raw = yf.download(
        tickers=symbols,
        start=start.isoformat(),
        end=end.isoformat(),
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        progress=False,
        threads=True,
    )
    out: dict[str, pd.DataFrame] = {}
    if isinstance(raw.columns, pd.MultiIndex):
        for sym in symbols:
            if sym not in raw.columns.get_level_values(0):
                continue
            sub = raw[sym].dropna(how="all")
            if not sub.empty:
                out[sym] = sub
    else:
        # Single-symbol case (yfinance flattens columns)
        if not raw.empty and symbols:
            out[symbols[0]] = raw.dropna(how="all")
    return out


def build_ranked_universe(top_n: int = 300) -> pd.DataFrame:
    """Rank the full market by 20-day avg dollar volume, return top_n rows."""
    full = fetch_full_market()
    pool = full.head(CANDIDATE_POOL).copy()
    histories = _yf_bulk_history(pool["yf_symbol"].tolist(), days=45)

    rows = []
    for _, r in pool.iterrows():
        df = histories.get(r["yf_symbol"])
        if df is None or df.empty or "Close" not in df or "Volume" not in df:
            continue
        df = df.dropna(subset=["Close", "Volume"]).tail(20)
        if len(df) < 10:  # need a reasonable window
            continue
        avg_dollar_vol = float((df["Close"] * df["Volume"]).mean())
        rows.append({**r.to_dict(), "avg_dollar_vol_20d": avg_dollar_vol, "bars": len(df)})

    ranked = pd.DataFrame(rows)
    if ranked.empty:
        raise RuntimeError("No bars returned from yfinance — universe rank failed.")
    ranked = ranked.sort_values("avg_dollar_vol_20d", ascending=False).reset_index(drop=True)
    ranked["rank"] = ranked.index + 1
    return ranked.head(top_n)


def cache_path(date: dt.date) -> Path:
    return DATA_DIR / f"{date.isoformat()}.parquet"


def load_or_build(date: dt.date | None = None, force_refresh: bool = False) -> pd.DataFrame:
    date = date or dt.date.today()
    p = cache_path(date)
    if p.exists() and not force_refresh:
        return pd.read_parquet(p)
    ranked = build_ranked_universe(top_n=300)
    ranked.to_parquet(p, index=False)
    LOG.info("Saved universe → %s (%d rows)", p, len(ranked))
    return ranked


def top_n(n: int, date: dt.date | None = None) -> pd.DataFrame:
    df = load_or_build(date)
    return df.head(n).reset_index(drop=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    df = load_or_build(force_refresh=True)
    print(df.head(20).to_string())
    print(f"\nTotal cached: {len(df)}  (Top 300)")
