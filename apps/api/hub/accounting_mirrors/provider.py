import asyncio
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.parse import quote

import requests

from hub.accounting.xlsx_styles import (
    BLACK,
    COLUMN_HEADER,
    DAY_HEADER,
    EXPENSE_AMOUNT,
    EXPENSE_CELL,
    EXPENSE_HEADER,
    JOB_AMOUNT,
    JOB_CELL,
    SUMMARY_AMOUNT,
    SUMMARY_CELL,
    SUMMARY_HEADER,
    TECHNICIAN_TITLE,
    TOTAL_VALUE,
    WEEK_LABEL,
    WEEK_METADATA,
    WRAPPED_CELL,
    CellStyle,
)
from hub.accounting_mirrors.presentation import SheetsPayload

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
TIMEOUT = (5, 20)


@dataclass(frozen=True)
class SheetMetadata:
    sheet_id: int
    title: str
    rows: int
    columns: int


class SheetsProviderError(Exception):
    CODES = {
        "SHEETS_PERMISSION_REQUIRED",
        "SPREADSHEET_NOT_FOUND",
        "RATE_LIMITED",
        "PROVIDER_TEMPORARY_ERROR",
        "MALFORMED_RESPONSE",
        "CONFIGURATION_ERROR",
    }

    def __init__(self, code: str, *, retryable: bool = False, retry_after: int = 60):
        self.code = code if code in self.CODES else "PROVIDER_TEMPORARY_ERROR"
        self.retryable = retryable
        self.retry_after = min(max(retry_after, 1), 3600)
        super().__init__(self.code)


class SheetsProvider(Protocol):
    async def get_spreadsheet_metadata(
        self, access_token: str, spreadsheet_id: str
    ) -> tuple[SheetMetadata, ...]: ...
    async def add_sheet(
        self, access_token: str, spreadsheet_id: str, title: str, rows: int, columns: int
    ) -> SheetMetadata: ...
    async def clear_owned_range(
        self, access_token: str, spreadsheet_id: str, sheet_id: int, rows: int, columns: int
    ) -> None: ...
    async def write_values(
        self,
        access_token: str,
        spreadsheet_id: str,
        sheet_title: str,
        values: tuple[tuple[object, ...], ...],
    ) -> None: ...
    async def batch_update_formatting(
        self,
        access_token: str,
        spreadsheet_id: str,
        sheet_id: int,
        payload: SheetsPayload,
        current_rows: int,
        current_columns: int,
    ) -> None: ...


ROLE_STYLES = {
    "TECHNICIAN_TITLE": TECHNICIAN_TITLE,
    "WEEK_METADATA": WEEK_METADATA,
    "WEEK_LABEL": WEEK_LABEL,
    "DAY_HEADER": DAY_HEADER,
    "COLUMN_HEADER": COLUMN_HEADER,
    "JOB_CELL": JOB_CELL,
    "WRAPPED_CELL": WRAPPED_CELL,
    "JOB_AMOUNT": JOB_AMOUNT,
    "EXPENSE_HEADER": EXPENSE_HEADER,
    "EXPENSE_CELL": EXPENSE_CELL,
    "EXPENSE_AMOUNT": EXPENSE_AMOUNT,
    "SUMMARY_CELL": SUMMARY_CELL,
    "SUMMARY_AMOUNT": SUMMARY_AMOUNT,
    "SUMMARY_HEADER": SUMMARY_HEADER,
    "TOTAL_VALUE": TOTAL_VALUE,
}


def _color(value: str) -> dict[str, float]:
    return {
        "red": int(value[0:2], 16) / 255,
        "green": int(value[2:4], 16) / 255,
        "blue": int(value[4:6], 16) / 255,
    }


def _format(style: CellStyle) -> dict:
    value: dict = {
        "textFormat": {
            "fontFamily": style.font_name,
            "fontSize": style.font_size,
            "bold": style.bold,
            "foregroundColorStyle": {"rgbColor": _color(style.font_color)},
        },
        "verticalAlignment": "MIDDLE",
    }
    if style.fill_color:
        value["backgroundColorStyle"] = {"rgbColor": _color(style.fill_color)}
    if style.horizontal:
        value["horizontalAlignment"] = style.horizontal.upper()
    if style.wrap_text:
        value["wrapStrategy"] = "WRAP"
    # Currency is exact RAW text, so no numeric numberFormat is applied in Sheets.
    if style.bordered:
        border = {"style": "SOLID", "colorStyle": {"rgbColor": _color(BLACK)}}
        value["borders"] = {name: border for name in ("top", "bottom", "left", "right")}
    return value


def formatting_requests(
    sheet_id: int, payload: SheetsPayload, rows: int, columns: int
) -> list[dict]:
    requests_: list[dict] = [
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {
                        "rowCount": max(rows, payload.row_count, 1),
                        "columnCount": max(columns, payload.column_count, 1),
                    },
                },
                "fields": "gridProperties(rowCount,columnCount)",
            }
        }
    ]
    for item in payload.formats:
        requests_.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": item.start_row,
                        "endRowIndex": item.end_row,
                        "startColumnIndex": item.start_column,
                        "endColumnIndex": item.end_column,
                    },
                    "cell": {"userEnteredFormat": _format(ROLE_STYLES[item.role])},
                    "fields": "userEnteredFormat",
                }
            }
        )
    for item in payload.row_heights:
        requests_.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": item.index,
                        "endIndex": item.index + 1,
                    },
                    "properties": {"pixelSize": item.pixels},
                    "fields": "pixelSize",
                }
            }
        )
    for item in payload.column_widths:
        requests_.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": item.index,
                        "endIndex": item.index + 1,
                    },
                    "properties": {"pixelSize": item.pixels},
                    "fields": "pixelSize",
                }
            }
        )
    return requests_


def _retry_after(response: requests.Response) -> int:
    value = response.headers.get("Retry-After", "60")
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            return max(1, math.ceil((retry_at - datetime.now(UTC)).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            return 60


class GoogleSheetsHttpMixin:
    async def _sheets_request(self, method: str, path: str, access_token: str, body=None):
        def call():
            try:
                with requests.Session() as session:
                    session.trust_env = False
                    response = session.request(
                        method,
                        f"{SHEETS_API}/{path}",
                        headers={"Authorization": f"Bearer {access_token}"},
                        json=body,
                        timeout=TIMEOUT,
                        allow_redirects=False,
                    )
                if response.status_code == 401 or response.status_code == 403:
                    raise SheetsProviderError("SHEETS_PERMISSION_REQUIRED")
                if response.status_code == 404:
                    raise SheetsProviderError("SPREADSHEET_NOT_FOUND")
                if response.status_code == 429:
                    raise SheetsProviderError(
                        "RATE_LIMITED", retryable=True, retry_after=_retry_after(response)
                    )
                if response.status_code >= 500:
                    raise SheetsProviderError("PROVIDER_TEMPORARY_ERROR", retryable=True)
                if not 200 <= response.status_code < 300:
                    raise SheetsProviderError("CONFIGURATION_ERROR")
                if response.status_code == 204 or not response.content:
                    return {}
                data = response.json()
                if not isinstance(data, dict):
                    raise SheetsProviderError("MALFORMED_RESPONSE")
                return data
            except SheetsProviderError:
                raise
            except (requests.RequestException, ValueError, json.JSONDecodeError):
                raise SheetsProviderError("PROVIDER_TEMPORARY_ERROR", retryable=True) from None

        task = asyncio.create_task(asyncio.to_thread(call))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            except Exception:
                pass
            raise

    async def get_spreadsheet_metadata(self, access_token, spreadsheet_id):
        data = await self._sheets_request(
            "GET",
            f"{quote(spreadsheet_id, safe='')}?fields="
            "sheets.properties(sheetId,title,gridProperties)",
            access_token,
        )
        try:
            return tuple(
                SheetMetadata(
                    int(item["properties"]["sheetId"]),
                    str(item["properties"]["title"]),
                    int(item["properties"].get("gridProperties", {}).get("rowCount", 0)),
                    int(item["properties"].get("gridProperties", {}).get("columnCount", 0)),
                )
                for item in data.get("sheets", [])
            )
        except (KeyError, TypeError, ValueError):
            raise SheetsProviderError("MALFORMED_RESPONSE") from None

    async def add_sheet(self, access_token, spreadsheet_id, title, rows, columns):
        data = await self._sheets_request(
            "POST",
            f"{quote(spreadsheet_id, safe='')}:batchUpdate",
            access_token,
            {
                "requests": [
                    {
                        "addSheet": {
                            "properties": {
                                "title": title,
                                "gridProperties": {
                                    "rowCount": max(rows, 1),
                                    "columnCount": max(columns, 1),
                                },
                            }
                        }
                    }
                ]
            },
        )
        try:
            value = data["replies"][0]["addSheet"]["properties"]
            return SheetMetadata(
                int(value["sheetId"]),
                str(value["title"]),
                int(value["gridProperties"]["rowCount"]),
                int(value["gridProperties"]["columnCount"]),
            )
        except (KeyError, IndexError, TypeError, ValueError):
            raise SheetsProviderError("MALFORMED_RESPONSE") from None

    async def clear_owned_range(self, access_token, spreadsheet_id, sheet_id, rows, columns):
        if rows <= 0 or columns <= 0:
            return
        await self._sheets_request(
            "POST",
            f"{quote(spreadsheet_id, safe='')}:batchUpdate",
            access_token,
            {
                "requests": [
                    {
                        "updateCells": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": 0,
                                "endRowIndex": rows,
                                "startColumnIndex": 0,
                                "endColumnIndex": columns,
                            },
                            "fields": "userEnteredValue,userEnteredFormat",
                        }
                    },
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "ROWS",
                                "startIndex": 0,
                                "endIndex": rows,
                            },
                            "properties": {},
                            "fields": "pixelSize",
                        }
                    },
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "COLUMNS",
                                "startIndex": 0,
                                "endIndex": columns,
                            },
                            "properties": {},
                            "fields": "pixelSize",
                        }
                    },
                ]
            },
        )

    async def write_values(self, access_token, spreadsheet_id, sheet_title, values):
        # Bound request bodies while preserving one RAW operation per row chunk.
        start = 0
        while start < len(values):
            end = min(start + 500, len(values))
            chunk = values[start:end]
            encoded = json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
            while len(encoded.encode()) > 4_000_000 and end - start > 1:
                end = start + max(1, (end - start) // 2)
                chunk = values[start:end]
                encoded = json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
            quoted_title = sheet_title.replace("'", "''")
            a1 = quote(f"'{quoted_title}'!A{start + 1}", safe="")
            await self._sheets_request(
                "PUT",
                f"{quote(spreadsheet_id, safe='')}/values/{a1}?valueInputOption=RAW",
                access_token,
                {"majorDimension": "ROWS", "values": [list(row) for row in chunk]},
            )
            start = end

    async def batch_update_formatting(
        self, access_token, spreadsheet_id, sheet_id, payload, current_rows, current_columns
    ):
        requests_ = formatting_requests(sheet_id, payload, current_rows, current_columns)
        for start in range(0, len(requests_), 400):
            await self._sheets_request(
                "POST",
                f"{quote(spreadsheet_id, safe='')}:batchUpdate",
                access_token,
                {"requests": requests_[start : start + 400]},
            )
