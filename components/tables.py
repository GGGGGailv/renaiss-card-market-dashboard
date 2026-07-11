from __future__ import annotations

import pandas as pd
import streamlit as st


def show_dataframe(frame: pd.DataFrame, *, height: int = 420, key: str | None = None) -> None:
    if frame.empty:
        st.info("暂无可展示的数据。")
        return
    st.dataframe(frame, use_container_width=True, hide_index=True, height=height, key=key)


def card_table(cards: list[dict], *, key: str | None = None) -> None:
    frame = pd.DataFrame(cards)
    if frame.empty:
        st.info("暂无卡牌数据。")
        return
    wanted = [
        column for column in [
            "token_id", "name", "pack_slug", "rarity", "current_price", "last_sale_price",
            "change_24h", "is_listed", "owner",
        ] if column in frame.columns
    ]
    display = frame[wanted].copy()
    rename = {
        "token_id": "Token ID", "name": "卡牌", "pack_slug": "卡包", "rarity": "稀有度",
        "current_price": "当前价格", "last_sale_price": "最近成交价", "change_24h": "24h 涨跌幅(%)",
        "is_listed": "在售", "owner": "持有者",
    }
    show_dataframe(display.rename(columns=rename), key=key)
