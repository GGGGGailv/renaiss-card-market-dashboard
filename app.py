from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from analytics.indicators import filter_time_range, prepare_history, summarize_trend
from components.charts import comparison_chart, market_distribution_chart, pack_trend_chart, price_history_chart
from components.metrics import format_number, format_percent, render_metric_grid, trend_badge
from components.tables import card_table, show_dataframe
from config import BASE_DIR, CONFIG, configure_logging
from database.connection import DatabaseManager
from database.repository import RenaissRepository
from services.card_service import CardService
from services.marketplace_service import MarketplaceService
from services.mock_data import MockDataProvider
from services.pack_service import PackService
from services.renaiss_cli import RenaissCLIClient, RenaissCLIError

configure_logging()
LOGGER = logging.getLogger(__name__)
SINGAPORE_TZ = ZoneInfo("Asia/Singapore")

st.set_page_config(
    page_title="Renaiss Card Market Dashboard",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
:root { --panel: rgba(24, 28, 43, .88); --border: rgba(138, 150, 190, .18); }
[data-testid="stAppViewContainer"] { background: radial-gradient(circle at 80% 0%, #1d2141 0%, #0b0e18 38%, #080a12 100%); }
[data-testid="stSidebar"] { background: rgba(10, 12, 22, .96); border-right: 1px solid var(--border); }
[data-testid="stMetric"] { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 14px 16px; }
[data-testid="stMetricValue"] { font-size: 1.55rem; }
.block-container { padding-top: 1.2rem; padding-bottom: 3rem; }
.dashboard-title { font-size: 2rem; font-weight: 800; letter-spacing: -.03em; margin: 0; }
.dashboard-subtitle { color: #9ca6c4; margin: .25rem 0 1rem 0; }
.status-pill { display:inline-block; padding: .28rem .65rem; border-radius: 999px; font-size:.82rem; background:rgba(89, 211, 167, .12); border:1px solid rgba(89,211,167,.3); }
.muted { color:#98a1bd; font-size:.9rem; }
.notice { padding:.75rem 1rem; border:1px solid var(--border); border-radius:12px; background:var(--panel); }
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_resource
def build_context() -> dict[str, Any]:
    database = DatabaseManager(CONFIG.database_path)
    repository = RenaissRepository(database)
    client = RenaissCLIClient()
    mock = MockDataProvider()
    return {
        "database": database,
        "repository": repository,
        "client": client,
        "mock": mock,
        "marketplace_service": MarketplaceService(client, repository, mock),
        "card_service": CardService(client, repository, mock),
        "pack_service": PackService(client, repository, mock),
    }


@st.cache_data(ttl=30, show_spinner=False)
def cached_market(_service: MarketplaceService, mock_mode: bool, allow_fallback: bool, refresh_nonce: int) -> dict[str, Any]:
    return _service.fetch(mock_mode=mock_mode, allow_fallback=allow_fallback)


@st.cache_data(ttl=30, show_spinner=False)
def cached_card(_service: CardService, token_id: str, mock_mode: bool, allow_fallback: bool, refresh_nonce: int) -> dict[str, Any]:
    return _service.fetch(token_id, mock_mode=mock_mode, allow_fallback=allow_fallback)


@st.cache_data(ttl=60, show_spinner=False)
def cached_pack_list(_service: PackService, mock_mode: bool, allow_fallback: bool, refresh_nonce: int) -> list[dict[str, Any]]:
    return _service.list(mock_mode=mock_mode, allow_fallback=allow_fallback)


@st.cache_data(ttl=60, show_spinner=False)
def cached_pack(_service: PackService, slug: str, mock_mode: bool, allow_fallback: bool, refresh_nonce: int) -> dict[str, Any]:
    return _service.get(slug, mock_mode=mock_mode, allow_fallback=allow_fallback)


context = build_context()
client: RenaissCLIClient = context["client"]
repository: RenaissRepository = context["repository"]

if "refresh_nonce" not in st.session_state:
    st.session_state.refresh_nonce = 0
if "last_update" not in st.session_state:
    st.session_state.last_update = None


def mark_updated() -> None:
    st.session_state.last_update = datetime.now(SINGAPORE_TZ)


def mode_settings(label: str) -> tuple[bool, bool, str]:
    installed = client.check_installation()
    if label == "模拟数据":
        return True, False, "模拟数据"
    if label == "真实 CLI":
        return False, False, "真实 CLI"
    if installed:
        return False, True, "自动 / CLI"
    return True, False, "自动 / 模拟数据"


def display_error(exc: Exception) -> None:
    LOGGER.exception("Dashboard request failed")
    if isinstance(exc, (RenaissCLIError, ValueError, RuntimeError)):
        message = str(exc)
    elif isinstance(exc, sqlite3.Error):
        message = "本地数据库暂时不可用，请检查 data 目录权限或稍后重试。"
    else:
        message = "处理数据时出现异常，详细信息已写入 logs/app.log。"
    st.error(message)


def load_market(mock_mode: bool, allow_fallback: bool) -> dict[str, Any] | None:
    try:
        data = cached_market(
            context["marketplace_service"],
            mock_mode,
            allow_fallback,
            st.session_state.refresh_nonce,
        )
        mark_updated()
        return data
    except Exception as exc:  # UI boundary: never expose a traceback.
        display_error(exc)
        return None


def load_card(token_id: str, mock_mode: bool, allow_fallback: bool) -> dict[str, Any] | None:
    try:
        data = cached_card(
            context["card_service"],
            token_id.strip(),
            mock_mode,
            allow_fallback,
            st.session_state.refresh_nonce,
        )
        mark_updated()
        return data
    except Exception as exc:
        display_error(exc)
        return None


def load_packs(mock_mode: bool, allow_fallback: bool) -> list[dict[str, Any]]:
    try:
        data = cached_pack_list(
            context["pack_service"], mock_mode, allow_fallback, st.session_state.refresh_nonce
        )
        mark_updated()
        return data
    except Exception as exc:
        display_error(exc)
        return []


def local_image(value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value)
    if path.exists():
        return str(path)
    candidate = BASE_DIR / value
    if candidate.exists():
        return str(candidate)
    return value


def merged_history(card: dict[str, Any]) -> pd.DataFrame:
    token_id = str(card.get("token_id") or "")
    database_history = repository.get_card_price_history(token_id)
    payload_history = prepare_history(card.get("price_history") or [])
    frames = [frame for frame in (database_history, payload_history) if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=["timestamp", "price", "source"])
    frame = pd.concat(frames, ignore_index=True, sort=False)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    return frame.dropna(subset=["timestamp", "price"]).sort_values("timestamp").drop_duplicates(subset=["timestamp", "price"], keep="last")


def format_source(data: dict[str, Any]) -> str:
    source = data.get("data_source") or data.get("parse_mode") or "unknown"
    mapping = {"cli": "真实 CLI", "mock": "模拟数据", "mock-fallback": "CLI 失败后模拟数据"}
    return mapping.get(str(source), str(source))


# Sidebar controls
st.sidebar.markdown("### ◈ Renaiss Dashboard")
page = st.sidebar.radio(
    "页面导航",
    ["市场概览", "单卡分析", "卡牌对比", "卡包分析", "数据与日志"],
)
mode_label = st.sidebar.selectbox(
    "数据模式",
    ["自动（CLI 不可用时使用模拟数据）", "真实 CLI", "模拟数据"],
    index=0,
)
mock_mode, allow_fallback, mode_display = mode_settings(mode_label)

st.sidebar.divider()
auto_refresh = st.sidebar.toggle("自动刷新", value=False)
interval_label = st.sidebar.selectbox("刷新间隔", ["30 秒", "1 分钟", "5 分钟", "15 分钟"], index=1, disabled=not auto_refresh)
interval_ms = {"30 秒": 30_000, "1 分钟": 60_000, "5 分钟": 300_000, "15 分钟": 900_000}[interval_label]
if auto_refresh:
    try:
        from streamlit_autorefresh import st_autorefresh

        st_autorefresh(interval=interval_ms, limit=None, key="renaiss_auto_refresh")
    except ImportError:
        st.sidebar.warning("未安装 streamlit-autorefresh，自动刷新暂不可用。")

if st.sidebar.button("立即刷新", type="primary", use_container_width=True):
    st.cache_data.clear()
    st.session_state.refresh_nonce += 1
    st.rerun()

installed = client.check_installation()
db_status = context["database"].status()
st.sidebar.divider()
st.sidebar.markdown(f"CLI 状态：{'🟢 已连接' if installed else '🟠 未安装'}")
st.sidebar.markdown(f"当前模式：**{mode_display}**")
st.sidebar.markdown(f"数据库：{'🟢 正常' if db_status.get('ok') else '🔴 异常'}")
last_update = st.session_state.last_update
st.sidebar.caption(f"最近更新：{last_update.strftime('%Y-%m-%d %H:%M:%S') if last_update else '尚未查询'}")

# Header
header_left, header_right = st.columns([4, 1.35])
with header_left:
    st.markdown('<p class="dashboard-title">Renaiss Card Market Dashboard</p>', unsafe_allow_html=True)
    st.markdown('<p class="dashboard-subtitle">实时价格追踪、历史曲线、趋势分析与本地快照</p>', unsafe_allow_html=True)
with header_right:
    status_text = "CLI 已连接" if installed else "模拟预览可用"
    st.markdown(f'<div class="status-pill">● {status_text}</div>', unsafe_allow_html=True)
    st.caption(f"刷新缓存：{CONFIG.default_cache_ttl_seconds} 秒")


if page == "市场概览":
    market = load_market(mock_mode, allow_fallback)
    if market:
        if market.get("fallback_reason"):
            st.warning(f"真实 CLI 调用失败，已自动切换模拟数据：{market['fallback_reason']}")
        cards = pd.DataFrame(market.get("cards") or [])
        sales = pd.DataFrame(market.get("recent_sales") or [])
        if cards.empty:
            if market.get("parse_errors"):
                st.info("CLI 已返回数据，但解析器未识别出卡牌列表。可在“数据与日志”页面查看原始输出。")
            else:
                st.info("CLI 返回的 marketplace collection 为空，当前没有可显示的卡牌。")
        else:
            st.caption(f"数据来源：{format_source(market)} · 解析方式：{market.get('parse_mode', 'unknown')}")

            # Local filters remain available even when the installed CLI exposes no filter flags.
            with st.expander("市场筛选", expanded=True):
                c1, c2, c3, c4 = st.columns(4)
                packs = sorted(cards.get("pack_slug", pd.Series(dtype=str)).dropna().astype(str).unique().tolist())
                rarities = sorted(cards.get("rarity", pd.Series(dtype=str)).dropna().astype(str).unique().tolist())
                selected_pack = c1.selectbox("卡包", ["全部", *packs])
                name_query = c2.text_input("卡牌名称", placeholder="输入名称关键词")
                selected_rarity = c3.selectbox("稀有度", ["全部", *rarities])
                listed_filter = c4.selectbox("上架状态", ["全部", "在售", "未上架"])

                prices = pd.to_numeric(cards.get("current_price", pd.Series(dtype=float)), errors="coerce").dropna()
                max_price = float(prices.max()) if not prices.empty else 1.0
                price_range = st.slider("价格区间", min_value=0.0, max_value=max(max_price, 1.0), value=(0.0, max(max_price, 1.0)))
                sort_choice = st.selectbox("排序方式", ["价格从低到高", "价格从高到低", "24h 涨幅", "24h 跌幅", "Token ID"])
                sales_range = st.selectbox("最近成交时间范围", ["24 小时", "7 天", "30 天", "全部"])

            filtered = cards.copy()
            if selected_pack != "全部":
                filtered = filtered[filtered["pack_slug"] == selected_pack]
            if name_query:
                filtered = filtered[filtered["name"].fillna("").str.contains(name_query, case=False, regex=False)]
            if selected_rarity != "全部":
                filtered = filtered[filtered["rarity"] == selected_rarity]
            if listed_filter != "全部" and "is_listed" in filtered:
                target = listed_filter == "在售"
                filtered = filtered[filtered["is_listed"].fillna(False).astype(bool) == target]
            filtered["current_price"] = pd.to_numeric(filtered.get("current_price"), errors="coerce")
            filtered = filtered[
                filtered["current_price"].between(price_range[0], price_range[1], inclusive="both")
                | filtered["current_price"].isna()
            ]
            sort_map = {
                "价格从低到高": ("current_price", True), "价格从高到低": ("current_price", False),
                "24h 涨幅": ("change_24h", False), "24h 跌幅": ("change_24h", True), "Token ID": ("token_id", True),
            }
            sort_column, ascending = sort_map[sort_choice]
            if sort_column in filtered:
                filtered = filtered.sort_values(sort_column, ascending=ascending, na_position="last")

            listed_cards = filtered[filtered.get("is_listed", False).fillna(False).astype(bool)] if "is_listed" in filtered else filtered.iloc[0:0]
            listed_prices = pd.to_numeric(listed_cards.get("current_price", pd.Series(dtype=float)), errors="coerce").dropna()
            summary = market.get("summary") or {}
            sales_count = int(summary.get("sales_24h") or len(sales))
            sales_volume = float(summary.get("volume_24h") or pd.to_numeric(sales.get("price", pd.Series(dtype=float)), errors="coerce").sum())
            gainers = filtered.dropna(subset=["change_24h"]).sort_values("change_24h", ascending=False) if "change_24h" in filtered else pd.DataFrame()
            losers = filtered.dropna(subset=["change_24h"]).sort_values("change_24h", ascending=True) if "change_24h" in filtered else pd.DataFrame()
            top_gainer = f"{gainers.iloc[0]['name']} {format_percent(gainers.iloc[0]['change_24h'])}" if not gainers.empty else "—"
            top_loser = f"{losers.iloc[0]['name']} {format_percent(losers.iloc[0]['change_24h'])}" if not losers.empty else "—"

            render_metric_grid(
                [
                    ("市场卡牌数量", f"{len(filtered):,}", None),
                    ("在售卡牌数量", f"{len(listed_cards):,}", None),
                    ("市场最低价", format_number(listed_prices.min() if not listed_prices.empty else None), None),
                    ("平均价格", format_number(listed_prices.mean() if not listed_prices.empty else None), None),
                    ("中位数价格", format_number(listed_prices.median() if not listed_prices.empty else None), None),
                    ("24h 成交数量", f"{sales_count:,}", None),
                    ("24h 成交额", format_number(sales_volume), None),
                    ("涨幅最大", top_gainer, None),
                    ("跌幅最大", top_loser, None),
                ],
                columns=4,
            )

            chart_col, list_col = st.columns([1.15, 1])
            with chart_col:
                st.plotly_chart(market_distribution_chart(filtered), use_container_width=True, config={"displaylogo": False})
            with list_col:
                st.subheader("卡牌价格列表")
                card_table(filtered.to_dict("records"), key="market_cards")

            st.subheader("最近成交记录")
            if not sales.empty and "timestamp" in sales:
                sales["timestamp"] = pd.to_datetime(sales["timestamp"], utc=True, errors="coerce")
                range_map = {"24 小时": timedelta(hours=24), "7 天": timedelta(days=7), "30 天": timedelta(days=30)}
                if sales_range in range_map:
                    cutoff = pd.Timestamp.now(tz="UTC") - range_map[sales_range]
                    sales = sales[sales["timestamp"] >= cutoff]
                sales = sales.sort_values("timestamp", ascending=False)
                visible = [col for col in ["timestamp", "token_id", "name", "price", "seller", "buyer", "type"] if col in sales]
                show_dataframe(sales[visible], height=320, key="recent_sales")
            else:
                st.info("暂无最近成交记录。")


elif page == "单卡分析":
    token_id = st.sidebar.text_input("Token ID", value="1001", help="模拟模式可使用 1001–1030")
    time_range = st.sidebar.selectbox("价格时间范围", ["24 小时", "7 天", "30 天", "90 天", "全部"], index=2)
    card = load_card(token_id, mock_mode, allow_fallback) if token_id.strip() else None
    if card:
        if card.get("fallback_reason"):
            st.warning(f"真实 CLI 调用失败，已自动使用模拟数据：{card['fallback_reason']}")
        history_all = merged_history(card)
        history = filter_time_range(history_all, time_range)
        activities = pd.DataFrame(card.get("activities") or [])
        trend = summarize_trend(history_all, activities)
        prices = history_all["price"] if not history_all.empty else pd.Series(dtype=float)

        image_col, detail_col = st.columns([1, 3])
        with image_col:
            image = local_image(card.get("image_url"))
            if image:
                try:
                    st.image(image, use_container_width=True)
                except Exception:
                    st.info("卡牌图片暂时无法加载。")
            else:
                st.info("暂无卡牌图片。")
        with detail_col:
            st.subheader(card.get("name") or f"Token #{card.get('token_id')}")
            st.caption(f"Token ID: {card.get('token_id')} · 数据来源：{format_source(card)}")
            st.markdown(f"**趋势状态：{trend_badge(trend['trend'])}**")
            render_metric_grid(
                [
                    ("当前售价", format_number(card.get("current_price")), format_percent(trend.get("change_24h"))),
                    ("最近成交价", format_number(card.get("last_sale_price")), None),
                    ("历史最低价", format_number(prices.min() if not prices.empty else None), None),
                    ("历史最高价", format_number(prices.max() if not prices.empty else None), None),
                    ("历史平均价", format_number(prices.mean() if not prices.empty else None), None),
                    ("7 天涨跌幅", format_percent(trend.get("change_7d")), None),
                    ("30 天涨跌幅", format_percent(trend.get("change_30d")), None),
                    ("波动率", format_number(trend.get("volatility"), suffix="%"), None),
                ], columns=4,
            )
            info = pd.DataFrame(
                [
                    ["所属卡包", card.get("pack_slug") or "—"], ["稀有度", card.get("rarity") or "—"],
                    ["当前持有者", card.get("owner") or "—"], ["上架状态", "在售" if card.get("is_listed") else "未上架"],
                ], columns=["字段", "内容"]
            )
            st.dataframe(info, hide_index=True, use_container_width=True)

        st.plotly_chart(
            price_history_chart(history, title=f"{card.get('name') or token_id} · {time_range}价格走势"),
            use_container_width=True,
            config={"displaylogo": False, "scrollZoom": True},
        )

        st.subheader("趋势分析")
        render_metric_grid(
            [
                ("7 日移动平均价", format_number(trend.get("ma_7d")), None),
                ("30 日移动平均价", format_number(trend.get("ma_30d")), None),
                ("成交频率", format_number(trend.get("transaction_frequency"), suffix=" 次/日"), None),
                ("市场活跃度", format_number(trend.get("market_activity"), suffix=" / 100"), None),
                ("当前价相对历史均价", format_percent(trend.get("price_vs_average")), None),
                ("综合趋势", trend_badge(trend.get("trend", "数据不足")), None),
            ], columns=3,
        )
        st.caption("趋势判断仅为历史数据统计结果，不构成投资建议。")

        tab1, tab2 = st.tabs(["活动历史", "成交/价格历史"])
        with tab1:
            activity_frame = repository.get_card_activities(str(card.get("token_id")))
            if activity_frame.empty:
                activity_frame = activities
            show_dataframe(activity_frame, height=360, key="card_activities")
        with tab2:
            show_dataframe(history_all.sort_values("timestamp", ascending=False), height=360, key="card_history")


elif page == "卡牌对比":
    market = load_market(mock_mode, allow_fallback)
    if market:
        cards = market.get("cards") or []
        label_to_id = {f"{card.get('name') or 'Unknown'} · #{card.get('token_id')}": str(card.get("token_id")) for card in cards if card.get("token_id")}
        defaults = list(label_to_id)[:3]
        selected_labels = st.multiselect("选择 2–5 张卡牌", list(label_to_id), default=defaults, max_selections=5)
        if len(selected_labels) < 2:
            st.info("请选择至少 2 张卡牌进行对比。")
        else:
            comparison_rows: list[dict[str, Any]] = []
            series: dict[str, pd.DataFrame] = {}
            for label in selected_labels:
                token_id = label_to_id[label]
                card = load_card(token_id, mock_mode, allow_fallback)
                if not card:
                    continue
                history = merged_history(card)
                trend = summarize_trend(history, card.get("activities") or [])
                prices = history["price"] if not history.empty else pd.Series(dtype=float)
                name = f"{card.get('name') or token_id} (#{token_id})"
                series[name] = history
                comparison_rows.append(
                    {
                        "卡牌": name,
                        "当前价格": card.get("current_price"),
                        "历史平均价": float(prices.mean()) if not prices.empty else None,
                        "7 天涨跌幅(%)": trend.get("change_7d"),
                        "30 天涨跌幅(%)": trend.get("change_30d"),
                        "历史最高价": float(prices.max()) if not prices.empty else None,
                        "历史最低价": float(prices.min()) if not prices.empty else None,
                        "波动率(%)": trend.get("volatility"),
                        "成交次数": len(card.get("activities") or []),
                        "综合趋势": trend.get("trend"),
                    }
                )
            show_dataframe(pd.DataFrame(comparison_rows), height=300, key="comparison_metrics")
            raw_tab, normalized_tab = st.tabs(["原始价格曲线", "归一化价格曲线"])
            with raw_tab:
                st.plotly_chart(comparison_chart(series, normalized=False), use_container_width=True, config={"displaylogo": False})
            with normalized_tab:
                st.plotly_chart(comparison_chart(series, normalized=True), use_container_width=True, config={"displaylogo": False})
                st.caption("归一化曲线将每张卡牌的首个有效价格设为 100，用于比较相对涨跌，不能代表绝对价值。")


elif page == "卡包分析":
    packs = load_packs(mock_mode, allow_fallback)
    if packs:
        pack_frame = pd.DataFrame(packs)
        st.subheader("卡包列表")
        wanted = [column for column in ["name", "slug", "card_count", "floor_price", "average_price", "market_cap"] if column in pack_frame]
        show_dataframe(pack_frame[wanted], height=260, key="pack_list")
        slugs = [str(pack.get("slug")) for pack in packs if pack.get("slug")]
        selected_slug = st.selectbox("选择卡包", slugs)
        try:
            pack = cached_pack(
                context["pack_service"], selected_slug, mock_mode, allow_fallback, st.session_state.refresh_nonce
            )
            mark_updated()
        except Exception as exc:
            display_error(exc)
            pack = None
        if pack:
            st.subheader(pack.get("name") or selected_slug)
            render_metric_grid(
                [
                    ("卡牌数量", f"{int(pack.get('card_count') or len(pack.get('cards') or [])):,}", None),
                    ("卡包最低价", format_number(pack.get("floor_price")), None),
                    ("卡包平均价", format_number(pack.get("average_price")), None),
                    ("卡包总市值", format_number(pack.get("market_cap")), None),
                ], columns=4,
            )
            st.plotly_chart(
                pack_trend_chart(pack.get("price_history") or [], f"{pack.get('name') or selected_slug} · 卡包平均价格趋势"),
                use_container_width=True,
                config={"displaylogo": False},
            )
            cards = pd.DataFrame(pack.get("cards") or [])
            if not cards.empty:
                cards["current_price"] = pd.to_numeric(cards.get("current_price"), errors="coerce")
                cards = cards.sort_values("current_price", ascending=False, na_position="last")
                hot = cards.head(5)[[col for col in ["token_id", "name", "rarity", "current_price", "change_24h"] if col in cards]]
                st.subheader("热门卡牌 / 价格排名")
                show_dataframe(hot, height=230, key="hot_cards")
                card_table(cards.to_dict("records"), key="pack_cards")
            else:
                st.info("该卡包详情中暂无可识别的卡牌列表。")


elif page == "数据与日志":
    status_col, count_col = st.columns([1, 2])
    with status_col:
        st.subheader("运行状态")
        st.json(
            {
                "cli_installed": installed,
                "cli_binary": client.binary,
                "cli_resolved_path": client.resolve_binary(),
                "selected_mode": mode_display,
                "database": context["database"].status(),
                "database_counts": repository.table_counts(),
            },
            expanded=True,
        )
    with count_col:
        st.subheader("市场快照")
        show_dataframe(repository.recent_market_snapshots(100), height=330, key="market_snapshots")

    help_tab, log_tab, raw_tab = st.tabs(["CLI 帮助探测", "运行日志", "原始数据检查"])
    with help_tab:
        if not installed:
            st.info("当前 PATH 中未找到 Renaiss CLI。安装后重新启动应用，即可自动执行 marketplace/card/packs --help。")
        elif st.button("读取三个子命令帮助"):
            try:
                diagnostics = client.diagnostics()
                st.json(diagnostics, expanded=False)
                for command, help_text in diagnostics.get("help", {}).items():
                    with st.expander(f"renaiss {command} --help"):
                        st.code(help_text, language="text")
            except Exception as exc:
                display_error(exc)
    with log_tab:
        try:
            lines = CONFIG.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            st.code("\n".join(lines[-CONFIG.max_log_lines:]) or "日志文件为空。", language="text")
        except OSError:
            st.info("日志文件暂时无法读取。")
    with raw_tab:
        market = load_market(mock_mode, allow_fallback)
        if market:
            st.caption(f"解析方式：{market.get('parse_mode')} · 数据来源：{format_source(market)}")
            st.code(RenaissCLIClient.raw_as_text(market.get("raw_data")), language="json")
            if market.get("parse_errors"):
                st.warning("；".join(market["parse_errors"]))

st.divider()
st.caption("Renaiss Card Market Dashboard · 本工具展示统计分析结果，不构成投资建议。")
