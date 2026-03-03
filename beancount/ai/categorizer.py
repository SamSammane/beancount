"""AI-powered transaction categorizer.

Uses LLM providers to suggest account categories for uncategorized
transactions based on payee, narration, and existing ledger patterns.
"""

from __future__ import annotations

__copyright__ = "Copyright (C) 2026  Beancount Contributors"
__license__ = "GNU GPLv2"

import json
import logging
from collections import Counter
from typing import TYPE_CHECKING

log = logging.getLogger(__name__)

from beancount.core import data

if TYPE_CHECKING:
    from beancount.ai.provider import LLMProvider

# Maximum number of example transactions to include in prompts.
_MAX_EXAMPLES = 50

_SYSTEM_PROMPT = """\
You are a financial bookkeeping assistant specialized in double-entry accounting.
Given a transaction description (payee and narration) and a list of known accounts,
suggest the most appropriate account(s) for categorization.

Always respond with valid JSON in this exact format:
{
  "account": "Expenses:Category:Subcategory",
  "confidence": 0.95,
  "reasoning": "Brief explanation"
}
"""


class Categorizer:
    """Categorize transactions using an LLM provider.

    The categorizer learns from existing ledger entries to suggest
    account assignments for new or uncategorized transactions.
    """

    def __init__(self, provider: LLMProvider):
        self.provider = provider
        self._account_patterns: dict[str, list[str]] = {}

    def learn_from_entries(self, entries: data.Directives) -> None:
        """Learn account assignment patterns from existing entries.

        Args:
          entries: A list of existing ledger directives.
        """
        payee_accounts: dict[str, Counter] = {}

        for entry in data.filter_txns(entries):
            if not entry.postings or len(entry.postings) < 2:
                continue

            # Use the first non-asset/liability posting as the "category".
            category_posting = None
            for posting in entry.postings:
                if posting.account and not (
                    posting.account.startswith("Assets:")
                    or posting.account.startswith("Liabilities:")
                ):
                    category_posting = posting
                    break

            if category_posting is None:
                continue

            account = category_posting.account

            # Track payee -> account mappings.
            if entry.payee:
                if entry.payee not in payee_accounts:
                    payee_accounts[entry.payee] = Counter()
                payee_accounts[entry.payee][account] += 1

        # Store the most common account for each payee.
        self._account_patterns = {}
        for payee, counter in payee_accounts.items():
            most_common = counter.most_common(3)
            accounts = [acc for acc, _ in most_common]
            if accounts:
                self._account_patterns[payee] = accounts

    def categorize(
        self,
        payee: str | None,
        narration: str | None,
        amount_number: str | None = None,
        available_accounts: list[str] | None = None,
    ) -> dict:
        """Suggest an account category for a transaction.

        Args:
          payee: The transaction payee, or None.
          narration: The transaction narration, or None.
          amount_number: The transaction amount as string, or None.
          available_accounts: List of valid account names, or None to use learned ones.
        Returns:
          A dict with 'account', 'confidence', and 'reasoning' keys.
        """
        # First check exact payee match from learned patterns.
        if payee and payee in self._account_patterns:
            accounts = self._account_patterns[payee]
            return {
                "account": accounts[0],
                "confidence": 0.9,
                "reasoning": f"Matched from existing payee pattern: {payee}",
            }

        # Build context for the LLM.
        context_parts = []
        if payee:
            context_parts.append(f"Payee: {payee}")
        if narration:
            context_parts.append(f"Narration: {narration}")
        if amount_number:
            context_parts.append(f"Amount: {amount_number}")

        # Include some learned patterns as examples.
        examples = []
        for p, accounts in list(self._account_patterns.items())[:_MAX_EXAMPLES]:
            examples.append(f"  {p} -> {accounts[0]}")

        prompt_parts = [
            "Categorize this transaction:",
            "\n".join(context_parts),
        ]
        if examples:
            prompt_parts.append("\nExisting patterns from this ledger:")
            prompt_parts.append("\n".join(examples))

        if available_accounts:
            prompt_parts.append(
                "\nAvailable accounts:\n" + "\n".join(f"  {a}" for a in available_accounts[:100])
            )

        prompt = "\n".join(prompt_parts)

        try:
            result = self.provider.complete_json(prompt, system=_SYSTEM_PROMPT)
            if "account" not in result:
                result["account"] = "Expenses:Uncategorized"
            if "confidence" not in result:
                result["confidence"] = 0.5
            if "reasoning" not in result:
                result["reasoning"] = "LLM categorization"
            return result
        except json.JSONDecodeError as exc:
            log.warning("Failed to parse LLM categorization response: %s", exc)
            return {
                "account": "Expenses:Uncategorized",
                "confidence": 0.0,
                "reasoning": f"Failed to parse LLM response as JSON: {exc}",
            }
        except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
            log.warning("LLM categorization request failed: %s", exc)
            return {
                "account": "Expenses:Uncategorized",
                "confidence": 0.0,
                "reasoning": f"LLM request failed: {exc}",
            }

    def categorize_batch(
        self,
        transactions: list[dict],
        available_accounts: list[str] | None = None,
    ) -> list[dict]:
        """Categorize a batch of transactions.

        Args:
          transactions: List of dicts with 'payee', 'narration', and optional 'amount' keys.
          available_accounts: List of valid account names.
        Returns:
          A list of categorization result dicts.
        """
        results = []
        for txn in transactions:
            result = self.categorize(
                payee=txn.get("payee"),
                narration=txn.get("narration"),
                amount_number=txn.get("amount"),
                available_accounts=available_accounts,
            )
            results.append(result)
        return results
