"""Anomaly detection for beancount ledgers.

Identifies unusual transactions using statistical analysis and optional
LLM-powered reasoning.
"""

from __future__ import annotations

__copyright__ = "Copyright (C) 2026  Beancount Contributors"
__license__ = "GNU GPLv2"

import statistics
from collections import defaultdict
from decimal import Decimal
from typing import TYPE_CHECKING
from typing import Any
from typing import NamedTuple

from beancount.core import data
from beancount.core.number import D

if TYPE_CHECKING:
    from beancount.ai.provider import LLMProvider


class Anomaly(NamedTuple):
    """Represents a detected anomaly in a transaction."""

    entry: data.Transaction
    score: float
    reason: str
    details: dict[str, Any]


class AnomalyDetector:
    """Detect unusual transactions in a beancount ledger.

    Uses statistical methods (z-score, frequency analysis) to identify
    outliers. Optionally uses an LLM to explain why a transaction looks
    unusual.
    """

    def __init__(
        self,
        provider: LLMProvider | None = None,
        z_threshold: float = 2.5,
    ):
        """Initialize the anomaly detector.

        Args:
          provider: Optional LLM provider for enhanced explanations.
          z_threshold: Z-score threshold for statistical outlier detection.
        """
        self.provider = provider
        self.z_threshold = z_threshold

    def detect(
        self,
        entries: data.Directives,
        max_results: int = 20,
    ) -> list[Anomaly]:
        """Detect anomalies in the given entries.

        Runs multiple detection strategies and returns a combined,
        deduplicated list of anomalies sorted by score.

        Args:
          entries: The ledger directives to analyze.
          max_results: Maximum number of anomalies to return.
        Returns:
          A list of Anomaly tuples sorted by score (highest first).
        """
        transactions = list(data.filter_txns(entries))
        if not transactions:
            return []

        anomalies: dict[int, Anomaly] = {}

        # Run detection strategies.
        for anomaly in self._detect_amount_outliers(transactions):
            key = id(anomaly.entry)
            if key not in anomalies or anomaly.score > anomalies[key].score:
                anomalies[key] = anomaly

        for anomaly in self._detect_unusual_accounts(transactions):
            key = id(anomaly.entry)
            if key not in anomalies or anomaly.score > anomalies[key].score:
                anomalies[key] = anomaly

        for anomaly in self._detect_duplicate_candidates(transactions):
            key = id(anomaly.entry)
            if key not in anomalies or anomaly.score > anomalies[key].score:
                anomalies[key] = anomaly

        # Sort by score and limit.
        result = sorted(anomalies.values(), key=lambda a: a.score, reverse=True)
        return result[:max_results]

    def _detect_amount_outliers(
        self, transactions: list[data.Transaction]
    ) -> list[Anomaly]:
        """Detect transactions with unusually large or small amounts."""
        # Group amounts by account pair.
        account_amounts: dict[str, list[Decimal]] = defaultdict(list)
        account_entries: dict[str, list[data.Transaction]] = defaultdict(list)

        for entry in transactions:
            for posting in entry.postings:
                if posting.units is not None and posting.units.number is not None:
                    key = posting.account
                    account_amounts[key].append(abs(posting.units.number))
                    account_entries[key].append(entry)

        anomalies = []
        for account, amounts in account_amounts.items():
            if len(amounts) < 5:
                continue

            float_amounts = [float(a) for a in amounts]
            mean = statistics.mean(float_amounts)
            if mean == 0:
                continue
            stdev = statistics.stdev(float_amounts) if len(float_amounts) > 1 else 0
            if stdev == 0:
                continue

            entries = account_entries[account]
            for amount, entry in zip(amounts, entries):
                z_score = abs(float(amount) - mean) / stdev
                if z_score > self.z_threshold:
                    anomalies.append(
                        Anomaly(
                            entry=entry,
                            score=min(z_score / 10.0, 1.0),
                            reason=f"Unusual amount for {account}",
                            details={
                                "amount": str(amount),
                                "mean": f"{mean:.2f}",
                                "stdev": f"{stdev:.2f}",
                                "z_score": f"{z_score:.2f}",
                            },
                        )
                    )
        return anomalies

    def _detect_unusual_accounts(
        self, transactions: list[data.Transaction]
    ) -> list[Anomaly]:
        """Detect transactions posting to rarely-used accounts."""
        account_freq: dict[str, int] = defaultdict(int)
        for entry in transactions:
            for posting in entry.postings:
                account_freq[posting.account] += 1

        total = sum(account_freq.values())
        if total == 0:
            return []

        anomalies = []
        for entry in transactions:
            for posting in entry.postings:
                freq = account_freq[posting.account]
                ratio = freq / total
                if freq <= 2 and total > 50:
                    anomalies.append(
                        Anomaly(
                            entry=entry,
                            score=0.4,
                            reason=f"Rarely used account: {posting.account}",
                            details={
                                "account": posting.account,
                                "frequency": freq,
                                "ratio": f"{ratio:.4f}",
                            },
                        )
                    )
                    break  # One anomaly per entry.
        return anomalies

    def _detect_duplicate_candidates(
        self, transactions: list[data.Transaction]
    ) -> list[Anomaly]:
        """Detect potential duplicate transactions."""
        # Group by (date, amount) to find candidates.
        date_amount_groups: dict[tuple, list[data.Transaction]] = defaultdict(list)

        for entry in transactions:
            for posting in entry.postings:
                if posting.units is not None and posting.units.number is not None:
                    key = (entry.date, posting.units.number, posting.units.currency)
                    date_amount_groups[key].append(entry)
                    break

        anomalies = []
        seen = set()
        for key, group in date_amount_groups.items():
            if len(group) > 1:
                for entry in group:
                    entry_id = id(entry)
                    if entry_id in seen:
                        continue
                    seen.add(entry_id)
                    anomalies.append(
                        Anomaly(
                            entry=entry,
                            score=0.6,
                            reason=f"Possible duplicate: {len(group)} transactions on {key[0]} for {key[1]} {key[2]}",
                            details={
                                "date": str(key[0]),
                                "amount": str(key[1]),
                                "currency": str(key[2]),
                                "count": len(group),
                            },
                        )
                    )
        return anomalies
