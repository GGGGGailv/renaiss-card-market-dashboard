from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import CONFIG
from parsers.card_parser import parse_card_output
from parsers.marketplace_parser import parse_marketplace_output
from parsers.pack_parser import parse_pack_list_output, parse_pack_output

LOGGER = logging.getLogger(__name__)


class RenaissCLIError(RuntimeError):
    """Base exception for user-facing CLI failures."""


class RenaissCLINotFoundError(RenaissCLIError):
    pass


class RenaissCLITimeoutError(RenaissCLIError):
    pass


class RenaissCLICommandError(RenaissCLIError):
    def __init__(self, message: str, returncode: int | None = None, stderr: str = "") -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


@dataclass(frozen=True)
class CLIExecution:
    args: tuple[str, ...]
    stdout: str
    stderr: str
    returncode: int
    duration_seconds: float


class RenaissCLIClient:
    """Safe wrapper around the local Renaiss CLI.

    The client never uses ``shell=True`` and never accepts raw arbitrary argument
    strings from UI input. Optional flags are only emitted when they are present
    in the corresponding command help output.
    """

    ALLOWED_HELP_COMMANDS = {"marketplace", "card", "packs"}
    TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,127}$")
    SLUG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

    # These are logical filters used by the app. A flag is only used when the
    # exact spelling appears in the installed CLI help.
    FILTER_FLAG_CANDIDATES: dict[str, tuple[str, ...]] = {
        "pack_slug": ("--pack", "--pack-slug", "--collection", "--collection-slug"),
        "name": ("--name", "--search", "--query"),
        "rarity": ("--rarity", "--tier"),
        "min_price": ("--min-price", "--price-min"),
        "max_price": ("--max-price", "--price-max"),
        "listed": ("--listed", "--status", "--on-sale"),
        "sort": ("--sort", "--order-by"),
        "limit": ("--limit", "--count", "-n"),
    }

    def __init__(
        self,
        binary: str = CONFIG.cli_binary,
        timeout_seconds: int = CONFIG.cli_timeout_seconds,
    ) -> None:
        self.binary = binary
        self.timeout_seconds = timeout_seconds
        self._help_cache: dict[str, str] = {}
        self.last_execution: CLIExecution | None = None

    def resolve_binary(self) -> str | None:
        """Return the concrete executable/shim path visible to this Python process."""
        return shutil.which(self.binary)

    def check_installation(self) -> bool:
        return self.resolve_binary() is not None

    @staticmethod
    def _build_process_args(resolved_binary: str, args: list[str]) -> list[str]:
        """Use the fully resolved executable/shim path for reliable launching.

        On Windows, ``shutil.which`` may resolve an extensionless command such
        as ``renaiss`` to a concrete ``renaiss.cmd`` path. Passing that resolved
        path avoids a second, platform-dependent executable lookup.
        """
        return [resolved_binary, *args]

    def _run(self, args: list[str], timeout: int | None = None) -> CLIExecution:
        resolved_binary = self.resolve_binary()
        if not resolved_binary:
            raise RenaissCLINotFoundError(
                f"未在系统 PATH 中找到 {self.binary!r}。请安装 Renaiss CLI，或使用模拟数据模式。"
            )

        safe_args = self._build_process_args(resolved_binary, args)
        started = time.monotonic()
        LOGGER.info("Calling Renaiss CLI command=%s", args[0] if args else "version")
        try:
            completed = subprocess.run(
                safe_args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout or self.timeout_seconds,
                check=False,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise RenaissCLINotFoundError(
                f"已在 PATH 中发现 Renaiss CLI（{resolved_binary}），但启动失败。"
                "请重新打开终端/Streamlit，或在命令行执行 where renaiss 与 renaiss --version 检查安装。"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            LOGGER.exception("Renaiss CLI timed out")
            raise RenaissCLITimeoutError(
                f"Renaiss CLI 调用超过 {timeout or self.timeout_seconds} 秒，已停止本次请求。"
            ) from exc
        except OSError as exc:
            LOGGER.exception("Unable to start Renaiss CLI")
            raise RenaissCLIError("无法启动 Renaiss CLI，请检查安装权限和系统环境。") from exc

        execution = CLIExecution(
            args=tuple(args),
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            returncode=completed.returncode,
            duration_seconds=time.monotonic() - started,
        )
        self.last_execution = execution

        if completed.returncode != 0:
            LOGGER.error(
                "Renaiss CLI failed command=%s code=%s stderr=%s",
                args[0] if args else "version",
                completed.returncode,
                (completed.stderr or "")[:1000],
            )
            friendly = self._friendly_error(args, execution)
            raise RenaissCLICommandError(friendly, completed.returncode, execution.stderr)
        return execution

    @staticmethod
    def _friendly_error(args: list[str], execution: CLIExecution) -> str:
        stderr = execution.stderr.strip()
        lower = stderr.lower()
        if "not found" in lower or "does not exist" in lower:
            if args and args[0] == "card":
                return "没有找到该 Token ID 对应的卡牌。"
            if args and args[0] == "packs":
                return "没有找到该卡包 Slug。"
        if "network" in lower or "timeout" in lower or "rpc" in lower:
            return "Renaiss 数据源暂时不可用，请稍后重试。"
        if stderr:
            return f"Renaiss CLI 返回错误：{stderr[:240]}"
        return "Renaiss CLI 执行失败，请查看日志了解详细信息。"

    def get_version(self) -> str:
        execution = self._run(["--version"], timeout=10)
        return execution.stdout.strip() or execution.stderr.strip() or "unknown"

    def get_help(self, command: str) -> str:
        if command not in self.ALLOWED_HELP_COMMANDS:
            raise ValueError(f"Unsupported help command: {command}")
        if command not in self._help_cache:
            execution = self._run([command, "--help"], timeout=10)
            self._help_cache[command] = execution.stdout or execution.stderr
        return self._help_cache[command]

    def discover_help(self) -> dict[str, str]:
        return {command: self.get_help(command) for command in sorted(self.ALLOWED_HELP_COMMANDS)}

    @staticmethod
    def _extract_options(help_text: str) -> set[str]:
        return set(re.findall(r"(?<!\w)(--[a-zA-Z0-9][a-zA-Z0-9-]*|-[a-zA-Z])(?=[\s,=\[<]|$)", help_text or ""))

    def _json_output_args(self, command: str) -> list[str]:
        options = self._extract_options(self.get_help(command))
        if "--json" in options:
            return ["--json"]
        # Only use output-format flags when JSON is explicitly documented.
        help_text = self.get_help(command)
        if "--output" in options and re.search(r"\bjson\b", help_text, flags=re.IGNORECASE):
            return ["--output", "json"]
        if "--format" in options and re.search(r"\bjson\b", help_text, flags=re.IGNORECASE):
            return ["--format", "json"]
        return []

    def _validated_filter_args(self, command: str, filters: dict[str, Any]) -> list[str]:
        options = self._extract_options(self.get_help(command))
        result: list[str] = []
        for logical_name, value in filters.items():
            if value is None or value == "":
                continue
            candidates = self.FILTER_FLAG_CANDIDATES.get(logical_name)
            if not candidates:
                continue
            flag = next((candidate for candidate in candidates if candidate in options), None)
            if flag is None:
                continue
            if logical_name in {"min_price", "max_price"}:
                try:
                    value = float(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{logical_name} must be numeric") from exc
                if value < 0:
                    raise ValueError(f"{logical_name} cannot be negative")
            elif logical_name == "limit":
                value = int(value)
                if not 1 <= value <= 1000:
                    raise ValueError("limit must be between 1 and 1000")
            elif logical_name == "listed":
                if isinstance(value, bool):
                    # Boolean flags commonly take no value. If help shows a value
                    # placeholder, use a literal boolean instead.
                    option_line = next((line for line in self.get_help(command).splitlines() if flag in line), "")
                    if value and not re.search(r"[<\[]|\bBOOLEAN\b|\bVALUE\b", option_line, re.IGNORECASE):
                        result.append(flag)
                        continue
                    value = str(value).lower()
            else:
                value = str(value)
                if len(value) > 128:
                    raise ValueError(f"{logical_name} is too long")
            result.extend([flag, str(value)])
        return result

    def get_marketplace(self, **filters: Any) -> dict[str, Any]:
        # The official CLI defaults to 10 rows. Request the largest documented
        # page so the dashboard has enough cards for filtering and comparison.
        filters = dict(filters)
        filters.setdefault("limit", 100)
        args = ["marketplace"]
        args.extend(self._json_output_args("marketplace"))
        args.extend(self._validated_filter_args("marketplace", filters))
        execution = self._run(args)
        result = parse_marketplace_output(execution.stdout)
        result["cli_stderr"] = execution.stderr
        result["cli_duration_seconds"] = execution.duration_seconds
        return result

    def get_card(self, token_id: str) -> dict[str, Any]:
        token_id = str(token_id).strip()
        if not self.TOKEN_PATTERN.fullmatch(token_id):
            raise ValueError("Token ID 只能包含字母、数字、冒号、下划线和连字符，长度不超过 128。")

        options = self._extract_options(self.get_help("card"))
        args = ["card"]
        args.extend(self._json_output_args("card"))
        # Ask for the full official payload when supported. Without these flags,
        # the CLI omits activity history and verbose price history.
        if "--price" in options:
            args.append("--price")
        if "--verbose" in options and "--price" in options:
            args.append("--verbose")
        if "--activities" in options:
            args.append("--activities")
        args.append(token_id)

        execution = self._run(args)
        result = parse_card_output(execution.stdout)
        if not result.get("token_id"):
            result["token_id"] = token_id
        result["cli_stderr"] = execution.stderr
        result["cli_duration_seconds"] = execution.duration_seconds
        return result

    def get_pack_list(self) -> list[dict[str, Any]]:
        args = ["packs"]
        args.extend(self._json_output_args("packs"))
        execution = self._run(args)
        return parse_pack_list_output(execution.stdout)

    def get_pack(self, slug: str) -> dict[str, Any]:
        slug = str(slug).strip()
        if not self.SLUG_PATTERN.fullmatch(slug):
            raise ValueError("卡包 Slug 只能包含字母、数字、点、下划线和连字符，长度不超过 128。")
        args = ["packs", *self._json_output_args("packs"), slug]
        execution = self._run(args)
        result = parse_pack_output(execution.stdout)
        if not result.get("slug"):
            result["slug"] = slug
        result["cli_stderr"] = execution.stderr
        result["cli_duration_seconds"] = execution.duration_seconds
        return result

    def diagnostics(self) -> dict[str, Any]:
        installed = self.check_installation()
        diagnostics: dict[str, Any] = {
            "installed": installed,
            "binary": self.binary,
            "resolved_binary": self.resolve_binary(),
        }
        if not installed:
            return diagnostics
        try:
            diagnostics["version"] = self.get_version()
            diagnostics["help"] = self.discover_help()
            diagnostics["available_options"] = {
                command: sorted(self._extract_options(text))
                for command, text in diagnostics["help"].items()
            }
        except RenaissCLIError as exc:
            diagnostics["error"] = str(exc)
        return diagnostics

    @staticmethod
    def raw_as_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
