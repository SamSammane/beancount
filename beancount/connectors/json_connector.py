"""JSON connector for importing structured transaction data.

Handles JSON files containing transaction arrays, supporting both
flat structures and nested formats commonly used by fintech APIs
and export tools.
"""

from __future__ import annotations

__copyright__ = "Copyright (C) 2026  Beancount Contributors"
__license__ = "GNU GPLv2"

import datetime
import json
from decimal import Decimal
from decimal import InvalidOperation
from os import path
from typing import Any

from beancount.connectors.base import BaseConnector
from beancount.core import data
from beancount.core.amount import Amount
from beancount.core.number import D


# Common field name patterns for auto-detection.
_DATE_FIELDS = ("date", "transaction_date", "posted_date", "transactionDate", "postedDate", "dt")
_AMOUNT_FIELDS = ("amount", "total", "value", "sum", "transactionAmount")
_PAYEE_FIELDS = ("payee", "merchant", "merchant_name", "merchantName", "vendor", "name")
_NARRATION_FIELDS = (
    "description", "narration", "memo", "details", "note", "reference",
    "transactionDescription",
)
_CURRENCY_FIELDS = ("currency", "currency_code", "currencyCode", "iso_currency_code")
_ID_FIELDS = ("id", "transaction_id", "transactionId", "fitid", "ref")


class JSONConnector(BaseConnector):
    """Import transactions from JSON files.

    Supports JSON files with:
      - Top-level array of transaction objects
      - Nested arrays under a configurable key (e.g. {"transactions": [...]})
      - Configurable field mapping for arbitrary schemas
      - Auto-detection of common field naming conventions

    Configuration options:
      - transactions_key: JSON path to the transactions array (dot-separated).
      - date_field: Field name for the transaction date.
      - amount_field: Field name for the amount.
      - payee_field: Field name for the payee.
      - narration_field: Field name for the narration.
      - currency_field: Field name for the currency.
      - id_field: Field name for a unique transaction ID.
      - date_format: strptime format for date parsing (default: ISO 8601).
      - negate_amounts: Whether to negate amounts.
    """

    def __init__(self):
        super().__init__()
        self.transactions_key: str | None = None
        self.date_field: str | None = None
        self.amount_field: str | None = None
        self.payee_field: str | None = None
        self.narration_field: str | None = None
        self.currency_field: str | None = None
        self.id_field: str | None = None
        self.date_format: str | None = None
        self.negate_amounts: bool = False
        self.encoding: str = "utf-8"

    def identify(self, filepath: str) -> bool:
        """Check if the file is a JSON file."""
        ext = path.splitext(filepath)[1].lower()
        if ext == ".json":
            return True

        # Try to parse as JSON.
        try:
            with open(filepath, "r", encoding=self.encoding) as f:
                content = f.read(1024)
            content = content.strip()
            return content.startswith("{") or content.startswith("[")
        except (OSError, UnicodeDecodeError):
            return False

    def extract(self, filepath: str) -> data.Directives:
        """Extract transactions from a JSON file.

        Args:
          filepath: Path to the JSON file.
        Returns:
          A list of Transaction directives.
        Raises:
          ValueError: If the file exceeds the size limit.
        """
        self._check_file_size(filepath)
        try:
            with open(filepath, "r", encoding=self.encoding) as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError):
            return []

        transactions_list = self._extract_transactions_array(raw)
        if not transactions_list:
            return []

        # Auto-detect field mapping from the first record.
        field_map = self._resolve_fields(transactions_list[0])

        entries: data.Directives = []
        for idx, record in enumerate(transactions_list):
            entry = self._record_to_transaction(record, field_map, filepath, idx)
            if entry is not None:
                entries.append(entry)

        entries.sort(key=data.entry_sortkey)
        return entries

    def _extract_transactions_array(self, raw: Any) -> list[dict]:
        """Extract the transactions array from the raw JSON data."""
        if isinstance(raw, list):
            return [r for r in raw if isinstance(r, dict)]

        if not isinstance(raw, dict):
            return []

        # Follow configured key path.
        if self.transactions_key:
            obj = raw
            for key in self.transactions_key.split("."):
                if isinstance(obj, dict) and key in obj:
                    obj = obj[key]
                else:
                    return []
            if isinstance(obj, list):
                return [r for r in obj if isinstance(r, dict)]
            return []

        # Auto-detect: look for a list-valued key.
        for key in ("transactions", "data", "items", "records", "entries", "results"):
            if key in raw and isinstance(raw[key], list):
                return [r for r in raw[key] if isinstance(r, dict)]

        # Try any list-valued key.
        for key, val in raw.items():
            if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict):
                return [r for r in val if isinstance(r, dict)]

        return []

    def _resolve_fields(self, sample: dict) -> dict[str, str | None]:
        """Resolve field mapping from config or auto-detect."""
        field_map: dict[str, str | None] = {
            "date": self.date_field,
            "amount": self.amount_field,
            "payee": self.payee_field,
            "narration": self.narration_field,
            "currency": self.currency_field,
            "id": self.id_field,
        }

        keys = set(sample.keys())

        def find_field(candidates: tuple[str, ...]) -> str | None:
            # Exact match.
            for name in candidates:
                if name in keys:
                    return name
            # Case-insensitive match.
            keys_lower = {k.lower(): k for k in keys}
            for name in candidates:
                if name.lower() in keys_lower:
                    return keys_lower[name.lower()]
            return None

        if field_map["date"] is None:
            field_map["date"] = find_field(_DATE_FIELDS)
        if field_map["amount"] is None:
            field_map["amount"] = find_field(_AMOUNT_FIELDS)
        if field_map["payee"] is None:
            field_map["payee"] = find_field(_PAYEE_FIELDS)
        if field_map["narration"] is None:
            field_map["narration"] = find_field(_NARRATION_FIELDS)
        if field_map["currency"] is None:
            field_map["currency"] = find_field(_CURRENCY_FIELDS)
        if field_map["id"] is None:
            field_map["id"] = find_field(_ID_FIELDS)

        return field_map

    def _record_to_transaction(
        self,
        record: dict,
        field_map: dict[str, str | None],
        filepath: str,
        idx: int,
    ) -> data.Transaction | None:
        """Convert a JSON record to a Transaction."""
        # Parse date.
        date_field = field_map["date"]
        if not date_field or date_field not in record:
            return None
        txn_date = self._parse_date(str(record[date_field]))
        if txn_date is None:
            return None

        # Parse amount.
        amount_field = field_map["amount"]
        if not amount_field or amount_field not in record:
            return None
        amount_num = self._parse_amount(record[amount_field])
        if amount_num is None:
            return None

        if self.negate_amounts:
            amount_num = -amount_num

        # Currency.
        currency = self.default_currency
        currency_field = field_map.get("currency")
        if currency_field and currency_field in record:
            raw_curr = str(record[currency_field]).strip().upper()
            if raw_curr:
                currency = raw_curr

        # Payee and narration.
        payee = None
        payee_field = field_map.get("payee")
        if payee_field and payee_field in record:
            payee = str(record[payee_field]).strip() or None

        narration = ""
        narration_field = field_map.get("narration")
        if narration_field and narration_field in record:
            narration = str(record[narration_field]).strip()
        if not narration:
            narration = payee or "JSON Transaction"

        # Metadata.
        meta = data.new_metadata(filepath, idx)
        id_field = field_map.get("id")
        if id_field and id_field in record:
            meta["json_id"] = str(record[id_field])

        return data.Transaction(
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
                    units=Amount(amount_num, currency),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                ),
            ],
        )

    def _parse_date(self, text: str) -> datetime.date | None:
        """Parse a date from a JSON value (ISO 8601, epoch, or custom format)."""
        text = text.strip()

        # Custom format.
        if self.date_format:
            try:
                return datetime.datetime.strptime(text, self.date_format).date()
            except ValueError:
                pass

        # ISO 8601: "2024-01-15", "2024-01-15T10:30:00Z", etc.
        try:
            # Handle datetime strings by taking just the date part.
            date_part = text.split("T")[0].split(" ")[0]
            return datetime.date.fromisoformat(date_part)
        except (ValueError, IndexError):
            pass

        # Unix timestamp (seconds).
        try:
            ts = float(text)
            if ts > 1e9:  # Reasonable epoch range.
                return datetime.date.fromtimestamp(ts)
        except (ValueError, OverflowError, OSError):
            pass

        return None

    def _parse_amount(self, value: Any) -> Decimal | None:
        """Parse an amount from a JSON value (number or string)."""
        if isinstance(value, (int, float)):
            return D(str(value))
        if isinstance(value, str):
            text = value.strip().replace(",", "").replace("$", "").replace("€", "").replace("£", "")
            if not text:
                return None
            try:
                return D(text)
            except (InvalidOperation, ValueError):
                return None
        return None

    def _apply_config(self, config: dict[str, Any]) -> None:
        """Apply JSON-specific configuration."""
        super()._apply_config(config)
        if "transactions_key" in config:
            self.transactions_key = config["transactions_key"]
        if "date_field" in config:
            self.date_field = config["date_field"]
        if "amount_field" in config:
            self.amount_field = config["amount_field"]
        if "payee_field" in config:
            self.payee_field = config["payee_field"]
        if "narration_field" in config:
            self.narration_field = config["narration_field"]
        if "currency_field" in config:
            self.currency_field = config["currency_field"]
        if "id_field" in config:
            self.id_field = config["id_field"]
        if "date_format" in config:
            self.date_format = config["date_format"]
        if "negate_amounts" in config:
            self.negate_amounts = bool(config["negate_amounts"])
        if "encoding" in config:
            self.encoding = config["encoding"]
