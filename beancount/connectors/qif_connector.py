"""QIF (Quicken Interchange Format) connector.

Parses QIF files exported from Quicken, Microsoft Money, and
other personal finance software into beancount transactions.
"""

from __future__ import annotations

__copyright__ = "Copyright (C) 2026  Beancount Contributors"
__license__ = "GNU GPLv2"

import datetime
import re
from decimal import Decimal
from decimal import InvalidOperation
from os import path
from typing import Any

from beancount.connectors.base import BaseConnector
from beancount.core import data
from beancount.core.amount import Amount
from beancount.core.number import D


# QIF account type codes to beancount account prefixes.
_QIF_ACCOUNT_TYPES = {
    "Bank": "Assets:Bank",
    "Cash": "Assets:Cash",
    "CCard": "Liabilities:CreditCard",
    "Invst": "Assets:Investments",
    "Oth A": "Assets:Other",
    "Oth L": "Liabilities:Other",
}


class QIFConnector(BaseConnector):
    """Import transactions from QIF (Quicken Interchange Format) files.

    Supports:
      - Bank, Cash, CCard, and Investment account types
      - Split transactions
      - Category and memo fields
      - Multiple date formats (M/D/Y and D/M/Y)
    """

    def __init__(self):
        super().__init__()
        self.date_format: str = "us"  # "us" (M/D/Y) or "eu" (D/M/Y)
        self.category_prefix: str = "Expenses"

    def identify(self, filepath: str) -> bool:
        """Check if the file is a QIF file."""
        ext = path.splitext(filepath)[1].lower()
        if ext == ".qif":
            return True

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
            return first_line.startswith("!Type:") or first_line.startswith("!Account")
        except (OSError, UnicodeDecodeError):
            return False

    def extract(self, filepath: str) -> data.Directives:
        """Extract transactions from a QIF file.

        Args:
          filepath: Path to the QIF file.
        Returns:
          A list of Transaction directives.
        Raises:
          ValueError: If the file exceeds the size limit.
        """
        self._check_file_size(filepath)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            return []

        entries = self._parse_qif(content, filepath)
        entries.sort(key=data.entry_sortkey)
        return entries

    def _parse_qif(self, content: str, filepath: str) -> data.Directives:
        """Parse QIF content into directives."""
        entries: data.Directives = []
        current_account_type = None
        current_record: dict[str, Any] = {}
        splits: list[dict[str, str]] = []
        line_num = 0

        for line in content.splitlines():
            line_num += 1
            line = line.strip()
            if not line:
                continue

            # Account type header.
            if line.startswith("!Type:"):
                current_account_type = line[6:].strip()
                continue
            if line.startswith("!Account") or line.startswith("!Option") or line.startswith("!Clear"):
                continue

            # Record delimiter.
            if line == "^":
                entry = self._record_to_transaction(
                    current_record, splits, current_account_type, filepath, line_num
                )
                if entry is not None:
                    entries.append(entry)
                current_record = {}
                splits = []
                continue

            # Parse field codes.
            code = line[0]
            value = line[1:]

            if code == "D":
                current_record["date"] = value
            elif code == "T" or code == "U":
                current_record["amount"] = value
            elif code == "P":
                current_record["payee"] = value
            elif code == "M":
                current_record["memo"] = value
            elif code == "L":
                current_record["category"] = value
            elif code == "N":
                current_record["number"] = value
            elif code == "C":
                current_record["cleared"] = value
            elif code == "A":
                # Address lines (ignored).
                pass
            elif code == "S":
                # Split category.
                splits.append({"category": value})
            elif code == "E":
                # Split memo.
                if splits:
                    splits[-1]["memo"] = value
            elif code == "$":
                # Split amount.
                if splits:
                    splits[-1]["amount"] = value

        # Handle last record if no trailing ^.
        if current_record:
            entry = self._record_to_transaction(
                current_record, splits, current_account_type, filepath, line_num
            )
            if entry is not None:
                entries.append(entry)

        return entries

    def _record_to_transaction(
        self,
        record: dict[str, Any],
        splits: list[dict[str, str]],
        account_type: str | None,
        filepath: str,
        line_num: int,
    ) -> data.Transaction | None:
        """Convert a QIF record to a Transaction."""
        if "date" not in record:
            return None

        txn_date = self._parse_date(record["date"])
        if txn_date is None:
            return None

        # Parse amount.
        amount_str = record.get("amount", "0")
        amount_num = self._parse_amount(amount_str)
        if amount_num is None:
            return None

        payee = record.get("payee")
        memo = record.get("memo", "")
        category = record.get("category", "")
        narration = memo or category or (payee or "QIF Transaction")

        # Determine flag from cleared status.
        cleared = record.get("cleared", "")
        flag = "*" if cleared in ("X", "R", "*") else "!"

        meta = data.new_metadata(filepath, line_num)
        if record.get("number"):
            meta["check_number"] = record["number"]

        postings = []

        # Main posting to the source account.
        postings.append(
            data.Posting(
                account=self.default_account,
                units=Amount(amount_num, self.default_currency),
                cost=None,
                price=None,
                flag=None,
                meta=None,
            )
        )

        if splits:
            # Add split postings.
            for split in splits:
                split_amount = self._parse_amount(split.get("amount", "0"))
                if split_amount is None:
                    continue
                split_account = self._category_to_account(split.get("category", ""))
                postings.append(
                    data.Posting(
                        account=split_account,
                        units=Amount(-split_amount, self.default_currency),
                        cost=None,
                        price=None,
                        flag=None,
                        meta=None,
                    )
                )
        else:
            # Single offsetting posting to the category account.
            offset_account = self._category_to_account(category)
            postings.append(
                data.Posting(
                    account=offset_account,
                    units=Amount(-amount_num, self.default_currency),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                )
            )

        return data.Transaction(
            meta=meta,
            date=txn_date,
            flag=flag,
            payee=payee,
            narration=narration,
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=postings,
        )

    def _category_to_account(self, category: str) -> str:
        """Convert a QIF category to a beancount account name.

        QIF categories use ':' separators (e.g. "Food:Groceries").
        Transfers use square brackets (e.g. "[Checking]").
        """
        if not category:
            return f"{self.category_prefix}:Uncategorized"

        # Transfer to another account.
        if category.startswith("[") and category.endswith("]"):
            account_name = category[1:-1].replace(" ", "-")
            return f"Assets:{account_name}"

        # Regular category — sanitize for beancount account names.
        parts = category.split(":")
        clean_parts = []
        for part in parts:
            # Capitalize first letter, replace invalid chars.
            cleaned = re.sub(r"[^A-Za-z0-9-]", "", part.strip().replace(" ", "-"))
            if cleaned:
                cleaned = cleaned[0].upper() + cleaned[1:] if len(cleaned) > 1 else cleaned.upper()
                clean_parts.append(cleaned)

        if not clean_parts:
            return f"{self.category_prefix}:Uncategorized"

        return f"{self.category_prefix}:{':'.join(clean_parts)}"

    def _parse_date(self, text: str) -> datetime.date | None:
        """Parse a QIF date string.

        Common QIF date formats:
          - M/D/Y  or M/D'Y  (US format)
          - D/M/Y  or D/M'Y  (EU format)
          - M-D-Y
        The year may be 2-digit (with ' prefix in old Quicken).
        """
        text = text.strip()
        # Normalize: replace ' with / (Quicken sometimes uses ' for year separator).
        text = text.replace("'", "/").replace("-", "/")

        parts = text.split("/")
        if len(parts) != 3:
            return None

        try:
            if self.date_format == "eu":
                day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            else:
                month, day, year = int(parts[0]), int(parts[1]), int(parts[2])

            # Handle 2-digit year.
            if year < 100:
                year += 2000 if year < 50 else 1900

            return datetime.date(year, month, day)
        except (ValueError, OverflowError):
            return None

    def _parse_amount(self, text: str) -> Decimal | None:
        """Parse a QIF amount string."""
        text = text.strip()
        text = text.replace(",", "")
        if not text:
            return None
        try:
            return D(text)
        except InvalidOperation:
            return None

    def _apply_config(self, config: dict[str, Any]) -> None:
        """Apply QIF-specific configuration."""
        super()._apply_config(config)
        if "date_format" in config:
            self.date_format = config["date_format"]
        if "category_prefix" in config:
            self.category_prefix = config["category_prefix"]
