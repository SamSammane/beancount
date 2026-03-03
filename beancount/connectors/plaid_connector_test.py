"""Tests for the Plaid connector."""

import json
import os
import tempfile
import unittest
from decimal import Decimal

from beancount.connectors.plaid_connector import PlaidConnector


class TestPlaidConnector(unittest.TestCase):
    def _write_json(self, data):
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(data, f)
        f.close()
        return f.name

    def _make_plaid_response(self):
        """Create a sample Plaid API response."""
        return {
            "accounts": [
                {
                    "account_id": "acct_001",
                    "name": "Checking",
                    "official_name": "CHECKING ACCOUNT",
                    "type": "depository",
                    "subtype": "checking",
                },
                {
                    "account_id": "acct_002",
                    "name": "Credit Card",
                    "type": "credit",
                    "subtype": "credit card",
                },
            ],
            "transactions": [
                {
                    "transaction_id": "txn_001",
                    "account_id": "acct_001",
                    "date": "2024-01-15",
                    "amount": 45.00,
                    "merchant_name": "Grocery Store",
                    "name": "GROCERY STORE #123",
                    "category": ["Food and Drink", "Groceries"],
                    "iso_currency_code": "USD",
                    "pending": False,
                },
                {
                    "transaction_id": "txn_002",
                    "account_id": "acct_001",
                    "date": "2024-01-16",
                    "amount": -5000.00,
                    "merchant_name": None,
                    "name": "EMPLOYER INC DIRECT DEP",
                    "category": ["Transfer", "Payroll"],
                    "iso_currency_code": "USD",
                    "pending": False,
                },
                {
                    "transaction_id": "txn_003",
                    "account_id": "acct_002",
                    "date": "2024-01-17",
                    "amount": 120.50,
                    "merchant_name": "Electronics Shop",
                    "name": "ELECTRONICS SHOP",
                    "category": ["Shops", "Electronics"],
                    "iso_currency_code": "USD",
                    "pending": True,
                },
            ],
            "total_transactions": 3,
        }

    def test_identify_plaid_json(self):
        data = self._make_plaid_response()
        tmpfile = self._write_json(data)
        try:
            conn = PlaidConnector()
            self.assertTrue(conn.identify(tmpfile))
        finally:
            os.unlink(tmpfile)

    def test_identify_non_plaid_json(self):
        data = {"transactions": [{"date": "2024-01-01", "amount": 10}]}
        tmpfile = self._write_json(data)
        try:
            conn = PlaidConnector()
            # Missing "accounts" key, so not identified as Plaid.
            self.assertFalse(conn.identify(tmpfile))
        finally:
            os.unlink(tmpfile)

    def test_identify_non_json(self):
        conn = PlaidConnector()
        self.assertFalse(conn.identify("test.csv"))

    def test_extract_from_file(self):
        data = self._make_plaid_response()
        tmpfile = self._write_json(data)
        try:
            conn = PlaidConnector()
            conn.default_account = "Assets:Checking"
            entries = conn.extract(tmpfile)

            self.assertEqual(len(entries), 3)
        finally:
            os.unlink(tmpfile)

    def test_transaction_amounts_negated(self):
        """Plaid amounts are negated: positive in Plaid = outflow."""
        data = self._make_plaid_response()
        tmpfile = self._write_json(data)
        try:
            conn = PlaidConnector()
            conn.default_account = "Assets:Checking"
            entries = conn.extract(tmpfile)

            # Find the grocery transaction (amount 45.00 in Plaid = -45 in beancount).
            grocery = [e for e in entries if e.payee == "Grocery Store"][0]
            self.assertEqual(grocery.postings[0].units.number, Decimal("-45"))

            # Find the salary (amount -5000 in Plaid = 5000 in beancount).
            salary = [e for e in entries if "EMPLOYER" in e.narration][0]
            self.assertEqual(salary.postings[0].units.number, Decimal("5000"))
        finally:
            os.unlink(tmpfile)

    def test_account_mapping(self):
        data = self._make_plaid_response()
        tmpfile = self._write_json(data)
        try:
            conn = PlaidConnector()
            conn.default_account = "Assets:Unknown"
            conn.account_map = {
                "acct_001": "Assets:Bank:Checking",
                "acct_002": "Liabilities:CreditCard",
            }
            entries = conn.extract(tmpfile)

            checking_entries = [
                e for e in entries
                if e.postings[0].account == "Assets:Bank:Checking"
            ]
            cc_entries = [
                e for e in entries
                if e.postings[0].account == "Liabilities:CreditCard"
            ]

            self.assertEqual(len(checking_entries), 2)
            self.assertEqual(len(cc_entries), 1)
        finally:
            os.unlink(tmpfile)

    def test_pending_transactions(self):
        data = self._make_plaid_response()
        tmpfile = self._write_json(data)
        try:
            conn = PlaidConnector()
            conn.default_account = "Assets:Checking"
            entries = conn.extract(tmpfile)

            # Pending transaction should have "!" flag.
            pending = [e for e in entries if e.payee == "Electronics Shop"][0]
            self.assertEqual(pending.flag, "!")
            self.assertTrue(pending.meta.get("plaid_pending"))

            # Non-pending should have "*" flag.
            cleared = [e for e in entries if e.payee == "Grocery Store"][0]
            self.assertEqual(cleared.flag, "*")
        finally:
            os.unlink(tmpfile)

    def test_metadata_fields(self):
        data = self._make_plaid_response()
        tmpfile = self._write_json(data)
        try:
            conn = PlaidConnector()
            conn.default_account = "Assets:Checking"
            entries = conn.extract(tmpfile)

            grocery = [e for e in entries if e.payee == "Grocery Store"][0]
            self.assertEqual(grocery.meta.get("plaid_id"), "txn_001")
            self.assertEqual(grocery.meta.get("plaid_category"), "Food and Drink > Groceries")
        finally:
            os.unlink(tmpfile)

    def test_currency_from_response(self):
        data = self._make_plaid_response()
        # Change one transaction's currency.
        data["transactions"][0]["iso_currency_code"] = "EUR"
        tmpfile = self._write_json(data)
        try:
            conn = PlaidConnector()
            conn.default_account = "Assets:Checking"
            entries = conn.extract(tmpfile)

            grocery = [e for e in entries if e.payee == "Grocery Store"][0]
            self.assertEqual(grocery.postings[0].units.currency, "EUR")
        finally:
            os.unlink(tmpfile)

    def test_empty_response(self):
        data = {"accounts": [], "transactions": []}
        tmpfile = self._write_json(data)
        try:
            conn = PlaidConnector()
            entries = conn.extract(tmpfile)
            self.assertEqual(entries, [])
        finally:
            os.unlink(tmpfile)

    def test_api_mode_requires_credentials(self):
        conn = PlaidConnector()
        with self.assertRaises(ImportError):
            # plaid-python is not installed, so this should raise ImportError.
            conn.fetch_transactions()

    def test_config(self):
        conn = PlaidConnector()
        conn._apply_config({
            "default_account": "Assets:Bank",
            "client_id": "test_client",
            "secret": "test_secret",
            "access_token": "test_token",
            "environment": "development",
            "account_map": {"acct_1": "Assets:Checking"},
            "days_back": 60,
        })
        self.assertEqual(conn.default_account, "Assets:Bank")
        self.assertEqual(conn.client_id, "test_client")
        self.assertEqual(conn.secret, "test_secret")
        self.assertEqual(conn.access_token, "test_token")
        self.assertEqual(conn.environment, "development")
        self.assertEqual(conn.account_map, {"acct_1": "Assets:Checking"})
        self.assertEqual(conn.days_back, 60)


    def test_file_size_limit(self):
        """Files exceeding the size limit should raise ValueError."""
        data = self._make_plaid_response()
        tmpfile = self._write_json(data)
        try:
            conn = PlaidConnector()
            conn.max_file_size = 1  # 1 byte limit.
            with self.assertRaises(ValueError) as ctx:
                conn.extract(tmpfile)
            self.assertIn("File too large", str(ctx.exception))
        finally:
            os.unlink(tmpfile)

    def test_transaction_missing_date(self):
        """Transactions without a date should be skipped."""
        data = {
            "accounts": [],
            "transactions": [
                {"transaction_id": "txn_bad", "amount": 10.00, "name": "No Date"},
            ],
        }
        tmpfile = self._write_json(data)
        try:
            conn = PlaidConnector()
            entries = conn.extract(tmpfile)
            self.assertEqual(entries, [])
        finally:
            os.unlink(tmpfile)

    def test_transaction_invalid_amount(self):
        """Transactions with invalid amounts should be skipped."""
        data = {
            "accounts": [],
            "transactions": [
                {"date": "2024-01-01", "amount": "not_a_number", "name": "Bad amount"},
            ],
        }
        tmpfile = self._write_json(data)
        try:
            conn = PlaidConnector()
            entries = conn.extract(tmpfile)
            self.assertEqual(entries, [])
        finally:
            os.unlink(tmpfile)

    def test_transaction_null_amount(self):
        """Transactions with null amounts should be skipped."""
        data = {
            "accounts": [],
            "transactions": [
                {"date": "2024-01-01", "amount": None, "name": "Null amount"},
            ],
        }
        tmpfile = self._write_json(data)
        try:
            conn = PlaidConnector()
            entries = conn.extract(tmpfile)
            self.assertEqual(entries, [])
        finally:
            os.unlink(tmpfile)

    def test_category_string_not_list(self):
        """Category as a string instead of list should be handled."""
        data = {
            "accounts": [],
            "transactions": [
                {
                    "date": "2024-01-01",
                    "amount": 10.00,
                    "name": "Test",
                    "category": "Food",
                },
            ],
        }
        tmpfile = self._write_json(data)
        try:
            conn = PlaidConnector()
            conn.default_account = "Assets:Checking"
            entries = conn.extract(tmpfile)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].meta.get("plaid_category"), "Food")
        finally:
            os.unlink(tmpfile)


if __name__ == "__main__":
    unittest.main()
