"""Pre-render Plotly candlestick charts to standalone HTML.

The brief JSON points the front-end at one of these files; opening the modal
just iframes / fetches the HTML. We embed the full Plotly bundle once and the
front-end can zoom, drag-select, and fit the y-axis without any extra calls."""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

LOG = logging.getLogger(__name__)

CHART_DIR = Path(__file__).parent / "data" / "charts"
CHART_DIR.mkdir(parents=True, exist_ok=True)

INCLUDE_PLOTLY = "cdn"  # 'cdn' = small files; 'inline' for offline use


def chart_filename(code: str, market: str, kind: str, focus_date: dt.date) -> str:
    suffix = "TW" if market == "TWSE" else "TWO"
    return f"{code}_{suffix}_{kind}_{focus_date.strftime('%Y%m%d')}.html"


def _resample_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """Daily OHLCV → weekly, anchored to Friday close."""
    rule = "W-FRI"
    weekly = pd.DataFrame({
        "Open": daily["Open"].resample(rule).first(),
        "High": daily["High"].resample(rule).max(),
        "Low": daily["Low"].resample(rule).min(),
        "Close": daily["Close"].resample(rule).last(),
        "Volume": daily["Volume"].resample(rule).sum(),
    }).dropna(how="all")
    return weekly


def _figure(df: pd.DataFrame, title: str, focus_idx: int, direction: str) -> go.Figure:
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.78, 0.22],
        vertical_spacing=0.03,
    )
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            increasing_line_color="#c0392b",
            decreasing_line_color="#1f8a4c",
            increasing_fillcolor="#c0392b",
            decreasing_fillcolor="#1f8a4c",
            name="K",
        ),
        row=1,
        col=1,
    )
    for win, color in [(20, "#888"), (50, "#5a7ca8"), (200, "#b58c4d")]:
        if len(df) >= win:
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df["Close"].rolling(win).mean(),
                    name=f"MA{win}",
                    line={"color": color, "width": 1},
                    hovertemplate=f"MA{win}: %{{y:.2f}}<extra></extra>",
                ),
                row=1,
                col=1,
            )
    bar_colors = ["#c0392b" if c >= o else "#1f8a4c"
                  for c, o in zip(df["Close"], df["Open"])]
    fig.add_trace(
        go.Bar(
            x=df.index,
            y=df["Volume"],
            marker_color=bar_colors,
            name="Vol",
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    if 0 <= focus_idx < len(df):
        focus_date = df.index[focus_idx]
        focus_close = df["Close"].iloc[focus_idx]
        marker_color = "#c0392b" if direction == "買入" else "#1f8a4c"
        fig.add_annotation(
            x=focus_date,
            y=focus_close,
            text="◆",
            showarrow=False,
            font={"size": 18, "color": marker_color},
            row=1,
            col=1,
        )
        fig.add_vline(
            x=focus_date,
            line={"color": marker_color, "width": 1, "dash": "dot"},
            opacity=0.35,
        )

    fig.update_layout(
        title={"text": title, "x": 0.02, "font": {"size": 14}},
        margin={"l": 40, "r": 20, "t": 36, "b": 30},
        xaxis_rangeslider_visible=False,
        height=520,
        plot_bgcolor="#fafafa",
        paper_bgcolor="#fff",
        showlegend=False,
        dragmode="zoom",
    )
    fig.update_xaxes(rangebreaks=[{"bounds": ["sat", "mon"]}])
    fig.update_yaxes(title_text="", tickformat=".2f", row=1, col=1)
    fig.update_yaxes(title_text="", showticklabels=False, row=2, col=1)
    return fig


def render(daily: pd.DataFrame, code: str, name: str, market: str, focus_date: dt.date,
           pattern: str, direction: str, kind: str = "daily") -> Path:
    if kind == "weekly":
        df = _resample_weekly(daily)
    else:
        df = daily

    df = df.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    if df.empty:
        raise ValueError("Empty frame after cleaning")

    target = pd.Timestamp(focus_date)
    if kind == "weekly":
        # last weekly bar at or before focus_date
        diffs = df.index - target
        idx_pos = (df.index <= target + pd.Timedelta(days=1))
        focus_idx = idx_pos.sum() - 1 if idx_pos.any() else len(df) - 1
    else:
        if target in df.index:
            focus_idx = df.index.get_loc(target)
        else:
            focus_idx = len(df) - 1

    title = f"{code} {name} · {pattern} · {kind}"
    fig = _figure(df, title, focus_idx, direction)
    out = CHART_DIR / chart_filename(code, market, kind, focus_date)
    fig.write_html(out, include_plotlyjs=INCLUDE_PLOTLY, full_html=True, config={"displaylogo": False})
    return out
