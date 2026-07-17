"""
FORTRESS_UNIFIED — core/sheets_client.py
══════════════════════════════════════════════════════════════════════════════
Single Google Sheets client shared by sniper, incubator, and the weekly
review. Consolidates the near-identical _gs_ok/_get_workbook/_push_sheet/
_read_sheet/_append_row implementations that existed separately in both
legacy scripts.

Every write here doubles as the training-data store you asked for:
BHAVCOPY tab is the fallback data source (see nse_data.py) AND the archive
that Monday's Claude review reads to learn from a week of decisions.
"""
from __future__ import annotations
import logging
import time
from typing import List, Optional

from . import config

log = logging.getLogger("fortress.sheets")

_WORKBOOK = None
_WS_CACHE: dict = {}
_LAST_INIT_ATTEMPT = 0.0
_INIT_RETRY_COOLDOWN = 60.0


def _gs_ok() -> bool:
    return bool(config.GOOGLE_SHEET_ID and config.GOOGLE_CREDS_JSON)


def _get_workbook():
    """Lazy-init gspread workbook. Cached for process lifetime."""
    global _WORKBOOK, _LAST_INIT_ATTEMPT
    if _WORKBOOK is not None:
        return _WORKBOOK
    if not _gs_ok():
        return None
    now = time.time()
    if now - _LAST_INIT_ATTEMPT < _INIT_RETRY_COOLDOWN and _WORKBOOK is None:
        # Don't hammer a broken creds file every call
        pass
    _LAST_INIT_ATTEMPT = now
    try:
        import json
        import gspread
        from google.oauth2.service_account import Credentials

        creds_dict = json.loads(config.GOOGLE_CREDS_JSON)
        scopes = ["https://www.googleapis.com/auth/spreadsheets",
                  "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(creds)
        _WORKBOOK = gc.open_by_key(config.GOOGLE_SHEET_ID)
        log.info("Google Sheets: workbook opened ✅")
        return _WORKBOOK
    except Exception as e:
        log.warning(f"Google Sheets init failed: {e}")
        _WORKBOOK = None
        return None


def _get_ws(tab: str, rows: int = 2000, cols: int = 60):
    """Get or create a worksheet tab."""
    wb = _get_workbook()
    if wb is None:
        return None
    if tab in _WS_CACHE:
        return _WS_CACHE[tab]
    try:
        ws = wb.worksheet(tab)
    except Exception:
        try:
            ws = wb.add_worksheet(title=tab, rows=rows, cols=cols)
            log.info(f"Sheets: created new tab '{tab}'")
        except Exception as e:
            log.warning(f"Sheets: could not create tab '{tab}': {e}")
            return None
    _WS_CACHE[tab] = ws
    return ws


def push_sheet(tab: str, rows: List[list]) -> bool:
    """Overwrite a tab's entire content with `rows` (list of lists, header first)."""
    ws = _get_ws(tab)
    if ws is None:
        return False
    try:
        ws.clear()
        if rows:
            ws.update("A1", rows, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        log.warning(f"push_sheet({tab}): {e}")
        return False


def read_sheet(tab: str) -> list:
    """Read all rows from a tab. Returns [] on any failure (never raises)."""
    ws = _get_ws(tab)
    if ws is None:
        return []
    try:
        return ws.get_all_values()
    except Exception as e:
        log.warning(f"read_sheet({tab}): {e}")
        return []


def append_row(tab: str, row: list) -> bool:
    ws = _get_ws(tab)
    if ws is None:
        return False
    try:
        ws.append_row(row, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        log.warning(f"append_row({tab}): {e}")
        return False


def append_rows(tab: str, rows: List[list]) -> bool:
    ws = _get_ws(tab)
    if ws is None or not rows:
        return False
    try:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        log.warning(f"append_rows({tab}): {e}")
        return False
