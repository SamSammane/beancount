"""Tests for the AI transaction categorizer."""

import textwrap
import unittest
from unittest import mock

from beancount.ai.categorizer import Categorizer
from beancount.ai.provider import LLMProvider
from beancount.loader import load_string


class MockProvider(LLMProvider):
    """Mock LLM provider for testing."""

    def __init__(self, response='{"account": "Expenses:Food:Restaurant", "confidence": 0.85, "reasoning": "test"}'):
        self.response = response
        self.calls = []

    def complete(self, prompt, system=None):
        self.calls.append(("complete", prompt, system))
        return self.response

    def complete_json(self, prompt, system=None):
        self.calls.append(("complete_json", prompt, system))
        import json
        return json.loads(self.response)


class TestCategorizer(unittest.TestCase):
    def _load_test_entries(self):
        input_text = textwrap.dedent("""\
            2024-01-01 open Assets:Checking
            2024-01-01 open Expenses:Food:Restaurant
            2024-01-01 open Expenses:Food:Groceries
            2024-01-01 open Expenses:Transport:Uber
            2024-01-01 open Income:Salary

            2024-01-15 * "Chipotle" "Lunch"
              Assets:Checking  -15.00 USD
              Expenses:Food:Restaurant  15.00 USD

            2024-01-16 * "Chipotle" "Dinner"
              Assets:Checking  -12.00 USD
              Expenses:Food:Restaurant  12.00 USD

            2024-01-17 * "Whole Foods" "Groceries"
              Assets:Checking  -85.00 USD
              Expenses:Food:Groceries  85.00 USD

            2024-01-18 * "Uber" "Ride to airport"
              Assets:Checking  -45.00 USD
              Expenses:Transport:Uber  45.00 USD
        """)
        entries, errors, options_map = load_string(input_text)
        self.assertEqual(errors, [])
        return entries

    def test_learn_from_entries(self):
        entries = self._load_test_entries()
        provider = MockProvider()
        cat = Categorizer(provider)
        cat.learn_from_entries(entries)

        # Should have learned Chipotle -> Restaurant pattern.
        self.assertIn("Chipotle", cat._account_patterns)
        self.assertEqual(
            cat._account_patterns["Chipotle"][0], "Expenses:Food:Restaurant"
        )

    def test_categorize_known_payee(self):
        entries = self._load_test_entries()
        provider = MockProvider()
        cat = Categorizer(provider)
        cat.learn_from_entries(entries)

        result = cat.categorize(payee="Chipotle", narration="Lunch")
        self.assertEqual(result["account"], "Expenses:Food:Restaurant")
        self.assertGreaterEqual(result["confidence"], 0.9)
        # Should not have called the LLM.
        self.assertEqual(len(provider.calls), 0)

    def test_categorize_unknown_payee_uses_llm(self):
        entries = self._load_test_entries()
        provider = MockProvider()
        cat = Categorizer(provider)
        cat.learn_from_entries(entries)

        result = cat.categorize(payee="New Restaurant", narration="Fancy dinner")
        self.assertEqual(result["account"], "Expenses:Food:Restaurant")
        self.assertEqual(len(provider.calls), 1)

    def test_categorize_llm_failure(self):
        entries = self._load_test_entries()
        provider = MockProvider(response="not valid json")
        cat = Categorizer(provider)

        result = cat.categorize(payee="Unknown", narration="Something")
        self.assertEqual(result["account"], "Expenses:Uncategorized")
        self.assertEqual(result["confidence"], 0.0)

    def test_categorize_batch(self):
        entries = self._load_test_entries()
        provider = MockProvider()
        cat = Categorizer(provider)
        cat.learn_from_entries(entries)

        batch = [
            {"payee": "Chipotle", "narration": "Lunch"},
            {"payee": "Uber", "narration": "Ride"},
        ]
        results = cat.categorize_batch(batch)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["account"], "Expenses:Food:Restaurant")
        self.assertEqual(results[1]["account"], "Expenses:Transport:Uber")


if __name__ == "__main__":
    unittest.main()
