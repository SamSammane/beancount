"""Natural language querying for beancount ledgers.

Allows users to ask questions about their financial data in plain
English and get structured answers.
"""

from __future__ import annotations

__copyright__ = "Copyright (C) 2026  Beancount Contributors"
__license__ = "GNU GPLv2"

import datetime
import json
from collections import defaultdict
from decimal import Decimal
from typing import TYPE_CHECKING
from typing import Any

from beancount.core import data
from beancount.core import getters
from beancount.core import prices
from beancount.core import realization
from beancount.core.inventory import Inventory

if TYPE_CHECKING:
    from beancount.ai.provider import LLMProvider

_SYSTEM_PROMPT = """\
You are a financial data analyst assistant. You have access to a user's
double-entry accounting ledger. Answer their questions about their finances
concisely and accurately.

When you need to specify a query, respond with JSON in this format:
{
  "query_type": "balance|transactions|summary|trend",
  "accounts": ["Account:Name"],
  "date_from": "YYYY-MM-DD",
  "date_to": "YYYY-MM-DD",
  "currency": "USD",
  "keywords": ["keyword1"]
}

When providing a direct answer, respond with:
{
  "answer": "Your answer text here",
  "data": {}
}
"""


class NaturalLanguageQuery:
    """Query beancount ledger data using natural language.

    Translates natural language questions into structured queries,
    executes them against the ledger data, and formats the results.
    """

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    def query(
        self,
        question: str,
        entries: data.Directives,
        options_map: dict[str, Any],
    ) -> dict[str, Any]:
        """Answer a natural language question about ledger data.

        Args:
          question: A natural language question.
          entries: The ledger directives.
          options_map: The options map from the loader.
        Returns:
          A dict with 'answer' and optional 'data' keys.
        """
        # Build a context summary for the LLM.
        context = self._build_context(entries, options_map)

        prompt = (
            f"Given this financial ledger context:\n{context}\n\n"
            f"Question: {question}\n\n"
            "Provide a helpful answer. If you can answer directly from the context, "
            "do so. Include relevant numbers and dates."
        )

        try:
            result = self.provider.complete_json(prompt, system=_SYSTEM_PROMPT)
            if "answer" in result:
                return result

            # If the LLM returned a structured query, execute it.
            if "query_type" in result:
                return self._execute_query(result, entries, options_map, question)

            return {"answer": json.dumps(result)}
        except json.JSONDecodeError:
            # LLM returned plain text; try a plain completion.
            try:
                text = self.provider.complete(prompt, system=_SYSTEM_PROMPT)
                return {"answer": text}
            except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
                return {"answer": f"Error processing query: {exc}"}
        except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
            return {"answer": f"Error processing query: {exc}"}

    def _build_context(
        self,
        entries: data.Directives,
        options_map: dict[str, Any],
    ) -> str:
        """Build a summary context string for the LLM."""
        accounts = sorted(getters.get_accounts(entries))
        transactions = list(data.filter_txns(entries))

        # Date range.
        if transactions:
            first_date = transactions[0].date
            last_date = transactions[-1].date
        else:
            first_date = last_date = datetime.date.today()

        # Account balances summary.
        real_root = realization.realize(entries)
        balance_lines = []
        for real_account in realization.iter_children(real_root):
            if not real_account.balance.is_empty():
                balance_lines.append(
                    f"  {real_account.account}: {real_account.balance}"
                )

        currencies = options_map.get("operating_currency", ["USD"])

        parts = [
            f"Date range: {first_date} to {last_date}",
            f"Total transactions: {len(transactions)}",
            f"Total accounts: {len(accounts)}",
            f"Operating currencies: {', '.join(currencies)}",
            "",
            "Account balances:",
        ]
        # Limit balance lines to keep context manageable.
        parts.extend(balance_lines[:100])

        return "\n".join(parts)

    def _execute_query(
        self,
        query: dict,
        entries: data.Directives,
        options_map: dict[str, Any],
        original_question: str,
    ) -> dict[str, Any]:
        """Execute a structured query against the ledger."""
        query_type = query.get("query_type", "summary")
        account_filters = query.get("accounts", [])
        date_from = query.get("date_from")
        date_to = query.get("date_to")

        # Parse dates (may come from LLM output, so handle errors).
        from_date = None
        to_date = None
        if date_from:
            try:
                from_date = datetime.date.fromisoformat(date_from)
            except ValueError:
                pass
        if date_to:
            try:
                to_date = datetime.date.fromisoformat(date_to)
            except ValueError:
                pass

        # Filter entries.
        filtered = list(data.filter_txns(entries))
        if from_date:
            filtered = [e for e in filtered if e.date >= from_date]
        if to_date:
            filtered = [e for e in filtered if e.date <= to_date]

        if query_type == "balance":
            return self._query_balance(filtered, account_filters)
        elif query_type == "transactions":
            return self._query_transactions(filtered, account_filters, query)
        elif query_type == "trend":
            return self._query_trend(filtered, account_filters)
        else:
            return self._query_summary(filtered, account_filters)

    def _query_balance(
        self,
        transactions: list[data.Transaction],
        accounts: list[str],
    ) -> dict[str, Any]:
        """Query account balances."""
        balances: dict[str, Inventory] = defaultdict(Inventory)

        for entry in transactions:
            for posting in entry.postings:
                if not accounts or any(
                    posting.account.startswith(a) for a in accounts
                ):
                    if posting.units is not None:
                        balances[posting.account].add_amount(posting.units)

        result_lines = []
        for account, inv in sorted(balances.items()):
            result_lines.append(f"{account}: {inv}")

        return {
            "answer": "\n".join(result_lines) if result_lines else "No matching accounts found.",
            "data": {
                "balances": {
                    acc: str(inv) for acc, inv in sorted(balances.items())
                }
            },
        }

    def _query_transactions(
        self,
        transactions: list[data.Transaction],
        accounts: list[str],
        query: dict,
    ) -> dict[str, Any]:
        """Query matching transactions."""
        keywords = [k.lower() for k in query.get("keywords", [])]

        matches = []
        for entry in transactions:
            # Filter by account.
            if accounts:
                entry_accounts = {p.account for p in entry.postings}
                if not any(
                    any(ea.startswith(a) for a in accounts)
                    for ea in entry_accounts
                ):
                    continue

            # Filter by keywords.
            if keywords:
                text = f"{entry.payee or ''} {entry.narration or ''}".lower()
                if not any(kw in text for kw in keywords):
                    continue

            matches.append(entry)

        # Format results.
        result_lines = []
        for entry in matches[-20:]:  # Last 20 matches.
            amounts = []
            for p in entry.postings:
                if p.units is not None:
                    amounts.append(f"{p.units.number} {p.units.currency}")
            amount_str = ", ".join(amounts) if amounts else "N/A"
            result_lines.append(
                f"{entry.date} | {entry.payee or 'N/A'} | "
                f"{entry.narration or 'N/A'} | {amount_str}"
            )

        return {
            "answer": f"Found {len(matches)} matching transactions.\n\n"
            + "\n".join(result_lines),
            "data": {"count": len(matches)},
        }

    def _query_trend(
        self,
        transactions: list[data.Transaction],
        accounts: list[str],
    ) -> dict[str, Any]:
        """Analyze spending/income trends by month."""
        monthly: dict[str, Inventory] = defaultdict(Inventory)

        for entry in transactions:
            month_key = entry.date.strftime("%Y-%m")
            for posting in entry.postings:
                if not accounts or any(
                    posting.account.startswith(a) for a in accounts
                ):
                    if posting.units is not None:
                        monthly[month_key].add_amount(posting.units)

        result_lines = []
        for month, inv in sorted(monthly.items()):
            result_lines.append(f"{month}: {inv}")

        return {
            "answer": "Monthly trend:\n" + "\n".join(result_lines),
            "data": {
                "monthly": {m: str(inv) for m, inv in sorted(monthly.items())}
            },
        }

    def _query_summary(
        self,
        transactions: list[data.Transaction],
        accounts: list[str],
    ) -> dict[str, Any]:
        """Provide a general summary."""
        total_income = Inventory()
        total_expenses = Inventory()

        for entry in transactions:
            for posting in entry.postings:
                if posting.units is None:
                    continue
                if posting.account.startswith("Income:"):
                    total_income.add_amount(posting.units)
                elif posting.account.startswith("Expenses:"):
                    total_expenses.add_amount(posting.units)

        if transactions:
            date_range = f"{transactions[0].date} to {transactions[-1].date}"
        else:
            date_range = "N/A"

        return {
            "answer": (
                f"Summary for {date_range}:\n"
                f"  Transactions: {len(transactions)}\n"
                f"  Total Income: {total_income}\n"
                f"  Total Expenses: {total_expenses}"
            ),
            "data": {
                "count": len(transactions),
                "income": str(total_income),
                "expenses": str(total_expenses),
            },
        }
