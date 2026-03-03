"""Tests for the interactive shell."""

import io
import textwrap
import tempfile
import os
import unittest

from beancount.cli.interactive import BeanShell


class TestBeanShell(unittest.TestCase):
    def setUp(self):
        self.content = textwrap.dedent("""\
            option "operating_currency" "USD"

            2024-01-01 open Assets:Checking
            2024-01-01 open Expenses:Food
            2024-01-01 open Income:Salary

            2024-01-15 * "Employer" "Salary"
              Assets:Checking  5000.00 USD
              Income:Salary  -5000.00 USD

            2024-01-20 * "Store" "Groceries"
              Assets:Checking  -100.00 USD
              Expenses:Food  100.00 USD
        """)
        fd, self.tmpfile = tempfile.mkstemp(suffix=".beancount")
        with os.fdopen(fd, "w") as f:
            f.write(self.content)

    def tearDown(self):
        os.unlink(self.tmpfile)

    def test_load_file(self):
        shell = BeanShell(self.tmpfile)
        self.assertTrue(shell._loaded)
        self.assertGreater(len(shell.entries), 0)

    def test_require_loaded(self):
        shell = BeanShell()
        self.assertFalse(shell._require_loaded())

    def test_stats(self):
        shell = BeanShell(self.tmpfile)
        # Just ensure it doesn't crash.
        shell.do_stats("")

    def test_accounts(self):
        shell = BeanShell(self.tmpfile)
        shell.do_accounts("")

    def test_accounts_with_filter(self):
        shell = BeanShell(self.tmpfile)
        shell.do_accounts("checking")

    def test_balances(self):
        shell = BeanShell(self.tmpfile)
        shell.do_balances("")

    def test_transactions(self):
        shell = BeanShell(self.tmpfile)
        shell.do_transactions("")

    def test_transactions_with_count(self):
        shell = BeanShell(self.tmpfile)
        shell.do_transactions("5")

    def test_transactions_with_filter(self):
        shell = BeanShell(self.tmpfile)
        shell.do_transactions("Store")

    def test_errors(self):
        shell = BeanShell(self.tmpfile)
        shell.do_errors("")

    def test_reload(self):
        shell = BeanShell(self.tmpfile)
        shell.do_reload("")
        self.assertTrue(shell._loaded)


if __name__ == "__main__":
    unittest.main()
