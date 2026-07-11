from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

NULL_VALUES = {"", "-", "--", "n/a", "na", "none", "null", "unknown"}
ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(value: str) -> str:
    return ANSI_ESCAPE_RE.sub("", value or "")


def parse_json_output(raw: str) -> Any | None:
    text = strip_ansi(raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Some CLIs print a status line before JSON. Try each JSON-looking suffix,
    # not only the first one, because banners/log lines may contain braces.
    starts = [index for index, char in enumerate(text) if char in "{["]
    for index in starts:
        try:
            return json.loads(text[index:])
        except json.JSONDecodeError:
            continue
    return None


def normalize_key(value: str) -> str:
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value.strip())
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    text = strip_ansi(str(value)).strip()
    if text.lower() in NULL_VALUES or text.upper().startswith("NO-"):
        return None
    text = re.sub(r"[$€£¥Ξ]", "", text)
    text = text.replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def _scaled_decimal(value: Any, divisor: str) -> float | None:
    if value is None:
        return None
    text = strip_ansi(str(value)).strip().replace(",", "")
    if not text or text.lower() in NULL_VALUES or text.upper().startswith("NO-"):
        return None
    try:
        return float(Decimal(text) / Decimal(divisor))
    except (InvalidOperation, ValueError, TypeError):
        return to_float(value)


def usd_cents_to_float(value: Any) -> float | None:
    """Convert Renaiss USD integer cents to a decimal dollar value."""
    return _scaled_decimal(value, "100")


def usdt_wei_to_float(value: Any) -> float | None:
    """Convert Renaiss USDT wei (18 decimals) to a decimal USDT value."""
    return _scaled_decimal(value, "1000000000000000000")


def money_amount_to_float(value: Any, token: Any = None) -> float | None:
    """Convert a Renaiss amount object or raw scalar to a display number.

    The official CLI uses integer cents for USD and 18-decimal wei for USDT.
    Generic/plain values are still accepted for backward compatibility.
    """
    if isinstance(value, dict):
        token = first_value(value, ["token", "currency", "symbol"], token)
        value = first_value(value, ["value", "amount", "price"])
    token_text = str(token or "").strip().upper()
    if token_text == "USDT":
        return usdt_wei_to_float(value)
    if token_text == "USD":
        return usd_cents_to_float(value)
    return to_float(value)


def to_int(value: Any) -> int | None:
    number = to_float(value)
    return int(number) if number is not None else None


def to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = strip_ansi(str(value)).strip().lower()
    if text in {"true", "yes", "y", "1", "listed", "active", "on sale", "for sale"}:
        return True
    if text in {"false", "no", "n", "0", "unlisted", "inactive", "not listed", "not for sale"}:
        return False
    return None


def first_value(mapping: dict[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    normalized = {normalize_key(str(k)): v for k, v in mapping.items()}
    for key in keys:
        normalized_key = normalize_key(key)
        if normalized_key in normalized and normalized[normalized_key] is not None:
            return normalized[normalized_key]
    return default


def nested_value(mapping: dict[str, Any], paths: Iterable[str], default: Any = None) -> Any:
    for path in paths:
        current: Any = mapping
        ok = True
        for part in path.split("."):
            if not isinstance(current, dict):
                ok = False
                break
            match = next((key for key in current if normalize_key(str(key)) == normalize_key(part)), None)
            if match is None:
                ok = False
                break
            current = current[match]
        if ok and current is not None:
            return current
    return default


def display_owner(value: Any, fallback: Any = None) -> Any:
    if isinstance(value, dict):
        return first_value(value, ["username", "name", "address"], fallback)
    return value if value is not None else fallback


def parse_key_value_lines(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in strip_ansi(raw or "").splitlines():
        stripped = line.strip().lstrip("•-* ")
        match = re.match(r"^([^:：]{2,60})\s*[:：]\s*(.+)$", stripped)
        if match:
            result[normalize_key(match.group(1))] = match.group(2).strip()
    return result


def split_table_line(line: str) -> list[str]:
    line = strip_ansi(line).strip().strip("|")
    if "|" in line:
        return [cell.strip() for cell in line.split("|")]
    return [cell.strip() for cell in re.split(r"\s{2,}|\t+", line) if cell.strip()]


def parse_text_tables(raw: str) -> list[list[dict[str, str]]]:
    """Parse pipe or aligned whitespace tables into row dictionaries."""
    lines = strip_ansi(raw or "").splitlines()
    tables: list[list[dict[str, str]]] = []
    i = 0
    while i < len(lines):
        cells = split_table_line(lines[i])
        if len(cells) < 2:
            i += 1
            continue
        next_cells = split_table_line(lines[i + 1]) if i + 1 < len(lines) else []
        separator = bool(next_cells) and all(re.fullmatch(r":?-{2,}:?", cell or "") for cell in next_cells)
        likely_header = separator or any(
            normalize_key(cell) in {
                "token_id", "token", "id", "name", "price", "rarity", "pack", "slug",
                "time", "timestamp", "date", "type", "event", "owner", "listed", "status",
            }
            for cell in cells
        )
        if not likely_header:
            i += 1
            continue

        headers = [normalize_key(cell) or f"column_{idx}" for idx, cell in enumerate(cells)]
        j = i + (2 if separator else 1)
        rows: list[dict[str, str]] = []
        while j < len(lines):
            row_cells = split_table_line(lines[j])
            if len(row_cells) != len(headers):
                break
            if all(re.fullmatch(r"[-:]+", cell or "") for cell in row_cells):
                j += 1
                continue
            rows.append(dict(zip(headers, row_cells)))
            j += 1
        if rows:
            tables.append(rows)
            i = j
        else:
            i += 1
    return tables


def ensure_iso_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit() and len(text) >= 10:
            timestamp = int(text)
            if timestamp > 10_000_000_000:
                timestamp //= 1000
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
        normalized = text.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y %H:%M"):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            else:
                return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def extract_list(payload: Any, candidate_keys: Iterable[str]) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in candidate_keys:
        value = first_value(payload, [key])
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = extract_list(value, candidate_keys)
            if nested:
                return nested
    data = first_value(payload, ["data", "result", "response"])
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and data is not payload:
        return extract_list(data, candidate_keys)
    return []
