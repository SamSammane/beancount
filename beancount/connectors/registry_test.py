"""Tests for the connector registry."""

import os
import tempfile
import unittest

from beancount.connectors.csv_connector import CSVConnector
from beancount.connectors.ofx_connector import OFXConnector
from beancount.connectors.registry import ConnectorRegistry
from beancount.connectors.registry import create_default_registry


class TestConnectorRegistry(unittest.TestCase):
    def test_register_and_identify(self):
        registry = ConnectorRegistry()
        csv_conn = CSVConnector()
        registry.register(csv_conn)

        # Should identify CSV files.
        result = registry.identify("test.csv")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, CSVConnector)

        # Should not identify OFX files.
        result = registry.identify("test.ofx")
        self.assertIsNone(result)

    def test_list_connectors(self):
        registry = ConnectorRegistry()
        registry.register(CSVConnector())
        registry.register(OFXConnector())

        names = registry.list_connectors()
        self.assertIn("CSVConnector", names)
        self.assertIn("OFXConnector", names)

    def test_extract_no_connector(self):
        registry = ConnectorRegistry()
        with self.assertRaises(ValueError):
            registry.extract("unknown.xyz")

    def test_create_default_registry(self):
        registry = create_default_registry(
            default_account="Assets:Checking",
            default_currency="EUR",
        )
        names = registry.list_connectors()
        self.assertIn("CSVConnector", names)
        self.assertIn("OFXConnector", names)

    def test_extract_csv_through_registry(self):
        content = "Date,Description,Amount\n2024-01-15,Test,-10.00\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            tmpfile = f.name

        try:
            registry = create_default_registry()
            entries = registry.extract(tmpfile)
            self.assertEqual(len(entries), 1)
        finally:
            os.unlink(tmpfile)


if __name__ == "__main__":
    unittest.main()
