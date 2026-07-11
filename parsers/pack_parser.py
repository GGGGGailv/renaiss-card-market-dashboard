from __future__ import annotations

from typing import Any

from parsers.common import (
    ensure_iso_datetime,
    extract_list,
    first_value,
    parse_json_output,
    parse_key_value_lines,
    parse_text_tables,
    to_float,
    to_int,
    usd_cents_to_float,
    usdt_wei_to_float,
)
from parsers.marketplace_parser import _normalize_card


def _normalize_recent_opened(item: dict[str, Any]) -> dict[str, Any]:
    token_id = first_value(item, ["collectibleTokenId", "collectible_token_id", "tokenId", "token_id"])
    fmv = usd_cents_to_float(first_value(item, ["fmv", "fmvPriceInUSD", "fmv_price_in_usd"]))
    return {
        "token_id": str(token_id) if token_id is not None else "",
        "name": f"Collectible #{token_id}" if token_id is not None else "Collectible",
        "current_price": fmv,
        "fmv_price": fmv,
        "rarity": first_value(item, ["tier", "rarity"]),
        "tier": first_value(item, ["tier"]),
        "is_listed": None,
        "pulled_at": ensure_iso_datetime(first_value(item, ["pulledAtTimestamp", "pulled_at_timestamp", "timestamp"])),
        "raw_data": item,
    }


def _normalize_pack(item: dict[str, Any]) -> dict[str, Any]:
    cards = extract_list(item, ["cards", "items", "collectibles", "results"])
    recent_opened = extract_list(item, ["recentOpenedPacks", "recent_opened_packs"])
    history = extract_list(item, ["price_history", "history", "sales"])

    official_price = usdt_wei_to_float(first_value(item, ["priceInUsdt", "price_in_usdt"]))
    expected_value = usd_cents_to_float(first_value(item, ["expectedValueInUsd", "expected_value_in_usd"]))
    featured_fmv = usd_cents_to_float(first_value(item, ["featuredCardFmvInUsd", "featured_card_fmv_in_usd"]))

    normalized_cards = [_normalize_card(card) for card in cards if isinstance(card, dict)]
    if not normalized_cards and recent_opened:
        normalized_cards = [_normalize_recent_opened(card) for card in recent_opened if isinstance(card, dict)]

    card_count = to_int(first_value(item, ["card_count", "cards_count", "count", "total_cards"]))
    if card_count is None and recent_opened:
        card_count = len(recent_opened)

    return {
        "slug": str(first_value(item, ["slug", "pack_slug", "id"], "")),
        "name": first_value(item, ["name", "pack_name", "title"]),
        "pack_type": first_value(item, ["packType", "pack_type", "type"]),
        "stage": first_value(item, ["stage", "status"]),
        "author": first_value(item, ["author", "creator"]),
        "description": first_value(item, ["description"]),
        "card_count": card_count,
        "pack_price": official_price,
        "expected_value": expected_value,
        "featured_card_fmv": featured_fmv,
        # Backward-compatible fields used by the current UI.
        "floor_price": official_price if official_price is not None else to_float(first_value(item, ["floor_price", "min_price", "lowest_price"])),
        "average_price": expected_value if expected_value is not None else to_float(first_value(item, ["average_price", "avg_price", "mean_price"])),
        "market_cap": to_float(first_value(item, ["market_cap", "total_value", "total_market_value"])),
        "cards": normalized_cards,
        "recent_opened_packs": [row for row in recent_opened if isinstance(row, dict)],
        "price_history": [row for row in history if isinstance(row, dict)],
        "raw_data": item,
    }


def parse_pack_list_output(raw: str) -> list[dict[str, Any]]:
    if not (raw or "").strip():
        return []
    payload = parse_json_output(raw)
    if payload is not None:
        items = extract_list(payload, ["cardPacks", "card_packs", "packs", "items", "results", "collections", "data"])
        return [_normalize_pack(item) for item in items if isinstance(item, dict)]

    packs: list[dict[str, Any]] = []
    for table in parse_text_tables(raw):
        keys = set(table[0]) if table else set()
        if "slug" in keys or "pack_slug" in keys:
            packs.extend(_normalize_pack(row) for row in table)
    return packs


def parse_pack_output(raw: str) -> dict[str, Any]:
    if not (raw or "").strip():
        return {"slug": "", "cards": [], "price_history": [], "raw_data": raw, "parse_mode": "empty", "parse_errors": ["CLI returned empty output"]}

    payload = parse_json_output(raw)
    if payload is not None:
        item: Any = payload
        if isinstance(payload, dict):
            for key in ("cardPack", "card_pack", "pack", "collection", "data", "result"):
                candidate = first_value(payload, [key])
                if isinstance(candidate, dict):
                    item = candidate
                    break
        if isinstance(item, dict):
            result = _normalize_pack(item)
            result.update({"raw_data": payload, "parse_mode": "json", "parse_errors": [] if result["slug"] else ["JSON parsed, but pack slug was not recognized"]})
            return result

    kv = parse_key_value_lines(raw)
    result = _normalize_pack(kv)
    cards: list[dict[str, Any]] = []
    for table in parse_text_tables(raw):
        keys = set(table[0]) if table else set()
        if {"token_id", "token", "id"} & keys and {"price", "current_price"} & keys:
            cards.extend(_normalize_card(row) for row in table)
    result["cards"] = cards
    result["raw_data"] = raw
    result["parse_mode"] = "text"
    result["parse_errors"] = [] if result["slug"] or cards else ["Text output format was not recognized"]
    return result
