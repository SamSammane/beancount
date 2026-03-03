"""Tests for the BaseConnector abstract class."""

import json
import os
import tempfile
import unittest

from beancount.connectors.base import BaseConnector
from beancount.core import data


class ConcreteConnector(BaseConnector):
    """Minimal concrete implementation for testing."""

    def identify(self, filepath):
        return filepath.endswith(".test")

    def extract(self, filepath):
        return []


class TestBaseConnector(unittest.TestCase):
    def test_default_attributes(self):
        conn = ConcreteConnector()
        self.assertEqual(conn.default_account, "Assets:Unknown")
        self.assertEqual(conn.default_currency, "USD")

    def test_file_account(self):
        conn = ConcreteConnector()
        conn.default_account = "Assets:Checking"
        self.assertEqual(conn.file_account("any.test"), "Assets:Checking")

    def test_file_date_returns_none(self):
        conn = ConcreteConnector()
        self.assertIsNone(conn.file_date("any.test"))

    def test_file_name_returns_none(self):
        conn = ConcreteConnector()
        self.assertIsNone(conn.file_name("any.test"))

    def test_load_config(self):
        config = {
            "default_account": "Assets:MyBank",
            "default_currency": "EUR",
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(config, f)
            tmpfile = f.name

        try:
            conn = ConcreteConnector()
            conn.load_config(tmpfile)
            self.assertEqual(conn.default_account, "Assets:MyBank")
            self.assertEqual(conn.default_currency, "EUR")
        finally:
            os.unlink(tmpfile)

    def test_load_config_missing_file(self):
        conn = ConcreteConnector()
        with self.assertRaises(FileNotFoundError):
            conn.load_config("/nonexistent/path/config.json")

    def test_load_config_invalid_json(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            f.write("not valid json {{{")
            tmpfile = f.name

        try:
            conn = ConcreteConnector()
            with self.assertRaises(json.JSONDecodeError):
                conn.load_config(tmpfile)
        finally:
            os.unlink(tmpfile)

    def test_apply_config_partial(self):
        conn = ConcreteConnector()
        conn._apply_config({"default_account": "Liabilities:CC"})
        self.assertEqual(conn.default_account, "Liabilities:CC")
        self.assertEqual(conn.default_currency, "USD")  # Unchanged.

    def test_apply_config_empty(self):
        conn = ConcreteConnector()
        conn._apply_config({})
        self.assertEqual(conn.default_account, "Assets:Unknown")
        self.assertEqual(conn.default_currency, "USD")

    def test_identify_interface(self):
        conn = ConcreteConnector()
        self.assertTrue(conn.identify("data.test"))
        self.assertFalse(conn.identify("data.csv"))

    def test_extract_interface(self):
        conn = ConcreteConnector()
        result = conn.extract("any.test")
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
