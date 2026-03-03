"""CSV file connector for importing bank/credit card statements.

Supports configurable column mapping to extract dates, amounts,
payees, and narrations from arbitrary CSV formats.
"""

from __future__ import annotations

__copyright__ = "Copyright (C) 2026  Beancount Contributors"
__license__ = "GNU GPLv2"

import csv
import datetime
import logging
import re
from decimal import Decimal
from decimal import InvalidOperation
from os import path
from typing import Any

log = logging.getLogger(__name__)

from beancount.connectors.base import BaseConnector
from beancount.core import data
from beancount.core.amount import Amount
from beancount.core.number import D


# Common date format patterns to try during auto-detection.
_DATE_FORMATS = [
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%m-%d-%Y",
    "%d-%m-%Y",
    "%m/%d/%y",
    "%d/%m/%y",
    "%Y%m%d",
]


class CSVConnector(BaseConnector):
    """Import transactions from CSV files.

    Configuration options (via config file or direct assignment):
      - date_column: Column name or index for the date field.
      - amount_column: Column name or index for the amount field.
      - payee_column: Column name or index for the payee field.
      - narration_column: Column name or index for the narration/description.
      - balance_column: Column name or index for running balance.
      - currency: Default currency for amounts.
      - date_format: strptime format string for dates.
      - skip_lines: Number of header lines to skip.
      - invert_amounts: Whether to negate amounts (for credit card statements).
      - encoding: File encoding (default: utf-8).
    """

    def __init__(self):
        super().__init__()
        self.date_column: str | int | None = None
        self.amount_column: str | int | None = None
        self.payee_column: str | int | None = None
        self.narration_column: str | int | None = None
        self.balance_column: str | int | None = None
        self.date_format: str | None = None
        self.skip_lines: int = 0
        self.invert_amounts: bool = False
        self.encoding: str = "utf-8"

    def identify(self, filepath: str) -> bool:
        """Check if the file is a CSV file."""
        ext = path.splitext(filepath)[1].lower()
        return ext in (".csv", ".tsv", ".txt")

    def extract(self, filepath: str) -> data.Directives:
        """Extract transactions from a CSV file.

        Args:
          filepath: Path to the CSV file.
        Returns:
          A list of Transaction directives.
        Raises:
          ValueError: If the file exceeds the size limit.
        """
        self._check_file_size(filepath)
        rows = self._read_csv(filepath)
        if not rows:
            return []

        # Auto-detect column mapping if not configured.
        header = rows[0] if rows else {}
        col_map = self._resolve_columns(header)

        entries: data.Directives = []
        for row_num, row in enumerate(rows):
            try:
                entry = self._row_to_transaction(row, col_map, filepath, row_num)
                if entry is not None:
                    entries.append(entry)
            except (ValueError, KeyError, InvalidOperation) as exc:
                log.debug("Skipping CSV row %d: %s", row_num, exc)
                continue

        entries.sort(key=data.entry_sortkey)
        return entries

    def _read_csv(self, filepath: str) -> list[dict[str, str]]:
        """Read CSV file and return list of row dicts."""
        rows = []
        with open(filepath, encoding=self.encoding, newline="") as f:
            # Skip leading lines if configured.
            for _ in range(self.skip_lines):
                next(f, None)

            # Sniff delimiter.
            sample = f.read(4096)
            f.seek(0)
            for _ in range(self.skip_lines):
                next(f, None)

            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel

            reader = csv.DictReader(f, dialect=dialect)
            for row in reader:
                rows.append(row)
        return rows

    def _resolve_columns(self, sample_row: dict[str, str]) -> dict[str, str | None]:
        """Resolve column mapping from config or auto-detect from headers."""
        col_map: dict[str, str | None] = {
            "date": None,
            "amount": None,
            "payee": None,
            "narration": None,
            "balance": None,
        }

        keys = list(sample_row.keys())
        keys_lower = {k.lower().strip(): k for k in keys}

        # Apply configured columns.
        if self.date_column is not None:
            col_map["date"] = self._resolve_col(self.date_column, keys)
        if self.amount_column is not None:
            col_map["amount"] = self._resolve_col(self.amount_column, keys)
        if self.payee_column is not None:
            col_map["payee"] = self._resolve_col(self.payee_column, keys)
        if self.narration_column is not None:
            col_map["narration"] = self._resolve_col(self.narration_column, keys)
        if self.balance_column is not None:
            col_map["balance"] = self._resolve_col(self.balance_column, keys)

        # Auto-detect from common column names.
        if col_map["date"] is None:
            for name in ("date", "transaction date", "posted date", "posting date", "trans date"):
                if name in keys_lower:
                    col_map["date"] = keys_lower[name]
                    break

        if col_map["amount"] is None:
            for name in ("amount", "debit", "credit", "transaction amount", "sum"):
                if name in keys_lower:
                    col_map["amount"] = keys_lower[name]
                    break

        if col_map["narration"] is None:
            for name in ("description", "narration", "memo", "details", "reference", "particulars"):
                if name in keys_lower:
                    col_map["narration"] = keys_lower[name]
                    break

        if col_map["payee"] is None:
            for name in ("payee", "merchant", "name", "vendor"):
                if name in keys_lower:
                    col_map["payee"] = keys_lower[name]
                    break

        if col_map["balance"] is None:
            for name in ("balance", "running balance", "available balance"):
                if name in keys_lower:
                    col_map["balance"] = keys_lower[name]
                    break

        return col_map

    def _resolve_col(self, col: str | int, keys: list[str]) -> str | None:
        """Resolve a column name or index to an actual header name."""
        if isinstance(col, int):
            return keys[col] if 0 <= col < len(keys) else None
        return col if col in keys else None

    def _row_to_transaction(
        self,
        row: dict[str, str],
        col_map: dict[str, str | None],
        filepath: str,
        row_num: int,
    ) -> data.Transaction | None:
        """Convert a CSV row to a Transaction directive."""
        # Parse date.
        date_col = col_map.get("date")
        if not date_col or date_col not in row:
            return None
        date_str = row[date_col].strip()
        if not date_str:
            return None
        txn_date = self._parse_date(date_str)
        if txn_date is None:
            return None

        # Parse amount.
        amount_col = col_map.get("amount")
        if not amount_col or amount_col not in row:
            return None
        amount_str = row[amount_col].strip()
        if not amount_str:
            return None
        amount_num = self._parse_amount(amount_str)
        if amount_num is None:
            return None

        if self.invert_amounts:
            amount_num = -amount_num

        # Parse payee and narration.
        payee = None
        payee_col = col_map.get("payee")
        if payee_col and payee_col in row:
            payee = row[payee_col].strip() or None

        narration = ""
        narration_col = col_map.get("narration")
        if narration_col and narration_col in row:
            narration = row[narration_col].strip()

        if not narration and payee:
            narration = payee

        # Create the transaction.
        meta = data.new_metadata(filepath, row_num)
        txn = data.Transaction(
            meta=meta,
            date=txn_date,
            flag="!",
            payee=payee,
            narration=narration,
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[
                data.Posting(
                    account=self.default_account,
                    units=Amount(amount_num, self.default_currency),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                ),
            ],
        )
        return txn

    def _parse_date(self, text: str) -> datetime.date | None:
        """Parse a date string, trying configured format first then common formats."""
        formats = [self.date_format] if self.date_format else []
        formats.extend(_DATE_FORMATS)

        for fmt in formats:
            if fmt is None:
                continue
            try:
                return datetime.datetime.strptime(text.strip(), fmt).date()
            except ValueError:
                continue
        return None

    def _parse_amount(self, text: str) -> Decimal | None:
        """Parse an amount string, handling commas and currency symbols."""
        text = text.strip()
        # Remove common currency symbols and whitespace.
        text = re.sub(r"[$€£¥₹\s]", "", text)
        # Handle parenthesized negatives: (123.45) -> -123.45
        if text.startswith("(") and text.endswith(")"):
            text = "-" + text[1:-1]
        # Remove thousands separators.
        text = text.replace(",", "")
        if not text:
            return None
        try:
            return D(text)
        except InvalidOperation:
            return None

    def _apply_config(self, config: dict[str, Any]) -> None:
        """Apply CSV-specific configuration."""
        super()._apply_config(config)
        if "date_column" in config:
            self.date_column = config["date_column"]
        if "amount_column" in config:
            self.amount_column = config["amount_column"]
        if "payee_column" in config:
            self.payee_column = config["payee_column"]
        if "narration_column" in config:
            self.narration_column = config["narration_column"]
        if "balance_column" in config:
            self.balance_column = config["balance_column"]
        if "date_format" in config:
            self.date_format = config["date_format"]
        if "skip_lines" in config:
            self.skip_lines = int(config["skip_lines"])
        if "invert_amounts" in config:
            self.invert_amounts = bool(config["invert_amounts"])
        if "encoding" in config:
            self.encoding = config["encoding"]
