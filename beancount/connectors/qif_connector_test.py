"""Tests for the QIF connector."""

import os
import tempfile
import textwrap
import unittest
from decimal import Decimal

from beancount.connectors.qif_connector import QIFConnector


class TestQIFConnector(unittest.TestCase):
    def _write_tmp(self, content, suffix=".qif"):
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=suffix, delete=False, encoding="utf-8"
        )
        f.write(content)
        f.close()
        return f.name

    def test_identify_by_extension(self):
        conn = QIFConnector()
        self.assertTrue(conn.identify("test.qif"))
        self.assertFalse(conn.identify("test.csv"))

    def test_identify_by_content(self):
        tmpfile = self._write_tmp("!Type:Bank\n", suffix=".txt")
        try:
            conn = QIFConnector()
            self.assertTrue(conn.identify(tmpfile))
        finally:
            os.unlink(tmpfile)

    def test_extract_basic_transactions(self):
        content = textwrap.dedent("""\
            !Type:Bank
            D01/15/2024
            T-45.00
            PGrocery Store
            MGroceries for the week
            LFood:Groceries
            ^
            D01/16/2024
            T5000.00
            PEmployer Inc
            MSalary deposit
            LIncome:Salary
            C*
            ^
        """)
        tmpfile = self._write_tmp(content)
        try:
            conn = QIFConnector()
            conn.default_account = "Assets:Checking"
            entries = conn.extract(tmpfile)

            self.assertEqual(len(entries), 2)

            # First transaction (sorted by date).
            self.assertEqual(entries[0].date.isoformat(), "2024-01-15")
            self.assertEqual(entries[0].payee, "Grocery Store")
            self.assertEqual(entries[0].flag, "!")
            self.assertEqual(len(entries[0].postings), 2)
            self.assertEqual(entries[0].postings[0].units.number, Decimal("-45.00"))
            self.assertEqual(entries[0].postings[0].account, "Assets:Checking")
            self.assertEqual(entries[0].postings[1].account, "Expenses:Food:Groceries")

            # Second transaction (cleared).
            self.assertEqual(entries[1].date.isoformat(), "2024-01-16")
            self.assertEqual(entries[1].flag, "*")
            self.assertEqual(entries[1].postings[0].units.number, Decimal("5000.00"))
        finally:
            os.unlink(tmpfile)

    def test_extract_split_transaction(self):
        content = textwrap.dedent("""\
            !Type:Bank
            D02/01/2024
            T-150.00
            PSupermart
            MShopping trip
            SFood:Groceries
            EGroceries
            $-100.00
            SHousehold
            ECleaning supplies
            $-50.00
            ^
        """)
        tmpfile = self._write_tmp(content)
        try:
            conn = QIFConnector()
            conn.default_account = "Assets:Checking"
            entries = conn.extract(tmpfile)

            self.assertEqual(len(entries), 1)
            # Main posting + 2 split postings.
            self.assertEqual(len(entries[0].postings), 3)
            self.assertEqual(entries[0].postings[0].units.number, Decimal("-150.00"))
            self.assertEqual(entries[0].postings[1].account, "Expenses:Food:Groceries")
            self.assertEqual(entries[0].postings[1].units.number, Decimal("100.00"))
            self.assertEqual(entries[0].postings[2].account, "Expenses:Household")
            self.assertEqual(entries[0].postings[2].units.number, Decimal("50.00"))
        finally:
            os.unlink(tmpfile)

    def test_category_to_account_transfer(self):
        conn = QIFConnector()
        account = conn._category_to_account("[Savings]")
        self.assertEqual(account, "Assets:Savings")

    def test_category_to_account_regular(self):
        conn = QIFConnector()
        account = conn._category_to_account("Food:Groceries")
        self.assertEqual(account, "Expenses:Food:Groceries")

    def test_category_to_account_empty(self):
        conn = QIFConnector()
        account = conn._category_to_account("")
        self.assertEqual(account, "Expenses:Uncategorized")

    def test_eu_date_format(self):
        content = textwrap.dedent("""\
            !Type:Bank
            D15/01/2024
            T-10.00
            PTest
            ^
        """)
        tmpfile = self._write_tmp(content)
        try:
            conn = QIFConnector()
            conn.date_format = "eu"
            conn.default_account = "Assets:Checking"
            entries = conn.extract(tmpfile)

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].date.isoformat(), "2024-01-15")
        finally:
            os.unlink(tmpfile)

    def test_two_digit_year(self):
        conn = QIFConnector()
        date = conn._parse_date("1/15/24")
        self.assertIsNotNone(date)
        self.assertEqual(date.year, 2024)

    def test_check_number_in_metadata(self):
        content = textwrap.dedent("""\
            !Type:Bank
            D01/20/2024
            T-250.00
            N1042
            PRent Payment
            ^
        """)
        tmpfile = self._write_tmp(content)
        try:
            conn = QIFConnector()
            conn.default_account = "Assets:Checking"
            entries = conn.extract(tmpfile)

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].meta.get("check_number"), "1042")
        finally:
            os.unlink(tmpfile)

    def test_empty_file(self):
        tmpfile = self._write_tmp("")
        try:
            conn = QIFConnector()
            entries = conn.extract(tmpfile)
            self.assertEqual(entries, [])
        finally:
            os.unlink(tmpfile)

    def test_credit_card_type(self):
        content = textwrap.dedent("""\
            !Type:CCard
            D01/10/2024
            T-25.00
            PCoffee Shop
            ^
        """)
        tmpfile = self._write_tmp(content)
        try:
            conn = QIFConnector()
            conn.default_account = "Liabilities:CreditCard"
            entries = conn.extract(tmpfile)

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].postings[0].account, "Liabilities:CreditCard")
        finally:
            os.unlink(tmpfile)

    def test_config(self):
        conn = QIFConnector()
        conn._apply_config({
            "default_account": "Assets:MyBank",
            "default_currency": "EUR",
            "date_format": "eu",
            "category_prefix": "Ausgaben",
        })
        self.assertEqual(conn.default_account, "Assets:MyBank")
        self.assertEqual(conn.default_currency, "EUR")
        self.assertEqual(conn.date_format, "eu")
        self.assertEqual(conn.category_prefix, "Ausgaben")


if __name__ == "__main__":
    unittest.main()
