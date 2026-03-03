"""Financial data connectors for Beancount.

This module provides a framework for importing financial data from
external sources into Beancount format:

- CSV files (bank statements, credit card exports)
- OFX/QFX files (Open Financial Exchange)
- API-based connectors (extensible for bank APIs)
- Generic base classes for building custom connectors

Each connector follows a common interface: identify, extract, and
optionally file documents.
"""

__copyright__ = "Copyright (C) 2026  Beancount Contributors"
__license__ = "GNU GPLv2"

from beancount.connectors.base import BaseConnector
from beancount.connectors.csv_connector import CSVConnector
from beancount.connectors.ofx_connector import OFXConnector
from beancount.connectors.registry import ConnectorRegistry

__all__ = [
    "BaseConnector",
    "CSVConnector",
    "OFXConnector",
    "ConnectorRegistry",
]
