from __future__ import annotations

import logging
from typing import Any

from database.repository import RenaissRepository
from services.mock_data import MockDataProvider
from services.renaiss_cli import RenaissCLIClient, RenaissCLIError

LOGGER = logging.getLogger(__name__)


class CardService:
    def __init__(self, client: RenaissCLIClient, repository: RenaissRepository, mock: MockDataProvider) -> None:
        self.client = client
        self.repository = repository
        self.mock = mock

    def fetch(self, token_id: str, *, mock_mode: bool = False, allow_fallback: bool = True) -> dict[str, Any]:
        source = "mock" if mock_mode else "cli"
        fallback_reason: str | None = None
        try:
            data = self.mock.get_card(token_id) if mock_mode else self.client.get_card(token_id)
            if (
                not mock_mode
                and allow_fallback
                and data.get("parse_errors")
                and not any(data.get(key) is not None for key in ("name", "current_price", "last_sale_price", "owner"))
            ):
                cli_raw = data.get("raw_data")
                data = self.mock.get_card(token_id)
                data["unparsed_cli_raw"] = cli_raw
                source = "mock-fallback"
                fallback_reason = "真实 CLI 输出格式暂未被解析器识别。"
        except RenaissCLIError as exc:
            if not allow_fallback or mock_mode:
                raise
            LOGGER.warning("Card CLI failed; using mock data: %s", exc)
            data = self.mock.get_card(token_id)
            source = "mock-fallback"
            fallback_reason = str(exc)
        data["data_source"] = source
        if fallback_reason:
            data["fallback_reason"] = fallback_reason
        self.repository.save_card(data)
        return data

    def history(self, token_id: str):
        return self.repository.get_card_price_history(token_id)

    def activities(self, token_id: str):
        return self.repository.get_card_activities(token_id)
