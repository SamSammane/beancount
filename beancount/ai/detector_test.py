"""Tests for the anomaly detector."""

import textwrap
import unittest

from beancount.ai.detector import AnomalyDetector
from beancount.loader import load_string


class TestAnomalyDetector(unittest.TestCase):
    def _load_entries(self, input_text):
        entries, errors, options_map = load_string(input_text, dedent=True)
        self.assertEqual(errors, [])
        return entries

    def test_detect_empty_entries(self):
        detector = AnomalyDetector()
        anomalies = detector.detect([])
        self.assertEqual(anomalies, [])

    def test_detect_amount_outlier(self):
        input_text = textwrap.dedent("""\
            2024-01-01 open Assets:Checking
            2024-01-01 open Expenses:Food

            2024-01-01 * "Store" "Groceries"
              Assets:Checking  -50.00 USD
              Expenses:Food  50.00 USD

            2024-01-02 * "Store" "Groceries"
              Assets:Checking  -45.00 USD
              Expenses:Food  45.00 USD

            2024-01-03 * "Store" "Groceries"
              Assets:Checking  -55.00 USD
              Expenses:Food  55.00 USD

            2024-01-04 * "Store" "Groceries"
              Assets:Checking  -48.00 USD
              Expenses:Food  48.00 USD

            2024-01-05 * "Store" "Groceries"
              Assets:Checking  -52.00 USD
              Expenses:Food  52.00 USD

            2024-01-06 * "Store" "Huge purchase"
              Assets:Checking  -5000.00 USD
              Expenses:Food  5000.00 USD
        """)
        entries = self._load_entries(input_text)
        detector = AnomalyDetector(z_threshold=2.0)
        anomalies = detector.detect(entries)

        # The 5000 USD transaction should be detected as an outlier.
        self.assertTrue(len(anomalies) > 0)
        found_outlier = any(
            "5000" in a.details.get("amount", "") for a in anomalies
        )
        self.assertTrue(found_outlier, "Expected to find the 5000 outlier")

    def test_detect_duplicate_candidates(self):
        input_text = textwrap.dedent("""\
            2024-01-01 open Assets:Checking
            2024-01-01 open Expenses:Food

            2024-01-15 * "Store A" "Purchase 1"
              Assets:Checking  -100.00 USD
              Expenses:Food  100.00 USD

            2024-01-15 * "Store B" "Purchase 2"
              Assets:Checking  -100.00 USD
              Expenses:Food  100.00 USD
        """)
        entries = self._load_entries(input_text)
        detector = AnomalyDetector()
        anomalies = detector.detect(entries)

        # Should detect potential duplicates.
        duplicate_anomalies = [a for a in anomalies if "duplicate" in a.reason.lower()]
        self.assertTrue(len(duplicate_anomalies) > 0)

    def test_max_results_limit(self):
        input_text = textwrap.dedent("""\
            2024-01-01 open Assets:Checking
            2024-01-01 open Expenses:Food

            2024-01-01 * "Store" "A"
              Assets:Checking  -10.00 USD
              Expenses:Food  10.00 USD

            2024-01-02 * "Store" "B"
              Assets:Checking  -10.00 USD
              Expenses:Food  10.00 USD
        """)
        entries = self._load_entries(input_text)
        detector = AnomalyDetector()
        anomalies = detector.detect(entries, max_results=1)
        self.assertLessEqual(len(anomalies), 1)

    def test_detect_unusual_accounts(self):
        # Build a ledger with many transactions using common accounts
        # and one transaction using a rare account.
        lines = [
            "2024-01-01 open Assets:Checking",
            "2024-01-01 open Expenses:Food",
            "2024-01-01 open Expenses:Rare:VeryUnusual",
            "",
        ]
        for i in range(60):
            date = f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}"
            lines.append(f'{date} * "Store" "Regular purchase"')
            lines.append(f"  Assets:Checking  -{10 + i}.00 USD")
            lines.append(f"  Expenses:Food  {10 + i}.00 USD")
            lines.append("")

        lines.append('2024-03-15 * "Weird" "Unusual"')
        lines.append("  Assets:Checking  -99.00 USD")
        lines.append("  Expenses:Rare:VeryUnusual  99.00 USD")

        entries = self._load_entries("\n".join(lines))
        detector = AnomalyDetector()
        anomalies = detector.detect(entries)

        rare_anomalies = [a for a in anomalies if "rarely" in a.reason.lower()]
        self.assertTrue(len(rare_anomalies) > 0, "Expected to detect rarely-used account")


if __name__ == "__main__":
    unittest.main()
