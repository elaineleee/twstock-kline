"""Daily brief generator — runs once per trading day after market close.

Pulls the latest 250 daily bars for the Top-300 universe, runs pattern
detection on the last *completed* bar (daily) and the last *completed* week
(weekly), filters via the event-study passlist, renders a Plotly chart per
signal, and writes `data/briefs/brief_{50|100|200|300}.json`."""
from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

import pandas as pd
import yfinance as yf

import chart
import event_study
import patterns
import tw_universe

LOG = logging.getLogger(__name__)

ROOT = Path(__file__).parent
BRIEFS_DIR = ROOT / "data" / "briefs"
BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
PRICES_LATEST = ROOT / "data" / "prices" / "latest_top300.parquet"

UNIVERSE_SIZES = (50, 100, 200, 300)
HISTORY_DAYS = 250  # enough for MA200 daily


# ── Price fetch ─────────────────────────────────────────────────────────

def fetch_latest_prices(symbols: list[str], days: int = HISTORY_DAYS) -> dict[str, pd.DataFrame]:
    end = dt.date.today() + dt.timedelta(days=1)
    start = end - dt.timedelta(days=days + 60)  # buffer for non-trading days
    LOG.info("yfinance bulk download: %d symbols × ~%d days", len(symbols), days)
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
    return out


def cut_to_completed_bars(df: pd.DataFrame, today: dt.date) -> pd.DataFrame:
    """Drop any in-progress bar (i.e., a bar dated 'today')."""
    if df.empty:
        return df
    last = df.index[-1].date()
    if last >= today:
        return df.iloc[:-1]
    return df


def resample_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    rule = "W-FRI"
    return pd.DataFrame({
        "Open": daily["Open"].resample(rule).first(),
        "High": daily["High"].resample(rule).max(),
        "Low": daily["Low"].resample(rule).min(),
        "Close": daily["Close"].resample(rule).last(),
        "Volume": daily["Volume"].resample(rule).sum(),
    }).dropna(how="all")


def cut_weekly_to_completed(weekly: pd.DataFrame, today: dt.date) -> pd.DataFrame:
    """Drop the currently-in-progress weekly bar (week-end >= today)."""
    if weekly.empty:
        return weekly
    last_week_end = weekly.index[-1].date()
    if last_week_end >= today:
        return weekly.iloc[:-1]
    return weekly


# ── Per-stock signal extraction ─────────────────────────────────────────

def _pct(now: float, ref: float) -> float | None:
    if ref is None or ref == 0 or pd.isna(ref):
        return None
    return round((now / ref - 1.0) * 100, 2)


def build_signal(row: dict, df: pd.DataFrame, weekly_df: pd.DataFrame, kind: str,
                 pattern_name: str, signal_date: dt.date,
                 weekly_signal_date: dt.date) -> dict:
    src = df if kind == "daily" else weekly_df
    close = float(src["Close"].iloc[-1])

    # RSI & MA come from the daily series regardless of kind, to match the
    # reference layout: RSI(14) on daily, MA distances on daily.
    daily_close = df["Close"]
    rsi = patterns.rsi(daily_close, 14).iloc[-1]
    weekly_close = weekly_df["Close"]
    weekly_ma200 = weekly_close.rolling(200).mean().iloc[-1] if len(weekly_close) >= 200 else None

    ma_dist = {
        "ma10": _pct(close, daily_close.rolling(10).mean().iloc[-1] if len(daily_close) >= 10 else None),
        "ma20": _pct(close, daily_close.rolling(20).mean().iloc[-1] if len(daily_close) >= 20 else None),
        "ma50": _pct(close, daily_close.rolling(50).mean().iloc[-1] if len(daily_close) >= 50 else None),
        "ma200_d": _pct(close, daily_close.rolling(200).mean().iloc[-1] if len(daily_close) >= 200 else None),
        "ma200_w": _pct(close, weekly_ma200),
    }

    direction = patterns.PATTERN_DIRECTION[pattern_name]

    # render charts
    daily_path = chart.render(df, row["code"], row["name"], row["market"],
                              focus_date=signal_date, pattern=pattern_name,
                              direction=direction, kind="daily")
    weekly_path = chart.render(df, row["code"], row["name"], row["market"],
                               focus_date=weekly_signal_date, pattern=pattern_name,
                               direction=direction, kind="weekly")
    charts = {
        "daily": f"charts/{daily_path.name}",
        "weekly": f"charts/{weekly_path.name}",
    }

    return {
        "code": row["yf_symbol"],
        "raw_code": row["code"],
        "market": row["market"],
        "kind": kind,
        "name": row["name"],
        "date": signal_date.isoformat() if kind == "daily" else weekly_signal_date.isoformat(),
        "close": round(close, 2),
        "pattern": pattern_name,
        "direction": direction,
        "rsi": round(float(rsi), 2) if pd.notna(rsi) else None,
        "ma_dist": ma_dist,
        "chart": charts["daily"],
        "chart_daily": charts["daily"],
        "chart_weekly": charts["weekly"],
        "charts": charts,
        "chart_focus_dates": {
            "daily": signal_date.isoformat(),
            "weekly": weekly_signal_date.isoformat(),
        },
    }


# ── Brief assembly ──────────────────────────────────────────────────────

def _passlist_filter(passlist: dict | None, kind: str) -> set[str]:
    if not passlist or kind not in passlist:
        return set(patterns.ALL_PATTERNS)
    return {p for p, info in passlist[kind].items() if info.get("pass")}


def _pretty_date(d: dt.date) -> str:
    return d.strftime("%A · %d %B %Y")


def generate(force_universe_refresh: bool = False) -> dict[int, Path]:
    today = dt.date.today()
    universe = tw_universe.load_or_build(force_refresh=force_universe_refresh)
    universe_top300 = universe.head(300)
    symbols = universe_top300["yf_symbol"].tolist()

    histories = fetch_latest_prices(symbols)
    if histories:
        big = pd.concat(
            [df.reset_index().assign(Symbol=sym) for sym, df in histories.items()],
            ignore_index=True,
        )
        big.to_parquet(PRICES_LATEST, index=False)

    passlist_full = event_study.load_passlist()
    daily_pass = _passlist_filter(passlist_full, "daily")
    weekly_pass = _passlist_filter(passlist_full, "weekly")

    # Determine signal dates from any one symbol that has fresh data
    sample = next(iter(histories.values()))
    sample_daily = cut_to_completed_bars(sample, today)
    if sample_daily.empty:
        raise RuntimeError("No completed daily bars in fetch — universe rebuild needed")
    daily_signal_date = sample_daily.index[-1].date()

    sample_weekly = cut_weekly_to_completed(resample_weekly(sample_daily), today)
    if sample_weekly.empty:
        raise RuntimeError("No completed weekly bars after cut")
    weekly_signal_date = sample_weekly.index[-1].date()

    LOG.info("daily_signal_date=%s  weekly_signal_date=%s", daily_signal_date, weekly_signal_date)

    # Compute per-symbol signals across the full Top 300, tag with rank,
    # so each universe size N is just a slice.
    per_symbol_signals: list[dict] = []  # {rank, signal_dict, kind}
    freshness_ok = freshness_fail = 0

    for _, urow in universe_top300.iterrows():
        sym = urow["yf_symbol"]
        df = histories.get(sym)
        if df is None or len(df) < 30:
            freshness_fail += 1
            continue
        df = cut_to_completed_bars(df, today)
        if df.empty:
            freshness_fail += 1
            continue
        weekly_df = cut_weekly_to_completed(resample_weekly(df), today)
        freshness_ok += 1

        row = urow.to_dict()

        for pname in patterns.ALL_PATTERNS:
            mask_d = patterns.DETECTORS[pname](df)
            if bool(mask_d.iloc[-1]) and pname in daily_pass:
                sig = build_signal(row, df, weekly_df, "daily", pname,
                                    daily_signal_date, weekly_signal_date)
                per_symbol_signals.append({"rank": int(row["rank"]), "kind": "daily", "sig": sig})

            if not weekly_df.empty:
                mask_w = patterns.DETECTORS[pname](weekly_df)
                if bool(mask_w.iloc[-1]) and pname in weekly_pass:
                    sig = build_signal(row, df, weekly_df, "weekly", pname,
                                        daily_signal_date, weekly_signal_date)
                    per_symbol_signals.append({"rank": int(row["rank"]), "kind": "weekly", "sig": sig})

    LOG.info("per_symbol_signals: %d (ok=%d fail=%d)",
             len(per_symbol_signals), freshness_ok, freshness_fail)

    written: dict[int, Path] = {}
    for n in UNIVERSE_SIZES:
        daily_signals = sorted(
            [x["sig"] for x in per_symbol_signals
             if x["kind"] == "daily" and x["rank"] <= n],
            key=lambda s: (s["direction"] != "買入", s["rsi"] if s["rsi"] is not None else 50)
        )
        weekly_signals = sorted(
            [x["sig"] for x in per_symbol_signals
             if x["kind"] == "weekly" and x["rank"] <= n],
            key=lambda s: (s["direction"] != "買入", s["rsi"] if s["rsi"] is not None else 50)
        )

        brief = {
            "universe_size": n,
            "generated_date": today.isoformat(),
            "generated_date_pretty": _pretty_date(today),
            "today": today.isoformat(),
            "today_pretty": _pretty_date(today),
            "signal_date": daily_signal_date.isoformat(),
            "signal_date_pretty": _pretty_date(daily_signal_date),
            "weekly_signal_date": weekly_signal_date.isoformat(),
            "weekly_signal_date_pretty": f"週始 {weekly_signal_date.strftime('%d %B %Y')}",
            "run_time": dt.datetime.now().strftime("%H:%M"),
            "freshness": {"ok": freshness_ok, "fail": freshness_fail,
                          "total": freshness_ok + freshness_fail, "cache_only": 0},
            "daily": daily_signals,
            "weekly": weekly_signals,
        }
        out = BRIEFS_DIR / f"brief_{n}.json"
        out.write_text(json.dumps(brief, ensure_ascii=False, indent=2))
        written[n] = out
        LOG.info("brief[%d]: daily=%d weekly=%d → %s", n,
                 len(daily_signals), len(weekly_signals), out)
    return written


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    generate()
