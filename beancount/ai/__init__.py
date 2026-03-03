"""AI-powered assistant for Beancount ledger analysis and automation.

This module provides:
- Transaction categorization using LLM providers
- Natural language querying of ledger data
- Anomaly detection for unusual transactions
- Smart transaction entry suggestions

Supports multiple LLM backends (OpenAI, Anthropic, Ollama) via a
provider-agnostic interface.
"""

__copyright__ = "Copyright (C) 2026  Beancount Contributors"
__license__ = "GNU GPLv2"

from beancount.ai.categorizer import Categorizer
from beancount.ai.detector import AnomalyDetector
from beancount.ai.nlquery import NaturalLanguageQuery
from beancount.ai.provider import get_provider

__all__ = [
    "Categorizer",
    "AnomalyDetector",
    "NaturalLanguageQuery",
    "get_provider",
]
