"""Unified 'bean' CLI entry point.

Groups all beancount commands under a single 'bean' command with
subcommands for checking, formatting, querying, AI analysis,
importing, and more.
"""

from __future__ import annotations

__copyright__ = "Copyright (C) 2026  Beancount Contributors"
__license__ = "GNU GPLv2"

import sys

import click

from beancount.parser.version import VERSION


class AliasGroup(click.Group):
    """Click group supporting command aliases and dash/underscore normalization."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aliases: dict[str, str] = {}

    def command(self, *args, aliases=None, **kwargs):
        wrap = click.Group.command(self, *args, **kwargs)

        def decorator(f):
            cmd = wrap(f)
            if aliases:
                for alias in aliases:
                    self.aliases[alias] = cmd.name
            return cmd

        return decorator

    def group(self, *args, aliases=None, **kwargs):
        wrap = click.Group.group(self, *args, **kwargs)

        def decorator(f):
            cmd = wrap(f)
            if aliases:
                for alias in aliases:
                    self.aliases[alias] = cmd.name
            return cmd

        return decorator

    def get_command(self, ctx, cmd_name):
        name = self.aliases.get(cmd_name, cmd_name)
        name = name.replace("_", "-")
        return click.Group.get_command(self, ctx, name)

    def format_help(self, ctx, formatter):
        """Customize help output with grouped commands."""
        self.format_usage(ctx, formatter)
        self.format_help_text(ctx, formatter)

        # Group commands by category.
        categories: dict[str, list[tuple[str, click.Command]]] = {
            "Core": [],
            "AI & Analysis": [],
            "Connectors": [],
            "Tools": [],
        }

        for name in sorted(self.list_commands(ctx)):
            cmd = self.get_command(ctx, name)
            if cmd is None or cmd.hidden:
                continue
            help_text = cmd.get_short_help_str(limit=50)
            if name in ("check", "format", "example", "doctor"):
                categories["Core"].append((name, help_text))
            elif name in ("ai", "categorize", "query-nl", "detect"):
                categories["AI & Analysis"].append((name, help_text))
            elif name in ("import", "connectors"):
                categories["Connectors"].append((name, help_text))
            else:
                categories["Tools"].append((name, help_text))

        for category, commands in categories.items():
            if not commands:
                continue
            with formatter.section(f"{category} Commands"):
                formatter.write_dl(commands)

        self.format_epilog(ctx, formatter)


@click.command(cls=AliasGroup)
@click.version_option(VERSION, prog_name="bean")
@click.option(
    "--color/--no-color",
    default=None,
    help="Force colored output on or off.",
)
@click.pass_context
def bean(ctx, color):
    """Beancount: Double-entry accounting from text files.

    A modern command-line interface for managing, analyzing, and
    importing financial data with your Beancount ledger.
    """
    ctx.ensure_object(dict)
    ctx.obj["color"] = color


# -- Core commands --


@bean.command(aliases=["chk"])
@click.argument("filename", type=click.Path(exists=True))
@click.option("--verbose", "-v", is_flag=True, help="Print timings.")
@click.option("--no-cache", "-C", is_flag=True, help="Disable the cache.")
@click.option("--cache-filename", type=click.Path(), help="Override the cache filename.")
@click.option("--auto", "-a", is_flag=True, help="Enable auto-plugins.")
@click.option("--json", "json_output", is_flag=True, help="Output errors as JSON.")
def check(filename, verbose, no_cache, cache_filename, auto, json_output):
    """Parse, check and validate a beancount ledger."""
    from beancount.scripts.check import main as check_main

    # Build argv for the existing check main.
    args = [filename]
    if verbose:
        args.append("--verbose")
    if no_cache:
        args.append("--no-cache")
    if cache_filename:
        args.extend(["--cache-filename", cache_filename])
    if auto:
        args.append("--auto")
    if json_output:
        args.append("--json")
    check_main(args, standalone_mode=False)


@bean.command(aliases=["fmt"])
@click.argument("filenames", nargs=-1, type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), help="Output file.")
@click.option("--currency-column", "-c", type=int, help="Align currencies to this column.")
@click.option("--in-place", "-i", is_flag=True, help="Edit files in place.")
def format(filenames, output, currency_column, in_place):
    """Format and align a beancount ledger."""
    from beancount.scripts.format import align_beancount

    if not filenames:
        click.echo("Error: At least one FILENAME is required.", err=True)
        raise SystemExit(2)

    for filepath in filenames:
        with open(filepath, encoding="utf-8") as f:
            contents = f.read()
        formatted = align_beancount(contents, currency_column=currency_column)
        if in_place:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(formatted)
            click.echo(f"Formatted: {filepath}")
        elif output:
            with open(output, "w", encoding="utf-8") as f:
                f.write(formatted)
        else:
            click.echo(formatted, nl=False)


@bean.command()
@click.option("--seed", "-s", type=int, help="Random seed.")
@click.option("--output", "-o", type=click.Path(), help="Output file.")
def example(seed, output):
    """Generate an example beancount ledger."""
    from beancount.scripts.example import main as example_main

    args = []
    if seed is not None:
        args.extend(["--seed", str(seed)])
    if output:
        args.extend(["--output", output])
    example_main(args, standalone_mode=False)


@bean.command()
@click.argument("filename", type=click.Path(exists=True))
@click.argument("subcommand", required=False)
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def doctor(ctx, filename, subcommand, extra_args):
    """Debugging and diagnostic tools for a ledger."""
    from beancount.scripts.doctor import main as doctor_main

    args = []
    if subcommand:
        args.append(subcommand)
    args.append(filename)
    args.extend(extra_args)
    doctor_main(args, standalone_mode=False)


# -- AI commands --


@bean.command(aliases=["cat"])
@click.argument("filename", type=click.Path(exists=True))
@click.option("--payee", "-p", help="Payee to categorize.")
@click.option("--narration", "-n", help="Narration to categorize.")
@click.option("--provider", type=click.Choice(["openai", "anthropic", "ollama"]), help="LLM provider.")
def categorize(filename, payee, narration, provider):
    """AI-powered transaction categorization.

    Learns from your existing ledger to suggest account categories
    for new transactions.
    """
    from beancount import loader as bn_loader
    from beancount.ai.categorizer import Categorizer
    from beancount.ai.provider import get_provider

    entries, errors, options_map = bn_loader.load_file(filename)

    llm = get_provider(provider)
    cat = Categorizer(llm)
    cat.learn_from_entries(entries)

    if payee or narration:
        result = cat.categorize(payee=payee, narration=narration)
        click.echo(f"Suggested account: {result['account']}")
        click.echo(f"Confidence: {result['confidence']:.0%}")
        click.echo(f"Reasoning: {result['reasoning']}")
    else:
        click.echo("Categorizer loaded and ready. Provide --payee or --narration to categorize.")


@bean.command(name="query-nl", aliases=["ask"])
@click.argument("filename", type=click.Path(exists=True))
@click.argument("question")
@click.option("--provider", type=click.Choice(["openai", "anthropic", "ollama"]), help="LLM provider.")
def query_nl(filename, question, provider):
    """Ask natural language questions about your ledger.

    Example: bean query-nl ledger.beancount "What were my top expenses last month?"
    """
    from beancount import loader as bn_loader
    from beancount.ai.nlquery import NaturalLanguageQuery
    from beancount.ai.provider import get_provider

    entries, errors, options_map = bn_loader.load_file(filename)

    llm = get_provider(provider)
    nlq = NaturalLanguageQuery(llm)
    result = nlq.query(question, entries, options_map)
    click.echo(result["answer"])


@bean.command(aliases=["anomalies"])
@click.argument("filename", type=click.Path(exists=True))
@click.option("--threshold", "-t", type=float, default=2.5, help="Z-score threshold.")
@click.option("--max-results", "-n", type=int, default=20, help="Maximum results to show.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def detect(filename, threshold, max_results, json_output):
    """Detect anomalous transactions in a ledger."""
    import json

    from beancount import loader as bn_loader
    from beancount.ai.detector import AnomalyDetector

    entries, errors, options_map = bn_loader.load_file(filename)

    detector = AnomalyDetector(z_threshold=threshold)
    anomalies = detector.detect(entries, max_results=max_results)

    if json_output:
        output = []
        for a in anomalies:
            output.append({
                "date": str(a.entry.date),
                "payee": a.entry.payee,
                "narration": a.entry.narration,
                "score": a.score,
                "reason": a.reason,
                "details": a.details,
            })
        click.echo(json.dumps(output, indent=2))
    else:
        if not anomalies:
            click.echo("No anomalies detected.")
            return

        click.echo(f"Found {len(anomalies)} anomalies:\n")
        for i, a in enumerate(anomalies, 1):
            click.echo(f"{i}. [{a.score:.0%}] {a.entry.date} | {a.entry.payee or 'N/A'}")
            click.echo(f"   {a.entry.narration or 'N/A'}")
            click.echo(f"   Reason: {a.reason}")
            click.echo()


# -- Connector commands --


@bean.group(name="import", cls=AliasGroup)
def import_group():
    """Import transactions from external sources."""
    pass


@import_group.command(name="csv")
@click.argument("csv_file", type=click.Path(exists=True))
@click.option("--config", "-c", type=click.Path(exists=True), help="Importer config file.")
@click.option("--account", "-a", help="Target account name.")
@click.option("--output", "-o", type=click.Path(), help="Output file.")
def import_csv(csv_file, config, account, output):
    """Import transactions from a CSV file."""
    from beancount.connectors.csv_connector import CSVConnector

    connector = CSVConnector()
    if config:
        connector.load_config(config)
    if account:
        connector.default_account = account

    entries = connector.extract(csv_file)
    _output_entries(entries, output)


@import_group.command(name="ofx")
@click.argument("ofx_file", type=click.Path(exists=True))
@click.option("--account", "-a", help="Target account name.")
@click.option("--output", "-o", type=click.Path(), help="Output file.")
def import_ofx(ofx_file, account, output):
    """Import transactions from an OFX/QFX file."""
    from beancount.connectors.ofx_connector import OFXConnector

    connector = OFXConnector()
    if account:
        connector.default_account = account

    entries = connector.extract(ofx_file)
    _output_entries(entries, output)


def _output_entries(entries, output_path):
    """Write entries to output or stdout."""
    from beancount.parser import printer

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            printer.print_entries(entries, file=f)
        click.echo(f"Wrote {len(entries)} entries to {output_path}")
    else:
        printer.print_entries(entries)


def main():
    """Entry point for the 'bean' CLI."""
    bean()


if __name__ == "__main__":
    main()
