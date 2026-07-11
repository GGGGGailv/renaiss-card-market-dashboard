from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st


def format_number(value: Any, decimals: int = 2, suffix: str = "") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:,.{decimals}f}{suffix}"


def format_percent(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return f"{float(value):+.2f}%"


def render_metric_grid(items: list[tuple[str, Any, Any | None]], columns: int = 4) -> None:
    for start in range(0, len(items), columns):
        cols = st.columns(columns)
        for col, item in zip(cols, items[start : start + columns]):
            label, value, delta = item
            with col:
                st.metric(label, value, delta=delta)


def trend_badge(trend: str) -> str:
    icon = {
        "上升趋势": "↗",
        "下降趋势": "↘",
        "震荡": "↔",
        "数据不足": "…",
    }.get(trend, "•")
    return f"{icon} {trend}"
