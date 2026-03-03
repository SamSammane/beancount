"""Base connector interface for financial data import.

All connectors must implement this interface to be compatible
with the beancount connector framework.
"""

from __future__ import annotations

__copyright__ = "Copyright (C) 2026  Beancount Contributors"
__license__ = "GNU GPLv2"

import datetime
import os
from abc import ABC
from abc import abstractmethod
from typing import Any

from beancount.core import data

# Default maximum file size for import (100 MB).
MAX_FILE_SIZE = 100 * 1024 * 1024


class BaseConnector(ABC):
    """Abstract base class for financial data connectors.

    Connectors transform external financial data (CSV, OFX, APIs)
    into beancount directives.
    """

    def __init__(self):
        self.default_account: str = "Assets:Unknown"
        self.default_currency: str = "USD"
        self.max_file_size: int = MAX_FILE_SIZE

    @abstractmethod
    def identify(self, filepath: str) -> bool:
        """Check if a file can be handled by this connector.

        Args:
          filepath: Path to the input file.
        Returns:
          True if this connector can process the file.
        """

    @abstractmethod
    def extract(self, filepath: str) -> data.Directives:
        """Extract beancount directives from an input file.

        Args:
          filepath: Path to the input file.
        Returns:
          A list of beancount directives.
        """

    def file_account(self, filepath: str) -> str | None:
        """Determine the filing account for the document.

        Args:
          filepath: Path to the input file.
        Returns:
          An account name string, or None.
        """
        return self.default_account

    def file_date(self, filepath: str) -> datetime.date | None:
        """Determine the filing date for the document.

        Args:
          filepath: Path to the input file.
        Returns:
          A date, or None.
        """
        return None

    def file_name(self, filepath: str) -> str | None:
        """Determine a clean filename for filing.

        Args:
          filepath: Path to the input file.
        Returns:
          A cleaned filename string, or None to use the original.
        """
        return None

    def _check_file_size(self, filepath: str) -> None:
        """Validate that a file is within the allowed size limit.

        Args:
          filepath: Path to the file to check.
        Raises:
          ValueError: If the file exceeds max_file_size.
        """
        try:
            size = os.path.getsize(filepath)
        except OSError:
            return  # Let the caller handle missing files.
        if size > self.max_file_size:
            raise ValueError(
                f"File too large ({size:,} bytes, limit {self.max_file_size:,}): {filepath}"
            )

    def load_config(self, config_path: str) -> None:
        """Load connector configuration from a JSON file.

        Args:
          config_path: Path to a JSON config file.
        Raises:
          FileNotFoundError: If the config file does not exist.
          json.JSONDecodeError: If the config file is not valid JSON.
        """
        import json

        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)

        self._apply_config(config)

    def _apply_config(self, config: dict[str, Any]) -> None:
        """Apply configuration dict to this connector.

        Override in subclasses for connector-specific settings.

        Args:
          config: Configuration dictionary.
        """
        if "default_account" in config:
            self.default_account = config["default_account"]
        if "default_currency" in config:
            self.default_currency = config["default_currency"]
