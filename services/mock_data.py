from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import BASE_DIR


class MockDataProvider:
    """Deterministic offline data used when the CLI is unavailable."""

    PACKS = [
        ("genesis", "Genesis Legends"),
        ("cyber-myth", "Cyber Myth"),
        ("stellar-guardians", "Stellar Guardians"),
        ("neon-beasts", "Neon Beasts"),
        ("arcane-relics", "Arcane Relics"),
    ]
    RARITIES = ["Common", "Rare", "Epic", "Legendary"]
    NAMES = [
        "Aether Dragon", "Neon Ronin", "Solar Oracle", "Void Panther", "Crystal Sage",
        "Ember Titan", "Lunar Fox", "Quantum Knight", "Storm Herald", "Golden Chimera",
        "Celestial Archer", "Obsidian Warden", "Prism Witch", "Nova Serpent", "Iron Phoenix",
        "Echo Ranger", "Rune Mechanist", "Astral Monk", "Frost Valkyrie", "Shadow Alchemist",
        "Radiant Golem", "Pulse Samurai", "Dream Weaver", "Meteor Druid", "Chrome Kraken",
        "Aurora Sentinel", "Grim Harpy", "Flux Paladin", "Cosmic Djinn", "Signal Minotaur",
    ]

    def __init__(self, seed: int = 20260711) -> None:
        self.seed = seed
        self.generated_at = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        self.cards = self._build_cards()

    def _build_cards(self) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for index, name in enumerate(self.NAMES, start=1):
            rng = random.Random(self.seed + index)
            pack_slug, _ = self.PACKS[(index - 1) % len(self.PACKS)]
            rarity = self.RARITIES[min(int(rng.random() * 4), 3)]
            rarity_multiplier = {"Common": 1.0, "Rare": 1.8, "Epic": 3.4, "Legendary": 6.5}[rarity]
            base = round((9 + rng.random() * 55) * rarity_multiplier, 2)
            change = round(rng.uniform(-18, 24), 2)
            listed = rng.random() > 0.16
            current = round(base * (1 + change / 100), 2)
            token_id = str(1000 + index)
            cards.append(
                {
                    "token_id": token_id,
                    "name": name,
                    "current_price": current if listed else None,
                    "last_sale_price": round(base * rng.uniform(0.92, 1.08), 2),
                    "owner": f"0x{rng.getrandbits(80):020x}",
                    "pack_slug": pack_slug,
                    "rarity": rarity,
                    "image_url": str(BASE_DIR / "assets" / "cards" / f"card_{((index - 1) % 8) + 1}.svg"),
                    "is_listed": listed,
                    "change_24h": change,
                }
            )
        return cards

    def _history(self, card: dict[str, Any]) -> list[dict[str, Any]]:
        token_seed = int(card["token_id"])
        rng = random.Random(self.seed + token_seed * 11)
        last_sale = float(card.get("last_sale_price") or card.get("current_price") or 50)
        drift = (float(card.get("change_24h") or 0) / 100) / 30
        points: list[dict[str, Any]] = []
        price = max(1.0, last_sale * rng.uniform(0.72, 1.15))
        start = self.generated_at - timedelta(days=120)
        for day in range(121):
            timestamp = start + timedelta(days=day)
            cyclical = math.sin(day / 8) * 0.012
            shock = rng.gauss(drift + cyclical, 0.035)
            price = max(0.5, price * (1 + shock))
            points.append({"timestamp": timestamp.isoformat(), "price": round(price, 2), "type": "sale"})
        # Add denser intraday points so 24-hour and 7-day ranges are useful.
        for hours_ago in range(42, -1, -6):
            timestamp = self.generated_at - timedelta(hours=hours_ago)
            price = max(0.5, price * (1 + rng.gauss(drift, 0.018)))
            points.append({"timestamp": timestamp.isoformat(), "price": round(price, 2), "type": "sale"})
        target = card.get("current_price") or card.get("last_sale_price") or price
        points.append({"timestamp": self.generated_at.isoformat(), "price": round(float(target), 2), "type": "snapshot"})
        points.sort(key=lambda row: row["timestamp"])
        return points

    def _activities(self, card: dict[str, Any], history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rng = random.Random(self.seed + int(card["token_id"]) * 19)
        activities: list[dict[str, Any]] = []
        for index, point in enumerate(history[-22:]):
            if index % 3 != 0 and index < len(history[-22:]) - 5:
                continue
            tx_hash = f"0x{rng.getrandbits(128):032x}"
            activities.append(
                {
                    "activity_id": tx_hash,
                    "type": "sale",
                    "timestamp": point["timestamp"],
                    "price": point["price"],
                    "from_owner": f"0x{rng.getrandbits(64):016x}",
                    "to_owner": f"0x{rng.getrandbits(64):016x}",
                    "tx_hash": tx_hash,
                }
            )
        activities.append(
            {
                "activity_id": f"list-{card['token_id']}-{int(self.generated_at.timestamp())}",
                "type": "listing" if card.get("is_listed") else "unlisting",
                "timestamp": self.generated_at.isoformat(),
                "price": card.get("current_price"),
                "from_owner": card.get("owner"),
                "to_owner": None,
            }
        )
        return sorted(activities, key=lambda row: row["timestamp"], reverse=True)

    def get_marketplace(self, **filters: Any) -> dict[str, Any]:
        cards = [dict(card) for card in self.cards]
        if filters.get("pack_slug"):
            cards = [card for card in cards if card["pack_slug"] == filters["pack_slug"]]
        if filters.get("name"):
            query = str(filters["name"]).lower()
            cards = [card for card in cards if query in str(card["name"]).lower()]
        if filters.get("rarity"):
            cards = [card for card in cards if card["rarity"] == filters["rarity"]]
        if filters.get("min_price") is not None:
            cards = [card for card in cards if card.get("current_price") is not None and card["current_price"] >= float(filters["min_price"])]
        if filters.get("max_price") is not None:
            cards = [card for card in cards if card.get("current_price") is not None and card["current_price"] <= float(filters["max_price"])]
        if filters.get("listed") is not None:
            cards = [card for card in cards if bool(card.get("is_listed")) is bool(filters["listed"])]

        recent_sales: list[dict[str, Any]] = []
        for card in self.cards[:15]:
            history = self._history(card)
            point = history[-2]
            recent_sales.append(
                {
                    "activity_id": f"market-{card['token_id']}-{point['timestamp']}",
                    "token_id": card["token_id"],
                    "name": card["name"],
                    "price": point["price"],
                    "timestamp": point["timestamp"],
                    "buyer": f"0x{int(card['token_id']) * 23:016x}",
                    "seller": f"0x{int(card['token_id']) * 17:016x}",
                    "type": "sale",
                }
            )
        listed_prices = [float(card["current_price"]) for card in cards if card.get("current_price") is not None]
        return {
            "cards": cards,
            "recent_sales": sorted(recent_sales, key=lambda row: row["timestamp"], reverse=True),
            "summary": {
                "total_cards": len(cards),
                "listed_cards": sum(bool(card.get("is_listed")) for card in cards),
                "sales_24h": len(recent_sales),
                "volume_24h": round(sum(float(sale["price"]) for sale in recent_sales), 2),
                "min_price": min(listed_prices) if listed_prices else None,
            },
            "raw_data": {"mode": "mock", "generated_at": self.generated_at.isoformat()},
            "parse_mode": "mock",
            "parse_errors": [],
        }

    def get_card(self, token_id: str) -> dict[str, Any]:
        card = next((dict(item) for item in self.cards if item["token_id"] == str(token_id)), None)
        if card is None:
            raise ValueError("模拟数据中不存在该 Token ID。可使用 1001–1030。")
        history = self._history(card)
        activities = self._activities(card, history)
        sales = [row for row in history if row["type"] == "sale"]
        card.update(
            {
                "last_sale_price": sales[-1]["price"] if sales else card.get("last_sale_price"),
                "activities": activities,
                "price_history": history,
                "raw_data": {"mode": "mock", "token_id": token_id},
                "parse_mode": "mock",
                "parse_errors": [],
            }
        )
        return card

    def get_pack_list(self) -> list[dict[str, Any]]:
        return [self.get_pack(slug) | {"cards": [], "price_history": []} for slug, _ in self.PACKS]

    def get_pack(self, slug: str) -> dict[str, Any]:
        pack_meta = next(((pack_slug, name) for pack_slug, name in self.PACKS if pack_slug == slug), None)
        if pack_meta is None:
            raise ValueError("模拟数据中不存在该卡包 Slug。")
        cards = [dict(card) for card in self.cards if card["pack_slug"] == slug]
        prices = [float(card["current_price"]) for card in cards if card.get("current_price") is not None]
        history: list[dict[str, Any]] = []
        for days_ago in range(90, -1, -3):
            values = []
            for card in cards:
                card_history = self._history(card)
                target = self.generated_at - timedelta(days=days_ago)
                nearest = min(card_history, key=lambda row: abs(datetime.fromisoformat(row["timestamp"]) - target))
                values.append(float(nearest["price"]))
            history.append(
                {
                    "timestamp": (self.generated_at - timedelta(days=days_ago)).isoformat(),
                    "price": round(sum(values) / len(values), 2) if values else None,
                }
            )
        return {
            "slug": slug,
            "name": pack_meta[1],
            "card_count": len(cards),
            "floor_price": round(min(prices), 2) if prices else None,
            "average_price": round(sum(prices) / len(prices), 2) if prices else None,
            "market_cap": round(sum(prices), 2) if prices else None,
            "cards": cards,
            "price_history": history,
            "raw_data": {"mode": "mock", "slug": slug},
            "parse_mode": "mock",
            "parse_errors": [],
        }
