"""Tests for the JSON connector."""

import json
import os
import tempfile
import unittest
from decimal import Decimal

from beancount.connectors.json_connector import JSONConnector


class TestJSONConnector(unittest.TestCase):
    def _write_json(self, data, suffix=".json"):
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=suffix, delete=False, encoding="utf-8"
        )
        json.dump(data, f)
        f.close()
        return f.name

    def test_identify_by_extension(self):
        conn = JSONConnector()
        self.assertTrue(conn.identify("test.json"))
        self.assertFalse(conn.identify("test.csv"))

    def test_identify_by_content(self):
        tmpfile = self._write_json({"transactions": []}, suffix=".txt")
        try:
            conn = JSONConnector()
            self.assertTrue(conn.identify(tmpfile))
        finally:
            os.unlink(tmpfile)

    def test_extract_top_level_array(self):
        data = [
            {"date": "2024-01-15", "amount": -45.00, "description": "Grocery Store"},
            {"date": "2024-01-16", "amount": 5000.00, "description": "Salary"},
        ]
        tmpfile = self._write_json(data)
        try:
            conn = JSONConnector()
            conn.default_account = "Assets:Checking"
            entries = conn.extract(tmpfile)

            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].date.isoformat(), "2024-01-15")
            self.assertEqual(entries[0].postings[0].units.number, Decimal("-45"))
            self.assertEqual(entries[0].narration, "Grocery Store")
        finally:
            os.unlink(tmpfile)

    def test_extract_nested_transactions(self):
        data = {
            "status": "ok",
            "transactions": [
                {"date": "2024-03-01", "amount": -100.00, "merchant": "Amazon"},
                {"date": "2024-03-02", "amount": -20.50, "merchant": "Cafe"},
            ],
        }
        tmpfile = self._write_json(data)
        try:
            conn = JSONConnector()
            conn.default_account = "Assets:Checking"
            entries = conn.extract(tmpfile)

            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].payee, "Amazon")
            self.assertEqual(entries[1].payee, "Cafe")
        finally:
            os.unlink(tmpfile)

    def test_extract_deep_nested_key(self):
        data = {
            "response": {
                "data": {
                    "items": [
                        {"date": "2024-05-01", "amount": -10.00, "description": "Test"},
                    ]
                }
            }
        }
        tmpfile = self._write_json(data)
        try:
            conn = JSONConnector()
            conn.transactions_key = "response.data.items"
            conn.default_account = "Assets:Checking"
            entries = conn.extract(tmpfile)

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].narration, "Test")
        finally:
            os.unlink(tmpfile)

    def test_auto_detect_field_names(self):
        data = [
            {
                "transactionDate": "2024-06-15",
                "transactionAmount": -99.99,
                "merchantName": "Big Store",
                "memo": "Online purchase",
                "currencyCode": "EUR",
                "transactionId": "TX123",
            }
        ]
        tmpfile = self._write_json(data)
        try:
            conn = JSONConnector()
            conn.default_account = "Assets:Checking"
            entries = conn.extract(tmpfile)

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].date.isoformat(), "2024-06-15")
            self.assertEqual(entries[0].postings[0].units.number, Decimal("-99.99"))
            self.assertEqual(entries[0].payee, "Big Store")
            self.assertEqual(entries[0].narration, "Online purchase")
            self.assertEqual(entries[0].postings[0].units.currency, "EUR")
            self.assertEqual(entries[0].meta.get("json_id"), "TX123")
        finally:
            os.unlink(tmpfile)

    def test_custom_field_mapping(self):
        data = [
            {"dt": "2024-07-01", "val": -30.00, "who": "Pizza Place", "what": "Lunch"},
        ]
        tmpfile = self._write_json(data)
        try:
            conn = JSONConnector()
            conn.date_field = "dt"
            conn.amount_field = "val"
            conn.payee_field = "who"
            conn.narration_field = "what"
            conn.default_account = "Assets:Checking"
            entries = conn.extract(tmpfile)

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].payee, "Pizza Place")
            self.assertEqual(entries[0].narration, "Lunch")
        finally:
            os.unlink(tmpfile)

    def test_negate_amounts(self):
        data = [{"date": "2024-01-01", "amount": 50.00, "description": "Test"}]
        tmpfile = self._write_json(data)
        try:
            conn = JSONConnector()
            conn.negate_amounts = True
            conn.default_account = "Assets:Checking"
            entries = conn.extract(tmpfile)

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].postings[0].units.number, Decimal("-50"))
        finally:
            os.unlink(tmpfile)

    def test_iso_datetime_parsing(self):
        data = [{"date": "2024-01-15T10:30:00Z", "amount": -10.00, "description": "Test"}]
        tmpfile = self._write_json(data)
        try:
            conn = JSONConnector()
            conn.default_account = "Assets:Checking"
            entries = conn.extract(tmpfile)

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].date.isoformat(), "2024-01-15")
        finally:
            os.unlink(tmpfile)

    def test_string_amounts(self):
        data = [{"date": "2024-01-01", "amount": "$1,234.56", "description": "Big purchase"}]
        tmpfile = self._write_json(data)
        try:
            conn = JSONConnector()
            conn.default_account = "Assets:Checking"
            entries = conn.extract(tmpfile)

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].postings[0].units.number, Decimal("1234.56"))
        finally:
            os.unlink(tmpfile)

    def test_empty_json_array(self):
        tmpfile = self._write_json([])
        try:
            conn = JSONConnector()
            entries = conn.extract(tmpfile)
            self.assertEqual(entries, [])
        finally:
            os.unlink(tmpfile)

    def test_invalid_json_file(self):
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        f.write("not valid json {{{")
        f.close()
        try:
            conn = JSONConnector()
            entries = conn.extract(f.name)
            self.assertEqual(entries, [])
        finally:
            os.unlink(f.name)

    def test_config(self):
        conn = JSONConnector()
        conn._apply_config({
            "default_account": "Assets:MyBank",
            "transactions_key": "data.txns",
            "date_field": "posted",
            "amount_field": "value",
            "negate_amounts": True,
        })
        self.assertEqual(conn.default_account, "Assets:MyBank")
        self.assertEqual(conn.transactions_key, "data.txns")
        self.assertEqual(conn.date_field, "posted")
        self.assertEqual(conn.amount_field, "value")
        self.assertTrue(conn.negate_amounts)


    def test_file_size_limit(self):
        """Files exceeding the size limit should raise ValueError."""
        data = [{"date": "2024-01-01", "amount": 10, "description": "Test"}]
        tmpfile = self._write_json(data)
        try:
            conn = JSONConnector()
            conn.max_file_size = 1  # 1 byte limit.
            with self.assertRaises(ValueError) as ctx:
                conn.extract(tmpfile)
            self.assertIn("File too large", str(ctx.exception))
        finally:
            os.unlink(tmpfile)

    def test_mixed_list_values(self):
        """Auto-detect should handle dicts with list values containing mixed types."""
        data = {
            "metadata": "some info",
            "items": [{"date": "2024-01-01", "amount": 10, "description": "Test"}, "not a dict", 42],
        }
        tmpfile = self._write_json(data)
        try:
            conn = JSONConnector()
            conn.default_account = "Assets:Checking"
            entries = conn.extract(tmpfile)
            self.assertEqual(len(entries), 1)
        finally:
            os.unlink(tmpfile)

    def test_record_missing_date(self):
        """Records without a date field should be skipped."""
        data = [{"amount": 10, "description": "No date"}]
        tmpfile = self._write_json(data)
        try:
            conn = JSONConnector()
            entries = conn.extract(tmpfile)
            self.assertEqual(entries, [])
        finally:
            os.unlink(tmpfile)

    def test_record_missing_amount(self):
        """Records without an amount field should be skipped."""
        data = [{"date": "2024-01-01", "description": "No amount"}]
        tmpfile = self._write_json(data)
        try:
            conn = JSONConnector()
            entries = conn.extract(tmpfile)
            self.assertEqual(entries, [])
        finally:
            os.unlink(tmpfile)

    def test_invalid_date_string(self):
        """Records with unparseable dates should be skipped."""
        data = [{"date": "not-a-date", "amount": 10, "description": "Bad date"}]
        tmpfile = self._write_json(data)
        try:
            conn = JSONConnector()
            entries = conn.extract(tmpfile)
            self.assertEqual(entries, [])
        finally:
            os.unlink(tmpfile)

    def test_invalid_amount_string(self):
        """Records with unparseable amounts should be skipped."""
        data = [{"date": "2024-01-01", "amount": "not-a-number", "description": "Bad amount"}]
        tmpfile = self._write_json(data)
        try:
            conn = JSONConnector()
            entries = conn.extract(tmpfile)
            self.assertEqual(entries, [])
        finally:
            os.unlink(tmpfile)


if __name__ == "__main__":
    unittest.main()
