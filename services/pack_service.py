from __future__ import annotations

import logging
from typing import Any

from database.repository import RenaissRepository
from services.mock_data import MockDataProvider
from services.renaiss_cli import RenaissCLIClient, RenaissCLIError

LOGGER = logging.getLogger(__name__)


class PackService:
    def __init__(self, client: RenaissCLIClient, repository: RenaissRepository, mock: MockDataProvider) -> None:
        self.client = client
        self.repository = repository
        self.mock = mock

    def list(self, *, mock_mode: bool = False, allow_fallback: bool = True) -> list[dict[str, Any]]:
        try:
            data = self.mock.get_pack_list() if mock_mode else self.client.get_pack_list()
            if not mock_mode and allow_fallback and not data:
                data = self.mock.get_pack_list()
                for item in data:
                    item["fallback_reason"] = "真实 CLI 输出格式暂未被解析器识别。"
        except RenaissCLIError as exc:
            if not allow_fallback or mock_mode:
                raise
            LOGGER.warning("Pack list CLI failed; using mock data: %s", exc)
            data = self.mock.get_pack_list()
            for item in data:
                item["fallback_reason"] = str(exc)
        self.repository.upsert_packs(data)
        return data

    def get(self, slug: str, *, mock_mode: bool = False, allow_fallback: bool = True) -> dict[str, Any]:
        source = "mock" if mock_mode else "cli"
        fallback_reason: str | None = None
        try:
            data = self.mock.get_pack(slug) if mock_mode else self.client.get_pack(slug)
            if (
                not mock_mode
                and allow_fallback
                and data.get("parse_errors")
                and not data.get("cards")
                and not data.get("name")
            ):
                cli_raw = data.get("raw_data")
                data = self.mock.get_pack(slug)
                data["unparsed_cli_raw"] = cli_raw
                source = "mock-fallback"
                fallback_reason = "真实 CLI 输出格式暂未被解析器识别。"
        except RenaissCLIError as exc:
            if not allow_fallback or mock_mode:
                raise
            LOGGER.warning("Pack CLI failed; using mock data: %s", exc)
            data = self.mock.get_pack(slug)
            source = "mock-fallback"
            fallback_reason = str(exc)
        data["data_source"] = source
        if fallback_reason:
            data["fallback_reason"] = fallback_reason
        self.repository.upsert_packs([data])
        for card in data.get("cards") or []:
            self.repository.upsert_card(card)
        return data
