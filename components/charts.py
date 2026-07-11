from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from analytics.indicators import add_moving_averages, normalize_price_series, prepare_history

PLOT_LAYOUT = {
    "template": "plotly_dark",
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
    "margin": {"l": 20, "r": 20, "t": 50, "b": 20},
    "hovermode": "x unified",
    "legend": {"orientation": "h", "y": 1.08, "x": 0},
}


def price_history_chart(
    history: pd.DataFrame | list[dict[str, Any]],
    *,
    title: str = "价格走势",
    show_moving_averages: bool = True,
    mark_extremes: bool = True,
) -> go.Figure:
    frame = add_moving_averages(history)
    figure = go.Figure()
    if frame.empty:
        figure.update_layout(**PLOT_LAYOUT, title=title)
        figure.add_annotation(text="暂无历史价格数据", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
        return figure

    figure.add_trace(
        go.Scatter(
            x=frame["timestamp"],
            y=frame["price"],
            mode="lines+markers",
            name="成交/快照价格",
            line={"width": 2.4},
            marker={"size": 5},
            customdata=frame.get("source"),
            hovertemplate="%{x|%Y-%m-%d %H:%M}<br>价格 %{y:.4f}<extra></extra>",
        )
    )
    if show_moving_averages:
        if frame["ma_7d"].notna().any():
            figure.add_trace(go.Scatter(x=frame["timestamp"], y=frame["ma_7d"], mode="lines", name="7 日均线", line={"dash": "dash"}))
        if frame["ma_30d"].notna().any():
            figure.add_trace(go.Scatter(x=frame["timestamp"], y=frame["ma_30d"], mode="lines", name="30 日均线", line={"dash": "dot"}))

    if mark_extremes:
        low_index = frame["price"].idxmin()
        high_index = frame["price"].idxmax()
        for index, label in ((high_index, "最高价"), (low_index, "最低价")):
            row = frame.loc[index]
            figure.add_trace(
                go.Scatter(
                    x=[row["timestamp"]],
                    y=[row["price"]],
                    mode="markers+text",
                    name=label,
                    text=[f"{label} {row['price']:.4f}"],
                    textposition="top center" if label == "最高价" else "bottom center",
                    marker={"size": 11, "symbol": "diamond"},
                    hovertemplate=f"{label}<br>%{{x|%Y-%m-%d %H:%M}}<br>%{{y:.4f}}<extra></extra>",
                )
            )

    figure.update_layout(**PLOT_LAYOUT, title=title, xaxis_title="时间", yaxis_title="价格", dragmode="zoom")
    figure.update_xaxes(rangeslider_visible=True)
    return figure


def market_distribution_chart(cards: pd.DataFrame) -> go.Figure:
    frame = cards.copy()
    if "current_price" not in frame.columns:
        frame["current_price"] = pd.Series(dtype=float)
    frame["current_price"] = pd.to_numeric(frame["current_price"], errors="coerce")
    frame = frame.dropna(subset=["current_price"])
    if frame.empty:
        figure = go.Figure()
        figure.update_layout(**PLOT_LAYOUT, title="市场价格分布")
        figure.add_annotation(text="暂无在售价格", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
        return figure
    figure = px.histogram(frame, x="current_price", color="rarity" if "rarity" in frame.columns else None, nbins=24, title="市场价格分布")
    figure.update_layout(**PLOT_LAYOUT, xaxis_title="价格", yaxis_title="卡牌数量", bargap=0.08)
    return figure


def comparison_chart(series_by_name: dict[str, pd.DataFrame], *, normalized: bool = False) -> go.Figure:
    figure = go.Figure()
    for name, history in series_by_name.items():
        frame = normalize_price_series(history) if normalized else prepare_history(history)
        y_column = "normalized" if normalized else "price"
        if frame.empty:
            continue
        figure.add_trace(
            go.Scatter(
                x=frame["timestamp"],
                y=frame[y_column],
                mode="lines",
                name=name,
                hovertemplate="%{x|%Y-%m-%d %H:%M}<br>%{y:.2f}<extra></extra>",
            )
        )
    title = "归一化价格曲线（首个有效价格 = 100）" if normalized else "原始价格曲线"
    y_title = "归一化指数" if normalized else "价格"
    figure.update_layout(**PLOT_LAYOUT, title=title, xaxis_title="时间", yaxis_title=y_title)
    return figure


def pack_trend_chart(history: pd.DataFrame | list[dict[str, Any]], title: str) -> go.Figure:
    return price_history_chart(history, title=title, show_moving_averages=False, mark_extremes=False)
