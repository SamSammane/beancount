"""Interactive REPL mode for beancount.

Provides an interactive shell where users can load a ledger and run
queries, check balances, and perform AI analysis interactively.
"""

from __future__ import annotations

__copyright__ = "Copyright (C) 2026  Beancount Contributors"
__license__ = "GNU GPLv2"

import cmd
import datetime
import shlex
import sys
from typing import Any

from beancount import loader
from beancount.core import data
from beancount.core import getters
from beancount.core import realization
from beancount.core.display_context import Align
from beancount.parser import options
from beancount.parser import printer


class BeanShell(cmd.Cmd):
    """Interactive beancount shell."""

    intro = "Beancount Interactive Shell. Type 'help' for available commands.\n"
    prompt = "bean> "

    def __init__(self, filename: str | None = None):
        super().__init__()
        self.filename = filename
        self.entries: data.Directives = []
        self.errors: list[data.BeancountError] = []
        self.options_map: dict[str, Any] = {}
        self._loaded = False

        if filename:
            self._load(filename)

    def _load(self, filename: str) -> None:
        """Load a beancount file."""
        self.filename = filename
        print(f"Loading {filename}...")
        self.entries, self.errors, self.options_map = loader.load_file(filename)
        self._loaded = True
        n_txns = len(list(data.filter_txns(self.entries)))
        print(f"Loaded {len(self.entries)} directives ({n_txns} transactions)")
        if self.errors:
            print(f"Warning: {len(self.errors)} errors found")
        print()

    def _require_loaded(self) -> bool:
        """Check if a file is loaded."""
        if not self._loaded:
            print("No file loaded. Use 'load <filename>' first.")
            return False
        return True

    def do_load(self, arg: str) -> None:
        """Load a beancount file: load <filename>"""
        arg = arg.strip()
        if not arg:
            print("Usage: load <filename>")
            return
        self._load(arg)

    def do_reload(self, arg: str) -> None:
        """Reload the current file."""
        if self.filename:
            self._load(self.filename)
        else:
            print("No file loaded.")

    def do_errors(self, arg: str) -> None:
        """Show errors from the loaded file."""
        if not self._require_loaded():
            return
        if not self.errors:
            print("No errors.")
            return
        printer.print_errors(self.errors, file=sys.stdout)

    def do_accounts(self, arg: str) -> None:
        """List all accounts, optionally filtered: accounts [pattern]"""
        if not self._require_loaded():
            return
        accounts = sorted(getters.get_accounts(self.entries))
        pattern = arg.strip().lower()
        if pattern:
            accounts = [a for a in accounts if pattern in a.lower()]
        for account in accounts:
            print(f"  {account}")
        print(f"\n{len(accounts)} accounts")

    def do_balances(self, arg: str) -> None:
        """Show account balances, optionally filtered: balances [pattern]"""
        if not self._require_loaded():
            return
        real_root = realization.realize(self.entries)
        dformat = self.options_map["dcontext"].build(alignment=Align.DOT, reserved=2)
        pattern = arg.strip().lower()

        for real_account in realization.iter_children(real_root):
            if real_account.balance.is_empty():
                continue
            if pattern and pattern not in real_account.account.lower():
                continue
            print(f"  {real_account.account:60s} {real_account.balance}")

    def do_transactions(self, arg: str) -> None:
        """Show recent transactions: transactions [count] [pattern]"""
        if not self._require_loaded():
            return

        parts = arg.strip().split(maxsplit=1)
        count = 10
        pattern = ""
        if parts:
            try:
                count = int(parts[0])
                pattern = parts[1] if len(parts) > 1 else ""
            except ValueError:
                pattern = arg.strip()

        txns = list(data.filter_txns(self.entries))
        if pattern:
            pattern_lower = pattern.lower()
            txns = [
                t for t in txns
                if pattern_lower in (t.payee or "").lower()
                or pattern_lower in (t.narration or "").lower()
            ]

        for txn in txns[-count:]:
            payee = txn.payee or ""
            narration = txn.narration or ""
            amounts = []
            for p in txn.postings:
                if p.units is not None:
                    amounts.append(f"{p.units.number} {p.units.currency}")
            amount_str = ", ".join(amounts[:2])
            print(f"  {txn.date} | {payee:20s} | {narration:40s} | {amount_str}")

        print(f"\nShowing last {min(count, len(txns))} of {len(txns)} transactions")

    def do_stats(self, arg: str) -> None:
        """Show ledger statistics."""
        if not self._require_loaded():
            return

        txns = list(data.filter_txns(self.entries))
        accounts = getters.get_accounts(self.entries)

        if txns:
            first_date = txns[0].date
            last_date = txns[-1].date
        else:
            first_date = last_date = datetime.date.today()

        currencies = self.options_map.get("operating_currency", [])

        print(f"  File: {self.filename}")
        print(f"  Directives: {len(self.entries)}")
        print(f"  Transactions: {len(txns)}")
        print(f"  Accounts: {len(accounts)}")
        print(f"  Date range: {first_date} to {last_date}")
        print(f"  Currencies: {', '.join(currencies)}")
        print(f"  Errors: {len(self.errors)}")

    def do_quit(self, arg: str) -> bool:
        """Exit the shell."""
        print("Goodbye!")
        return True

    do_exit = do_quit
    do_EOF = do_quit

    def emptyline(self) -> None:
        pass


def run_interactive(filename: str | None = None) -> None:
    """Launch the interactive beancount shell."""
    shell = BeanShell(filename)
    shell.cmdloop()
