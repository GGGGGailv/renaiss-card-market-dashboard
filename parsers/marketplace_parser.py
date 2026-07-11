from __future__ import annotations

from typing import Any

from parsers.common import (
    display_owner,
    extract_list,
    first_value,
    money_amount_to_float,
    nested_value,
    parse_json_output,
    parse_key_value_lines,
    parse_text_tables,
    to_bool,
    to_float,
    usd_cents_to_float,
    usdt_wei_to_float,
)


def _is_renaiss_listed(item: dict[str, Any]) -> bool | None:
    ask = first_value(item, ["askPriceInUSDT", "ask_price_in_usdt"])
    if ask is not None:
        text = str(ask).strip().upper()
        return bool(text) and not text.startswith("NO-")
    return None


def _normalize_card(item: dict[str, Any]) -> dict[str, Any]:
    listing = nested_value(item, ["listing", "market_listing"], {})
    if not isinstance(listing, dict):
        listing = {}

    token_id = first_value(item, ["token_id", "tokenId", "token", "id", "collectible_id"])

    # Official Renaiss CLI v0.0.2 fields:
    # - askPriceInUSDT: 18-decimal wei
    # - fmvPriceInUSD: integer cents
    ask_raw = first_value(item, ["askPriceInUSDT", "ask_price_in_usdt"])
    fmv_raw = first_value(item, ["fmvPriceInUSD", "fmv_price_in_usd"])
    ask_price = usdt_wei_to_float(ask_raw)
    fmv_price = usd_cents_to_float(fmv_raw)

    price = first_value(item, ["current_price", "price", "listing_price", "ask_price", "floor_price"])
    if price is None:
        price = first_value(listing, ["price", "amount", "value"])
    generic_price = money_amount_to_float(price)
    current_price = ask_price if ask_price is not None else (generic_price if generic_price is not None else fmv_price)

    listed = first_value(item, ["is_listed", "listed", "for_sale", "on_sale", "status"])
    if listed is None:
        listed = first_value(listing, ["active", "is_active", "listed"])
    listed_value = to_bool(listed)
    if listed_value is None:
        listed_value = _is_renaiss_listed(item)

    owner = display_owner(
        first_value(item, ["owner", "holder", "current_owner", "seller"]),
        first_value(item, ["ownerAddress", "owner_address"]),
    )

    set_name = first_value(item, ["setName", "set_name"])
    grading = first_value(item, ["gradingCompany", "grading_company"])
    grade = first_value(item, ["grade"])
    tier = first_value(item, ["tier", "rarity"])

    return {
        "token_id": str(token_id) if token_id is not None else "",
        "name": first_value(item, ["name", "card_name", "title"]),
        "current_price": current_price,
        "ask_price": ask_price,
        "fmv_price": fmv_price,
        "last_sale_price": to_float(first_value(item, ["last_sale_price", "last_price", "sale_price"])),
        "owner": owner,
        "pack_slug": first_value(item, ["pack_slug", "pack", "collection_slug", "collection"]) or set_name,
        "set_name": set_name,
        "rarity": tier or grade,
        "tier": tier,
        "grade": grade,
        "grading_company": grading,
        "year": first_value(item, ["year"]),
        "card_number": first_value(item, ["cardNumber", "card_number"]),
        "character": first_value(item, ["pokemonName", "pokemon_name", "character"]),
        "image_url": first_value(item, ["image_url", "imageUrl", "frontImageUrl", "front_image_url", "image", "thumbnail", "media_url"]),
        "is_listed": listed_value,
        "change_24h": to_float(first_value(item, ["change_24h", "price_change_24h", "24h_change", "change"])),
        "raw_data": item,
    }


def _normalize_sale(item: dict[str, Any]) -> dict[str, Any]:
    price_value = first_value(item, ["price", "sale_price", "amount", "value"])
    return {
        "activity_id": first_value(item, ["activity_id", "event_id", "id", "transaction_hash", "tx_hash"]),
        "token_id": str(first_value(item, ["token_id", "tokenId", "token", "id"], "")),
        "name": first_value(item, ["name", "card_name", "title"]),
        "price": money_amount_to_float(price_value),
        "timestamp": first_value(item, ["timestamp", "time", "date", "created_at", "occurred_at"]),
        "buyer": first_value(item, ["buyer", "to", "to_owner", "bidder"]),
        "seller": first_value(item, ["seller", "from", "from_owner", "asker"]),
        "type": first_value(item, ["type", "event", "activity_type"], "sale"),
        "raw_data": item,
    }


def parse_marketplace_output(raw: str) -> dict[str, Any]:
    if not (raw or "").strip():
        return {"cards": [], "recent_sales": [], "raw_data": raw, "parse_mode": "empty", "parse_errors": ["CLI returned empty output"]}

    payload = parse_json_output(raw)
    if payload is not None:
        # The official CLI returns {"collection": [...], "pagination": {...}}.
        card_items = extract_list(
            payload,
            ["collection", "cards", "items", "listings", "collectibles", "results", "marketplace"],
        )
        sales_items = extract_list(payload, ["recent_sales", "sales", "transactions", "activities", "events"])
        cards = [_normalize_card(item) for item in card_items if isinstance(item, dict)]
        sales = [_normalize_sale(item) for item in sales_items if isinstance(item, dict)]
        summary_source = payload if isinstance(payload, dict) else {}
        pagination = first_value(summary_source, ["pagination"], {}) if isinstance(summary_source, dict) else {}
        if not isinstance(pagination, dict):
            pagination = {}
        return {
            "cards": cards,
            "recent_sales": sales,
            "summary": {
                "total_cards": to_float(first_value(pagination, ["total"])) or to_float(first_value(summary_source, ["total_cards", "total", "count"])),
                "listed_cards": to_float(first_value(summary_source, ["listed_cards", "listed_count", "active_listings"])),
                "sales_24h": to_float(first_value(summary_source, ["sales_24h", "transactions_24h", "volume_count_24h"])),
                "volume_24h": to_float(first_value(summary_source, ["volume_24h", "sales_volume_24h", "turnover_24h"])),
                "limit": to_float(first_value(pagination, ["limit"])),
                "offset": to_float(first_value(pagination, ["offset"])),
                "has_more": first_value(pagination, ["hasMore", "has_more"]),
            },
            "raw_data": payload,
            "parse_mode": "json",
            "parse_errors": [] if cards or sales else ["JSON parsed, but no recognized card or sale list was found"],
        }

    kv = parse_key_value_lines(raw)
    tables = parse_text_tables(raw)
    cards: list[dict[str, Any]] = []
    sales: list[dict[str, Any]] = []
    for table in tables:
        keys = set(table[0]) if table else set()
        if {"token_id", "token", "id"} & keys and {"price", "current_price", "listing_price"} & keys:
            cards.extend(_normalize_card(row) for row in table)
        elif {"price", "sale_price", "amount"} & keys and {"time", "timestamp", "date"} & keys:
            sales.extend(_normalize_sale(row) for row in table)

    summary = {
        "total_cards": to_float(first_value(kv, ["total_cards", "total", "cards"])),
        "listed_cards": to_float(first_value(kv, ["listed_cards", "listed", "active_listings"])),
        "sales_24h": to_float(first_value(kv, ["sales_24h", "24h_sales", "transactions_24h"])),
        "volume_24h": to_float(first_value(kv, ["volume_24h", "24h_volume", "turnover_24h"])),
    }
    errors = [] if cards or sales or any(v is not None for v in summary.values()) else ["Text output format was not recognized"]
    return {
        "cards": cards,
        "recent_sales": sales,
        "summary": summary,
        "raw_data": raw,
        "parse_mode": "text",
        "parse_errors": errors,
    }
