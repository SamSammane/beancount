"""Connector registry for managing and discovering available connectors."""

from __future__ import annotations

__copyright__ = "Copyright (C) 2026  Beancount Contributors"
__license__ = "GNU GPLv2"

from typing import Any

from beancount.connectors.base import BaseConnector
from beancount.core import data


class ConnectorRegistry:
    """Registry for managing financial data connectors.

    Provides auto-detection of file types and routing to the
    appropriate connector.
    """

    def __init__(self):
        self._connectors: list[BaseConnector] = []

    def register(self, connector: BaseConnector) -> None:
        """Register a connector instance.

        Args:
          connector: A BaseConnector instance.
        """
        self._connectors.append(connector)

    def identify(self, filepath: str) -> BaseConnector | None:
        """Find a connector that can handle the given file.

        Args:
          filepath: Path to the input file.
        Returns:
          The first matching connector, or None.
        """
        for connector in self._connectors:
            if connector.identify(filepath):
                return connector
        return None

    def extract(self, filepath: str) -> data.Directives:
        """Extract directives from a file using the appropriate connector.

        Args:
          filepath: Path to the input file.
        Returns:
          A list of directives.
        Raises:
          ValueError: If no connector can handle the file.
        """
        connector = self.identify(filepath)
        if connector is None:
            raise ValueError(
                f"No connector found for file: {filepath}. "
                f"Registered connectors: {len(self._connectors)}"
            )
        return connector.extract(filepath)

    def list_connectors(self) -> list[str]:
        """List registered connector class names.

        Returns:
          A list of connector class name strings.
        """
        return [type(c).__name__ for c in self._connectors]


def create_default_registry(**kwargs: Any) -> ConnectorRegistry:
    """Create a registry with the default set of connectors.

    Args:
      **kwargs: Configuration passed to connectors.
    Returns:
      A ConnectorRegistry with CSV and OFX connectors registered.
    """
    from beancount.connectors.csv_connector import CSVConnector
    from beancount.connectors.ofx_connector import OFXConnector

    registry = ConnectorRegistry()

    csv_conn = CSVConnector()
    ofx_conn = OFXConnector()

    if "default_account" in kwargs:
        csv_conn.default_account = kwargs["default_account"]
        ofx_conn.default_account = kwargs["default_account"]
    if "default_currency" in kwargs:
        csv_conn.default_currency = kwargs["default_currency"]
        ofx_conn.default_currency = kwargs["default_currency"]

    registry.register(csv_conn)
    registry.register(ofx_conn)

    return registry
