from __future__ import annotations

import logging
from typing import Any

from database.repository import RenaissRepository
from services.mock_data import MockDataProvider
from services.renaiss_cli import RenaissCLIClient, RenaissCLIError

LOGGER = logging.getLogger(__name__)


class MarketplaceService:
    def __init__(self, client: RenaissCLIClient, repository: RenaissRepository, mock: MockDataProvider) -> None:
        self.client = client
        self.repository = repository
        self.mock = mock

    def fetch(
        self,
        filters: dict[str, Any] | None = None,
        *,
        mock_mode: bool = False,
        allow_fallback: bool = True,
    ) -> dict[str, Any]:
        filters = filters or {}
        source = "mock" if mock_mode else "cli"
        fallback_reason: str | None = None
        try:
            data = self.mock.get_marketplace(**filters) if mock_mode else self.client.get_marketplace(**filters)
            if (
                not mock_mode
                and allow_fallback
                and data.get("parse_errors")
                and not data.get("cards")
                and not data.get("recent_sales")
            ):
                cli_raw = data.get("raw_data")
                data = self.mock.get_marketplace(**filters)
                data["unparsed_cli_raw"] = cli_raw
                source = "mock-fallback"
                fallback_reason = "真实 CLI 输出格式暂未被解析器识别。"
        except (RenaissCLIError, ValueError) as exc:
            if not allow_fallback or mock_mode:
                raise
            LOGGER.warning("Marketplace CLI failed; using mock data: %s", exc)
            data = self.mock.get_marketplace(**filters)
            source = "mock-fallback"
            fallback_reason = str(exc)
        data["data_source"] = source
        if fallback_reason:
            data["fallback_reason"] = fallback_reason
        self.repository.save_marketplace(data)
        return data
