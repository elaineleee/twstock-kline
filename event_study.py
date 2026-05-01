"""5-year event study on Taiwan Top-100 universe.

For every pattern × horizon combination, measure the after-cost long-side or
short-side return distribution, then keep patterns with N≥30 and |t|>2 in the
expected direction. The morning brief filters out any pattern that doesn't
appear in the resulting passlist."""
from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

import patterns
import tw_universe

LOG = logging.getLogger(__name__)

ROOT = Path(__file__).parent
PRICES_DIR = ROOT / "data" / "prices"
PRICES_DIR.mkdir(parents=True, exist_ok=True)
PASSLIST_PATH = ROOT / "data" / "pattern_passlist.json"

# ── Gate settings ──────────────────────────────────────────────────────
MIN_SAMPLES = 30
MIN_T_STAT = 2.0
ROUND_TRIP_COST = 0.00585  # 0.1425% × 2 fee + 0.3% transaction tax = 0.585%
HORIZONS = (1, 3, 5, 20)
GATE_HORIZON = 5  # days used for the pass/fail decision
LOOKBACK_YEARS = 5
TOP_FOR_STUDY = 100


def _bulk_history(symbols: list[str], years: int) -> dict[str, pd.DataFrame]:
    end = dt.date.today() + dt.timedelta(days=1)
    start = end - dt.timedelta(days=int(years * 365.25) + 30)
    LOG.info("yfinance bulk download: %d symbols × %d years", len(symbols), years)
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


def _resample_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    rule = "W-FRI"
    return pd.DataFrame({
        "Open": daily["Open"].resample(rule).first(),
        "High": daily["High"].resample(rule).max(),
        "Low": daily["Low"].resample(rule).min(),
        "Close": daily["Close"].resample(rule).last(),
        "Volume": daily["Volume"].resample(rule).sum(),
    }).dropna(how="all")


def _forward_returns(close: pd.Series, h: int) -> pd.Series:
    return close.shift(-h) / close - 1.0


def _aggregate(symbol_dfs: dict[str, pd.DataFrame]) -> dict:
    """Run all patterns × all symbols, collect per-trigger forward returns."""
    by_pattern: dict[str, dict[int, list[float]]] = {
        p: {h: [] for h in HORIZONS} for p in patterns.ALL_PATTERNS
    }
    for sym, df in symbol_dfs.items():
        if len(df) < 220:
            continue
        flags = patterns.detect_all(df)
        fwd = {h: _forward_returns(df["Close"], h) for h in HORIZONS}
        for pname, mask in flags.items():
            mask = mask.astype(bool)
            if not mask.any():
                continue
            for h in HORIZONS:
                vals = fwd[h][mask].dropna().tolist()
                by_pattern[pname][h].extend(vals)
    return by_pattern


def _stats_block(returns: list[float], direction: str) -> dict:
    if not returns:
        return {"n": 0, "mean_gross": 0.0, "mean_net": 0.0, "t": 0.0, "p": 1.0,
                "win_rate": 0.0, "std": 0.0}
    arr = np.asarray(returns, dtype=float)
    sign = 1.0 if direction == "買入" else -1.0
    net = sign * arr - ROUND_TRIP_COST
    mean_gross = float(arr.mean())
    mean_net = float(net.mean())
    std = float(net.std(ddof=1)) if len(net) > 1 else 0.0
    t = mean_net / (std / np.sqrt(len(net))) if std > 0 else 0.0
    p = float(2 * (1 - stats.t.cdf(abs(t), df=max(len(net) - 1, 1))))
    win = float((net > 0).mean())
    return {
        "n": int(len(net)),
        "mean_gross": round(mean_gross, 5),
        "mean_net": round(mean_net, 5),
        "t": round(float(t), 3),
        "p": round(p, 4),
        "win_rate": round(win, 3),
        "std": round(std, 5),
    }


def _gate(by_pattern: dict[str, dict[int, list[float]]]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for pname, by_h in by_pattern.items():
        direction = patterns.PATTERN_DIRECTION[pname]
        horizons = {f"h{h}": _stats_block(by_h[h], direction) for h in HORIZONS}
        gate = horizons[f"h{GATE_HORIZON}"]
        passes = (gate["n"] >= MIN_SAMPLES
                  and abs(gate["t"]) >= MIN_T_STAT
                  and gate["mean_net"] > 0)
        out[pname] = {
            "direction": direction,
            "pass": bool(passes),
            "gate_horizon": GATE_HORIZON,
            **horizons,
        }
    return out


def run_study(force_refresh: bool = False) -> dict:
    universe = tw_universe.load_or_build()
    top = universe.head(TOP_FOR_STUDY)
    symbols = top["yf_symbol"].tolist()

    cache_path = PRICES_DIR / f"top{TOP_FOR_STUDY}_{LOOKBACK_YEARS}y.parquet"
    if cache_path.exists() and not force_refresh:
        LOG.info("Loading cached price panel: %s", cache_path)
        big = pd.read_parquet(cache_path)
        symbol_dfs = {sym: g.drop(columns=["Symbol"]).set_index("Date").sort_index()
                      for sym, g in big.groupby("Symbol")}
    else:
        symbol_dfs = _bulk_history(symbols, LOOKBACK_YEARS)
        rows = []
        for sym, df in symbol_dfs.items():
            tmp = df.reset_index().rename(columns={"index": "Date"})
            if "Date" not in tmp.columns:
                tmp = tmp.rename(columns={tmp.columns[0]: "Date"})
            tmp["Symbol"] = sym
            rows.append(tmp)
        if rows:
            pd.concat(rows, ignore_index=True).to_parquet(cache_path, index=False)
            LOG.info("Cached price panel → %s", cache_path)

    LOG.info("Running daily aggregate over %d symbols", len(symbol_dfs))
    daily_by_pattern = _aggregate(symbol_dfs)
    daily_passlist = _gate(daily_by_pattern)

    LOG.info("Running weekly aggregate")
    weekly_dfs = {sym: _resample_weekly(df) for sym, df in symbol_dfs.items()}
    weekly_by_pattern = _aggregate(weekly_dfs)
    weekly_passlist = _gate(weekly_by_pattern)

    result = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "top_for_study": TOP_FOR_STUDY,
        "lookback_years": LOOKBACK_YEARS,
        "min_samples": MIN_SAMPLES,
        "min_t_stat": MIN_T_STAT,
        "round_trip_cost": ROUND_TRIP_COST,
        "gate_horizon_days": GATE_HORIZON,
        "daily": daily_passlist,
        "weekly": weekly_passlist,
    }
    PASSLIST_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    LOG.info("Wrote passlist → %s", PASSLIST_PATH)
    return result


def load_passlist() -> dict | None:
    if not PASSLIST_PATH.exists():
        return None
    return json.loads(PASSLIST_PATH.read_text())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    res = run_study(force_refresh=True)
    print()
    for kind in ("daily", "weekly"):
        print(f"── {kind} ──")
        for pname, d in res[kind].items():
            gate_h = d[f"h{GATE_HORIZON}"]
            mark = "✓" if d["pass"] else "✗"
            print(f"  {mark} {pname:5s}  n={gate_h['n']:5d}  mean_net={gate_h['mean_net']:+.4f}  "
                  f"t={gate_h['t']:+.2f}  win={gate_h['win_rate']:.2f}")
