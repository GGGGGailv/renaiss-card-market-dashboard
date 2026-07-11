from __future__ import annotations

from typing import Any

from parsers.common import (
    display_owner,
    ensure_iso_datetime,
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


def _normalize_activity(item: dict[str, Any]) -> dict[str, Any]:
    activity_type = str(first_value(item, ["type", "event", "activity_type", "action"], "unknown"))
    amount = first_value(item, ["price", "sale_price", "amount", "value"])
    if activity_type.lower() in {"sell", "sale", "sold", "purchase", "trade"} and not isinstance(amount, dict):
        # Official CLI sell activities expose raw USDT wei in `amount`.
        price = usdt_wei_to_float(amount)
        if price is None:
            price = to_float(amount)
    else:
        price = money_amount_to_float(amount)
    return {
        "activity_id": first_value(item, ["activity_id", "event_id", "id", "tx_hash", "txHash", "transaction_hash"]),
        "type": activity_type,
        "timestamp": ensure_iso_datetime(first_value(item, ["timestamp", "time", "date", "created_at", "occurred_at"])),
        "price": price,
        "from_owner": first_value(item, ["from_owner", "from", "seller", "asker", "user"]),
        "to_owner": first_value(item, ["to_owner", "to", "buyer", "bidder"]),
        "tx_hash": first_value(item, ["tx_hash", "txHash", "transaction_hash", "hash"]),
        "raw_data": item,
    }


def _normalize_history(item: dict[str, Any]) -> dict[str, Any]:
    amount = first_value(item, ["amount"])
    price = money_amount_to_float(amount) if isinstance(amount, dict) else to_float(
        first_value(item, ["price", "sale_price", "value", "amount"])
    )
    return {
        "timestamp": ensure_iso_datetime(first_value(item, ["timestamp", "time", "date", "created_at", "occurred_at"])),
        "price": price,
        "type": first_value(item, ["type", "event", "activity_type"], "sale"),
        "raw_data": item,
    }


def _normalize_official_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    collectible = first_value(payload, ["collectible"])
    if not isinstance(collectible, dict):
        return None

    pricing = first_value(payload, ["pricing"], {})
    if not isinstance(pricing, dict):
        pricing = {}
    activities_container = first_value(payload, ["activities"], {})
    if not isinstance(activities_container, dict):
        activities_container = {}

    ask_raw = first_value(collectible, ["askPriceInUSDT", "ask_price_in_usdt"])
    fmv_raw = first_value(collectible, ["fmvPriceInUSD", "fmv_price_in_usd"])
    ask_price = usdt_wei_to_float(ask_raw)
    fmv_price = usd_cents_to_float(fmv_raw)

    price_object = first_value(pricing, ["price"])
    top_offer_object = first_value(pricing, ["top_offer", "topOffer"])
    last_sale_object = first_value(pricing, ["last_sale", "lastSale"])
    current_price = money_amount_to_float(price_object)
    if current_price is None:
        current_price = ask_price if ask_price is not None else fmv_price

    history_items = extract_list(pricing, ["price_history", "priceHistory", "history"])
    normalized_history = [_normalize_history(item) for item in history_items if isinstance(item, dict)]

    activity_items = extract_list(activities_container, ["activities", "events", "transactions"])
    normalized_activities = [_normalize_activity(item) for item in activity_items if isinstance(item, dict)]
    for activity in normalized_activities:
        if activity.get("price") is not None and str(activity.get("type", "")).lower() in {"sell", "sale", "sold", "purchase", "trade"}:
            normalized_history.append(
                {
                    "timestamp": activity.get("timestamp"),
                    "price": activity.get("price"),
                    "type": activity.get("type"),
                    "raw_data": activity.get("raw_data"),
                }
            )

    owner = display_owner(
        first_value(collectible, ["owner"]),
        first_value(collectible, ["ownerAddress", "owner_address"]),
    )
    listed = bool(str(ask_raw or "").strip()) and not str(ask_raw).upper().startswith("NO-")

    return {
        "token_id": str(first_value(collectible, ["tokenId", "token_id"], "")),
        "name": first_value(collectible, ["name"]),
        "current_price": current_price,
        "ask_price": ask_price,
        "fmv_price": fmv_price,
        "top_offer": money_amount_to_float(top_offer_object),
        "last_sale_price": money_amount_to_float(last_sale_object),
        "owner": owner,
        "pack_slug": first_value(collectible, ["setName", "set_name"]),
        "set_name": first_value(collectible, ["setName", "set_name"]),
        "rarity": first_value(collectible, ["tier", "grade"]),
        "tier": first_value(collectible, ["tier"]),
        "grade": first_value(collectible, ["grade"]),
        "grading_company": first_value(collectible, ["gradingCompany", "grading_company"]),
        "year": first_value(collectible, ["year"]),
        "card_number": first_value(collectible, ["cardNumber", "card_number"]),
        "character": first_value(collectible, ["pokemonName", "pokemon_name"]),
        "image_url": first_value(collectible, ["image_url", "imageUrl", "frontImageUrl", "front_image_url", "image", "thumbnail", "media_url"]),
        "is_listed": listed,
        "activities": normalized_activities,
        "price_history": normalized_history,
        "raw_data": payload,
    }


def _from_mapping(item: dict[str, Any], raw_data: Any) -> dict[str, Any]:
    listing = nested_value(item, ["listing", "market_listing"], {})
    metadata = nested_value(item, ["metadata", "attributes"], {})
    if not isinstance(listing, dict):
        listing = {}
    if not isinstance(metadata, dict):
        metadata = {}

    activities = extract_list(item, ["activities", "activity_history", "events", "transactions"])
    sales = extract_list(item, ["sales", "sale_history", "price_history", "priceHistory", "history"])
    normalized_activities = [_normalize_activity(x) for x in activities if isinstance(x, dict)]
    normalized_history = [_normalize_history(x) for x in sales if isinstance(x, dict)]
    for activity in normalized_activities:
        if activity.get("price") is not None and str(activity.get("type", "")).lower() in {"sale", "sell", "sold", "purchase", "trade"}:
            normalized_history.append({
                "timestamp": activity.get("timestamp"),
                "price": activity.get("price"),
                "type": activity.get("type"),
                "raw_data": activity.get("raw_data"),
            })

    price = first_value(item, ["current_price", "currentPrice", "price", "listing_price", "ask_price"])
    if price is None:
        price = first_value(listing, ["price", "amount", "value"])
    listed = first_value(item, ["is_listed", "isListed", "listed", "for_sale", "status"])
    if listed is None:
        listed = first_value(listing, ["active", "is_active", "listed"])

    token_id = first_value(item, ["token_id", "tokenId", "token", "id", "collectible_id"])
    return {
        "token_id": str(token_id) if token_id is not None else "",
        "name": first_value(item, ["name", "card_name", "title"]),
        "current_price": money_amount_to_float(price),
        "last_sale_price": money_amount_to_float(first_value(item, ["last_sale_price", "lastSalePrice", "last_price", "sale_price"])),
        "owner": display_owner(first_value(item, ["owner", "holder", "current_owner"])),
        "pack_slug": first_value(item, ["pack_slug", "packSlug", "pack", "collection_slug", "collection"]),
        "rarity": first_value(item, ["rarity", "tier", "grade"]) or first_value(metadata, ["rarity", "tier"]),
        "image_url": first_value(item, ["image_url", "imageUrl", "image", "thumbnail", "media_url"]),
        "is_listed": to_bool(listed),
        "activities": normalized_activities,
        "price_history": normalized_history,
        "raw_data": raw_data,
    }


def parse_card_output(raw: str) -> dict[str, Any]:
    if not (raw or "").strip():
        return {
            "token_id": "", "activities": [], "price_history": [], "raw_data": raw,
            "parse_mode": "empty", "parse_errors": ["CLI returned empty output"],
        }

    payload = parse_json_output(raw)
    if payload is not None:
        if isinstance(payload, dict):
            official = _normalize_official_payload(payload)
            if official is not None:
                official.update({
                    "parse_mode": "json",
                    "parse_errors": [] if official["token_id"] else ["JSON parsed, but token ID was not recognized"],
                })
                return official

        item: Any = payload
        if isinstance(payload, dict):
            for key in ("card", "collectible", "item", "data", "result"):
                candidate = first_value(payload, [key])
                if isinstance(candidate, dict):
                    item = candidate
                    break
        if isinstance(item, dict):
            result = _from_mapping(item, payload)
            result.update({"parse_mode": "json", "parse_errors": [] if result["token_id"] else ["JSON parsed, but token ID was not recognized"]})
            return result
        return {"token_id": "", "activities": [], "price_history": [], "raw_data": payload, "parse_mode": "json", "parse_errors": ["JSON output is not an object"]}

    kv = parse_key_value_lines(raw)
    result = _from_mapping(kv, raw)
    activities: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    for table in parse_text_tables(raw):
        keys = set(table[0]) if table else set()
        if {"time", "timestamp", "date"} & keys and {"type", "event", "activity"} & keys:
            activities.extend(_normalize_activity(row) for row in table)
        if {"time", "timestamp", "date"} & keys and {"price", "sale_price", "amount"} & keys:
            history.extend(_normalize_history(row) for row in table)
    result["activities"] = activities
    result["price_history"] = history
    result["parse_mode"] = "text"
    result["parse_errors"] = [] if result.get("token_id") else ["Text output format was not recognized"]
    return result
