"""Plaid API connector for live bank transaction feeds.

Connects to Plaid (https://plaid.com) to fetch real-time
transactions from linked bank accounts.

Requires the 'plaid-python' package and valid Plaid API credentials.
"""

from __future__ import annotations

__copyright__ = "Copyright (C) 2026  Beancount Contributors"
__license__ = "GNU GPLv2"

import datetime
import json
from decimal import Decimal
from os import path
from typing import Any

from beancount.connectors.base import BaseConnector
from beancount.core import data
from beancount.core.amount import Amount
from beancount.core.number import D


class PlaidConnector(BaseConnector):
    """Import transactions from Plaid-linked bank accounts.

    This connector can operate in two modes:

    1. **API mode**: Fetches transactions live from the Plaid API
       using client_id, secret, and an access_token.

    2. **File mode**: Reads a JSON file containing Plaid API response
       data (useful for testing, offline processing, or CI).

    Configuration:
      - client_id: Plaid client ID.
      - secret: Plaid secret key.
      - access_token: Plaid access token for a linked institution.
      - environment: "sandbox", "development", or "production".
      - account_map: Dict mapping Plaid account IDs to beancount accounts.
      - days_back: Number of days of history to fetch (default: 30).
    """

    def __init__(self):
        super().__init__()
        self.client_id: str = ""
        self.secret: str = ""
        self.access_token: str = ""
        self.environment: str = "sandbox"
        self.account_map: dict[str, str] = {}
        self.days_back: int = 30

    def identify(self, filepath: str) -> bool:
        """Check if the file is a Plaid JSON response.

        Identifies files that contain Plaid transaction response data
        (looking for the 'accounts' and 'transactions' keys).
        """
        ext = path.splitext(filepath)[1].lower()
        if ext != ".json":
            return False

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return (
                isinstance(raw, dict)
                and "accounts" in raw
                and "transactions" in raw
            )
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return False

    def extract(self, filepath: str) -> data.Directives:
        """Extract transactions from a Plaid response file or the API.

        If filepath points to a JSON file containing Plaid response
        data, parses it directly. Otherwise, if API credentials are
        configured, fetches transactions from the Plaid API.

        Args:
          filepath: Path to a Plaid JSON file, or a placeholder path
                    when using API mode.
        Returns:
          A list of Transaction directives.
        """
        if path.exists(filepath):
            return self._extract_from_file(filepath)
        elif self.access_token:
            return self._extract_from_api()
        return []

    def fetch_transactions(
        self,
        start_date: datetime.date | None = None,
        end_date: datetime.date | None = None,
    ) -> data.Directives:
        """Fetch transactions directly from the Plaid API.

        Args:
          start_date: Start of date range (default: days_back ago).
          end_date: End of date range (default: today).
        Returns:
          A list of Transaction directives.
        """
        return self._extract_from_api(start_date, end_date)

    def _extract_from_file(self, filepath: str) -> data.Directives:
        """Parse transactions from a Plaid JSON response file."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError):
            return []

        return self._parse_plaid_response(raw, filepath)

    def _extract_from_api(
        self,
        start_date: datetime.date | None = None,
        end_date: datetime.date | None = None,
    ) -> data.Directives:
        """Fetch and parse transactions from the Plaid API."""
        try:
            import plaid
            from plaid.api import plaid_api
            from plaid.model.transactions_get_request import TransactionsGetRequest
            from plaid.model.transactions_get_request_options import (
                TransactionsGetRequestOptions,
            )
        except ImportError:
            raise ImportError(
                "The 'plaid-python' package is required for Plaid API access. "
                "Install it with: pip install plaid-python"
            )

        if not self.client_id or not self.secret or not self.access_token:
            raise ValueError(
                "Plaid API credentials required: client_id, secret, and access_token. "
                "Set them via config file or connector attributes."
            )

        if end_date is None:
            end_date = datetime.date.today()
        if start_date is None:
            start_date = end_date - datetime.timedelta(days=self.days_back)

        # Configure Plaid client.
        env_map = {
            "sandbox": plaid.Environment.Sandbox,
            "development": plaid.Environment.Development,
            "production": plaid.Environment.Production,
        }
        configuration = plaid.Configuration(
            host=env_map.get(self.environment, plaid.Environment.Sandbox),
            api_key={
                "clientId": self.client_id,
                "secret": self.secret,
            },
        )

        api_client = plaid.ApiClient(configuration)
        client = plaid_api.PlaidApi(api_client)

        # Fetch transactions with pagination.
        all_transactions: list[dict] = []
        offset = 0
        max_pages = 100  # Safety limit to prevent infinite loops.

        for _ in range(max_pages):
            request = TransactionsGetRequest(
                access_token=self.access_token,
                start_date=start_date,
                end_date=end_date,
                options=TransactionsGetRequestOptions(
                    count=500,
                    offset=offset,
                ),
            )
            response = client.transactions_get(request)
            response_dict = response.to_dict()

            txns = response_dict.get("transactions", [])
            all_transactions.extend(txns)

            total_transactions = response_dict.get("total_transactions", 0) or 0
            offset += len(txns)

            if not txns or offset >= total_transactions:
                break

        # Also extract accounts for mapping.
        plaid_data = {
            "accounts": response_dict.get("accounts", []),
            "transactions": all_transactions,
        }
        return self._parse_plaid_response(plaid_data, "<plaid-api>")

    def _parse_plaid_response(
        self, response: dict, source: str
    ) -> data.Directives:
        """Parse a Plaid response dict into beancount directives."""
        entries: data.Directives = []

        # Build account ID -> name mapping from response.
        account_names: dict[str, str] = {}
        for acct in response.get("accounts", []):
            acct_id = acct.get("account_id", "")
            name = acct.get("name", "") or acct.get("official_name", "")
            account_names[acct_id] = name

        for idx, txn in enumerate(response.get("transactions", [])):
            entry = self._plaid_txn_to_transaction(txn, account_names, source, idx)
            if entry is not None:
                entries.append(entry)

        entries.sort(key=data.entry_sortkey)
        return entries

    def _plaid_txn_to_transaction(
        self,
        txn: dict,
        account_names: dict[str, str],
        source: str,
        idx: int,
    ) -> data.Transaction | None:
        """Convert a single Plaid transaction to a beancount Transaction."""
        # Parse date.
        date_str = txn.get("date") or txn.get("authorized_date")
        if not date_str:
            return None
        try:
            txn_date = datetime.date.fromisoformat(str(date_str))
        except ValueError:
            return None

        # Parse amount (Plaid uses positive = money leaving the account).
        raw_amount = txn.get("amount")
        if raw_amount is None:
            return None
        try:
            amount_num = D(str(raw_amount))
            # Plaid convention: positive = debit/outflow, negate for beancount.
            amount_num = -amount_num
        except Exception:
            return None

        # Currency.
        currency = (
            txn.get("iso_currency_code")
            or txn.get("unofficial_currency_code")
            or self.default_currency
        )

        # Determine the beancount account.
        plaid_account_id = txn.get("account_id", "")
        if plaid_account_id in self.account_map:
            account = self.account_map[plaid_account_id]
        else:
            # Fall back to default, using Plaid account name as hint.
            account = self.default_account

        # Payee and narration.
        payee = txn.get("merchant_name") or txn.get("name")
        narration = txn.get("name") or txn.get("original_description") or "Plaid Transaction"

        # Build metadata with Plaid-specific fields.
        meta = data.new_metadata(source, idx)
        if txn.get("transaction_id"):
            meta["plaid_id"] = txn["transaction_id"]
        if txn.get("category"):
            categories = txn["category"]
            if isinstance(categories, list):
                meta["plaid_category"] = " > ".join(categories)
            else:
                meta["plaid_category"] = str(categories)
        if txn.get("pending"):
            meta["plaid_pending"] = True

        flag = "!" if txn.get("pending") else "*"

        return data.Transaction(
            meta=meta,
            date=txn_date,
            flag=flag,
            payee=payee,
            narration=narration,
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[
                data.Posting(
                    account=account,
                    units=Amount(amount_num, currency),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                ),
            ],
        )

    def _apply_config(self, config: dict[str, Any]) -> None:
        """Apply Plaid-specific configuration."""
        super()._apply_config(config)
        if "client_id" in config:
            self.client_id = config["client_id"]
        if "secret" in config:
            self.secret = config["secret"]
        if "access_token" in config:
            self.access_token = config["access_token"]
        if "environment" in config:
            self.environment = config["environment"]
        if "account_map" in config:
            self.account_map = config["account_map"]
        if "days_back" in config:
            self.days_back = int(config["days_back"])
