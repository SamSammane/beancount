"""Tests for the unified 'bean' CLI."""

import unittest

from click.testing import CliRunner

from beancount.cli.main import bean


class TestBeanCLI(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    def test_help(self):
        result = self.runner.invoke(bean, ["--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Beancount", result.output)
        self.assertIn("Double-entry accounting", result.output)

    def test_version(self):
        result = self.runner.invoke(bean, ["--version"])
        self.assertEqual(result.exit_code, 0)

    def test_check_help(self):
        result = self.runner.invoke(bean, ["check", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("check", result.output.lower())

    def test_format_help(self):
        result = self.runner.invoke(bean, ["format", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("format", result.output.lower())

    def test_detect_help(self):
        result = self.runner.invoke(bean, ["detect", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_categorize_help(self):
        result = self.runner.invoke(bean, ["categorize", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_query_nl_help(self):
        result = self.runner.invoke(bean, ["query-nl", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_import_help(self):
        result = self.runner.invoke(bean, ["import", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_import_csv_help(self):
        result = self.runner.invoke(bean, ["import", "csv", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_import_ofx_help(self):
        result = self.runner.invoke(bean, ["import", "ofx", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_format_no_files(self):
        result = self.runner.invoke(bean, ["format"])
        self.assertNotEqual(result.exit_code, 0)

    def test_detect_with_example(self):
        """Test detect command with an inline example file."""
        import tempfile
        import os

        content = """\
2024-01-01 open Assets:Checking
2024-01-01 open Expenses:Food

2024-01-15 * "Store" "Lunch"
  Assets:Checking  -15.00 USD
  Expenses:Food  15.00 USD
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".beancount", delete=False
        ) as f:
            f.write(content)
            tmpfile = f.name

        try:
            result = self.runner.invoke(bean, ["detect", tmpfile])
            self.assertEqual(result.exit_code, 0)
        finally:
            os.unlink(tmpfile)


    def test_import_auto_help(self):
        result = self.runner.invoke(bean, ["import", "auto", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_import_auto_unknown_format(self):
        """Auto import of an unrecognized file should show a user-friendly error."""
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xyz", delete=False
        ) as f:
            f.write("not a financial file at all!!!")
            tmpfile = f.name
        try:
            result = self.runner.invoke(bean, ["import", "auto", tmpfile])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("Error", result.output)
        finally:
            os.unlink(tmpfile)

    def test_import_csv_with_valid_file(self):
        """Import CSV should work with a valid CSV file."""
        import tempfile
        import os

        content = "date,amount,description\n2024-01-15,-50.00,Groceries\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as f:
            f.write(content)
            tmpfile = f.name
        try:
            result = self.runner.invoke(
                bean, ["import", "csv", tmpfile, "-a", "Assets:Checking"]
            )
            self.assertEqual(result.exit_code, 0)
        finally:
            os.unlink(tmpfile)

    def test_detect_json_output(self):
        """Test detect command with JSON output flag."""
        import tempfile
        import os

        content = """\
2024-01-01 open Assets:Checking
2024-01-01 open Expenses:Food

2024-01-15 * "Store" "Lunch"
  Assets:Checking  -15.00 USD
  Expenses:Food  15.00 USD
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".beancount", delete=False
        ) as f:
            f.write(content)
            tmpfile = f.name
        try:
            result = self.runner.invoke(bean, ["detect", tmpfile, "--json"])
            self.assertEqual(result.exit_code, 0)
        finally:
            os.unlink(tmpfile)


if __name__ == "__main__":
    unittest.main()
