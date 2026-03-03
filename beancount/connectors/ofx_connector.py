"""OFX/QFX file connector for importing bank statements.

Parses OFX (Open Financial Exchange) and QFX (Quicken Financial
Exchange) files into beancount transactions.
"""

from __future__ import annotations

__copyright__ = "Copyright (C) 2026  Beancount Contributors"
__license__ = "GNU GPLv2"

import datetime
import re
import xml.etree.ElementTree as ET
from decimal import Decimal
from os import path
from typing import Any

from beancount.connectors.base import BaseConnector
from beancount.core import data
from beancount.core.amount import Amount
from beancount.core.number import D


class OFXConnector(BaseConnector):
    """Import transactions from OFX/QFX files.

    Supports both OFX 1.x (SGML) and OFX 2.x (XML) formats.
    """

    def __init__(self):
        super().__init__()
        self.account_map: dict[str, str] = {}

    def identify(self, filepath: str) -> bool:
        """Check if the file is an OFX/QFX file."""
        ext = path.splitext(filepath)[1].lower()
        if ext in (".ofx", ".qfx"):
            return True

        # Check file header for OFX signature.
        try:
            with open(filepath, "r", encoding="latin-1") as f:
                header = f.read(256)
            return "OFXHEADER" in header or "<OFX>" in header
        except (OSError, UnicodeDecodeError):
            return False

    def extract(self, filepath: str) -> data.Directives:
        """Extract transactions from an OFX/QFX file.

        Args:
          filepath: Path to the OFX file.
        Returns:
          A list of Transaction directives.
        """
        content = self._read_ofx(filepath)
        if content is None:
            return []

        transactions = self._parse_transactions(content, filepath)
        transactions.sort(key=data.entry_sortkey)
        return transactions

    def _read_ofx(self, filepath: str) -> str | None:
        """Read an OFX file, handling both SGML and XML formats."""
        try:
            with open(filepath, "r", encoding="latin-1") as f:
                content = f.read()
        except OSError:
            return None

        is_sgml = False

        # Strip SGML header if present (OFX 1.x).
        if "OFXHEADER" in content:
            is_sgml = True
            # Find the start of the actual OFX data.
            idx = content.find("<OFX>")
            if idx == -1:
                return None
            content = content[idx:]

        # Only convert SGML to XML for OFX 1.x files; leave valid XML alone.
        if is_sgml:
            content = self._sgml_to_xml(content)
        return content

    def _sgml_to_xml(self, content: str) -> str:
        """Convert OFX SGML to well-formed XML.

        OFX 1.x uses SGML with unclosed tags like <TRNAMT>100.00
        which need to be converted to <TRNAMT>100.00</TRNAMT> for
        XML parsing.
        """
        # Close tags that contain text content but no closing tag.
        # Match: <TAG>content where content doesn't start with <
        content = re.sub(
            r"<(\w+)>([^<]+?)(?=<|\Z)",
            r"<\1>\2</\1>",
            content,
        )
        # Wrap in root if needed.
        if not content.strip().startswith("<?xml"):
            content = '<?xml version="1.0" encoding="UTF-8"?>\n' + content

        return content

    def _parse_transactions(
        self, xml_content: str, filepath: str
    ) -> data.Directives:
        """Parse transactions from OFX XML content."""
        entries: data.Directives = []

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError:
            return entries

        # Find all transaction elements (STMTTRN).
        for trn in root.iter("STMTTRN"):
            entry = self._parse_stmttrn(trn, filepath)
            if entry is not None:
                entries.append(entry)

        return entries

    def _parse_stmttrn(
        self, trn: ET.Element, filepath: str
    ) -> data.Transaction | None:
        """Parse a single STMTTRN element into a Transaction."""
        # Extract fields.
        trntype = self._get_text(trn, "TRNTYPE")
        dtposted = self._get_text(trn, "DTPOSTED")
        trnamt = self._get_text(trn, "TRNAMT")
        fitid = self._get_text(trn, "FITID")
        name = self._get_text(trn, "NAME")
        memo = self._get_text(trn, "MEMO")

        if not dtposted or not trnamt:
            return None

        # Parse date (OFX format: YYYYMMDD or YYYYMMDDHHMMSS).
        try:
            date_str = dtposted[:8]
            txn_date = datetime.datetime.strptime(date_str, "%Y%m%d").date()
        except (ValueError, IndexError):
            return None

        # Parse amount.
        try:
            amount_num = D(trnamt.strip())
        except (ArithmeticError, ValueError):
            return None

        # Determine payee and narration.
        payee = name.strip() if name else None
        narration = memo.strip() if memo else (name.strip() if name else "OFX Transaction")

        # Build metadata.
        meta = data.new_metadata(filepath, 0)
        if fitid:
            meta["ofx_fitid"] = fitid
        if trntype:
            meta["ofx_type"] = trntype

        # Create the transaction.
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

    def _get_text(self, element: ET.Element, tag: str) -> str | None:
        """Get text content of a child element."""
        child = element.find(tag)
        if child is not None and child.text:
            return child.text.strip()
        return None

    def _apply_config(self, config: dict[str, Any]) -> None:
        """Apply OFX-specific configuration."""
        super()._apply_config(config)
        if "account_map" in config:
            self.account_map = config["account_map"]
