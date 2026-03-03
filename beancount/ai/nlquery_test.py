"""Tests for the natural language query module."""

import textwrap
import unittest
from unittest.mock import MagicMock

from beancount.ai.nlquery import NaturalLanguageQuery
from beancount.loader import load_string


def _make_ledger():
    """Create a test ledger with entries."""
    input_text = textwrap.dedent("""\
        option "operating_currency" "USD"

        2024-01-01 open Assets:Checking
        2024-01-01 open Expenses:Food
        2024-01-01 open Expenses:Rent
        2024-01-01 open Income:Salary

        2024-01-15 * "Employer" "Salary"
          Assets:Checking  5000.00 USD
          Income:Salary  -5000.00 USD

        2024-01-20 * "Store" "Groceries"
          Assets:Checking  -100.00 USD
          Expenses:Food  100.00 USD

        2024-02-01 * "Landlord" "February rent"
          Assets:Checking  -1500.00 USD
          Expenses:Rent  1500.00 USD

        2024-02-15 * "Employer" "Salary"
          Assets:Checking  5000.00 USD
          Income:Salary  -5000.00 USD

        2024-02-20 * "Store" "Groceries"
          Assets:Checking  -120.00 USD
          Expenses:Food  120.00 USD
    """)
    entries, errors, options_map = load_string(input_text, dedent=True)
    assert not errors
    return entries, options_map


class TestNaturalLanguageQuery(unittest.TestCase):
    def setUp(self):
        self.entries, self.options_map = _make_ledger()
        self.provider = MagicMock()

    def test_query_direct_answer(self):
        self.provider.complete_json.return_value = {
            "answer": "Your total expenses are $1720."
        }
        nlq = NaturalLanguageQuery(self.provider)
        result = nlq.query("What are my expenses?", self.entries, self.options_map)
        self.assertEqual(result["answer"], "Your total expenses are $1720.")

    def test_query_balance_type(self):
        self.provider.complete_json.return_value = {
            "query_type": "balance",
            "accounts": ["Expenses:Food"],
        }
        nlq = NaturalLanguageQuery(self.provider)
        result = nlq.query("What's my food balance?", self.entries, self.options_map)
        self.assertIn("answer", result)
        self.assertIn("Expenses:Food", result["answer"])

    def test_query_transactions_type(self):
        self.provider.complete_json.return_value = {
            "query_type": "transactions",
            "accounts": ["Expenses:Food"],
            "keywords": ["Groceries"],
        }
        nlq = NaturalLanguageQuery(self.provider)
        result = nlq.query("Show food transactions", self.entries, self.options_map)
        self.assertIn("answer", result)
        self.assertIn("data", result)
        self.assertGreater(result["data"]["count"], 0)

    def test_query_trend_type(self):
        self.provider.complete_json.return_value = {
            "query_type": "trend",
            "accounts": ["Expenses:"],
        }
        nlq = NaturalLanguageQuery(self.provider)
        result = nlq.query("Show expense trends", self.entries, self.options_map)
        self.assertIn("Monthly trend", result["answer"])
        self.assertIn("monthly", result["data"])

    def test_query_summary_type(self):
        self.provider.complete_json.return_value = {
            "query_type": "summary",
            "accounts": [],
        }
        nlq = NaturalLanguageQuery(self.provider)
        result = nlq.query("Give me a summary", self.entries, self.options_map)
        self.assertIn("Summary", result["answer"])
        self.assertIn("count", result["data"])

    def test_query_with_date_filter(self):
        self.provider.complete_json.return_value = {
            "query_type": "transactions",
            "accounts": [],
            "date_from": "2024-02-01",
            "date_to": "2024-02-28",
        }
        nlq = NaturalLanguageQuery(self.provider)
        result = nlq.query("February transactions", self.entries, self.options_map)
        self.assertIn("answer", result)

    def test_query_with_invalid_date_filter(self):
        """Malformed dates from LLM should not crash."""
        self.provider.complete_json.return_value = {
            "query_type": "summary",
            "accounts": [],
            "date_from": "not-a-date",
            "date_to": "also-bad",
        }
        nlq = NaturalLanguageQuery(self.provider)
        result = nlq.query("Summary", self.entries, self.options_map)
        self.assertIn("answer", result)

    def test_query_json_decode_error_fallback(self):
        """When complete_json fails, falls back to plain complete()."""
        import json

        self.provider.complete_json.side_effect = json.JSONDecodeError("bad", "", 0)
        self.provider.complete.return_value = "Here is a plain text answer."
        nlq = NaturalLanguageQuery(self.provider)
        result = nlq.query("What happened?", self.entries, self.options_map)
        self.assertEqual(result["answer"], "Here is a plain text answer.")

    def test_query_json_decode_and_fallback_both_fail(self):
        """When both complete_json and complete fail, returns error."""
        import json

        self.provider.complete_json.side_effect = json.JSONDecodeError("bad", "", 0)
        self.provider.complete.side_effect = ConnectionError("network down")
        nlq = NaturalLanguageQuery(self.provider)
        result = nlq.query("What happened?", self.entries, self.options_map)
        self.assertIn("Error", result["answer"])

    def test_query_provider_error(self):
        self.provider.complete_json.side_effect = ConnectionError("timeout")
        nlq = NaturalLanguageQuery(self.provider)
        result = nlq.query("Anything?", self.entries, self.options_map)
        self.assertIn("Error", result["answer"])

    def test_query_balance_no_matching_accounts(self):
        self.provider.complete_json.return_value = {
            "query_type": "balance",
            "accounts": ["Nonexistent:Account"],
        }
        nlq = NaturalLanguageQuery(self.provider)
        result = nlq.query("Balance?", self.entries, self.options_map)
        self.assertIn("No matching", result["answer"])

    def test_query_transactions_no_matches(self):
        self.provider.complete_json.return_value = {
            "query_type": "transactions",
            "accounts": [],
            "keywords": ["xyznonexistent"],
        }
        nlq = NaturalLanguageQuery(self.provider)
        result = nlq.query("Find xyznonexistent", self.entries, self.options_map)
        self.assertEqual(result["data"]["count"], 0)

    def test_build_context(self):
        nlq = NaturalLanguageQuery(self.provider)
        context = nlq._build_context(self.entries, self.options_map)
        self.assertIn("Date range:", context)
        self.assertIn("Total transactions:", context)
        self.assertIn("USD", context)

    def test_empty_entries(self):
        self.provider.complete_json.return_value = {
            "query_type": "summary",
            "accounts": [],
        }
        nlq = NaturalLanguageQuery(self.provider)
        result = nlq.query("Summary?", [], self.options_map)
        self.assertIn("answer", result)


if __name__ == "__main__":
    unittest.main()
