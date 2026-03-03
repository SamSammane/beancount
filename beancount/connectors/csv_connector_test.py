"""Tests for the CSV connector."""

import datetime
import os
import tempfile
import textwrap
import unittest
from decimal import Decimal

from beancount.connectors.csv_connector import CSVConnector
from beancount.core import data
from beancount.core.number import D


class TestCSVConnector(unittest.TestCase):
    def test_identify_csv(self):
        conn = CSVConnector()
        self.assertTrue(conn.identify("test.csv"))
        self.assertTrue(conn.identify("test.tsv"))
        self.assertTrue(conn.identify("test.txt"))
        self.assertFalse(conn.identify("test.ofx"))
        self.assertFalse(conn.identify("test.py"))

    def test_extract_basic_csv(self):
        content = textwrap.dedent("""\
            Date,Description,Amount
            2024-01-15,Coffee Shop,-4.50
            2024-01-16,Grocery Store,-85.23
            2024-01-17,Salary,5000.00
        """)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            tmpfile = f.name

        try:
            conn = CSVConnector()
            conn.default_account = "Assets:Checking"
            entries = conn.extract(tmpfile)

            self.assertEqual(len(entries), 3)
            # Entries should be sorted by date.
            self.assertEqual(entries[0].date, datetime.date(2024, 1, 15))
            self.assertEqual(entries[0].narration, "Coffee Shop")
        finally:
            os.unlink(tmpfile)

    def test_extract_with_column_config(self):
        content = textwrap.dedent("""\
            Trans Date,Payee Name,Memo,Debit
            01/15/2024,Amazon,Book purchase,-29.99
            01/16/2024,Walmart,Groceries,-55.12
        """)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            tmpfile = f.name

        try:
            conn = CSVConnector()
            conn.date_column = "Trans Date"
            conn.amount_column = "Debit"
            conn.payee_column = "Payee Name"
            conn.narration_column = "Memo"
            conn.date_format = "%m/%d/%Y"
            conn.default_account = "Liabilities:CreditCard"

            entries = conn.extract(tmpfile)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].payee, "Amazon")
            self.assertEqual(entries[0].narration, "Book purchase")
            posting = entries[0].postings[0]
            self.assertEqual(posting.account, "Liabilities:CreditCard")
            self.assertEqual(posting.units.number, D("-29.99"))
        finally:
            os.unlink(tmpfile)

    def test_extract_inverted_amounts(self):
        content = textwrap.dedent("""\
            Date,Description,Amount
            2024-01-15,Payment,100.00
        """)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            tmpfile = f.name

        try:
            conn = CSVConnector()
            conn.invert_amounts = True
            entries = conn.extract(tmpfile)

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].postings[0].units.number, D("-100.00"))
        finally:
            os.unlink(tmpfile)

    def test_parse_amount_with_currency_symbol(self):
        conn = CSVConnector()
        self.assertEqual(conn._parse_amount("$1,234.56"), D("1234.56"))
        self.assertEqual(conn._parse_amount("€99.00"), D("99.00"))
        self.assertEqual(conn._parse_amount("(50.00)"), D("-50.00"))
        self.assertIsNone(conn._parse_amount(""))

    def test_parse_date_various_formats(self):
        conn = CSVConnector()
        self.assertEqual(
            conn._parse_date("2024-01-15"), datetime.date(2024, 1, 15)
        )
        self.assertEqual(
            conn._parse_date("01/15/2024"), datetime.date(2024, 1, 15)
        )
        self.assertIsNone(conn._parse_date("not-a-date"))

    def test_extract_empty_csv(self):
        content = "Date,Description,Amount\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            tmpfile = f.name

        try:
            conn = CSVConnector()
            entries = conn.extract(tmpfile)
            self.assertEqual(entries, [])
        finally:
            os.unlink(tmpfile)

    def test_apply_config(self):
        conn = CSVConnector()
        config = {
            "default_account": "Assets:Bank",
            "default_currency": "EUR",
            "date_column": "Trans Date",
            "amount_column": "Debit",
            "invert_amounts": True,
            "skip_lines": 2,
        }
        conn._apply_config(config)
        self.assertEqual(conn.default_account, "Assets:Bank")
        self.assertEqual(conn.default_currency, "EUR")
        self.assertEqual(conn.date_column, "Trans Date")
        self.assertTrue(conn.invert_amounts)
        self.assertEqual(conn.skip_lines, 2)


if __name__ == "__main__":
    unittest.main()
