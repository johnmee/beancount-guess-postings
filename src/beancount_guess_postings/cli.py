"""The ``guess-postings`` command."""

import os
import sys
import warnings
from pathlib import Path

import click
from beancount.parser import printer

from .core import DEFAULT_THRESHOLD, LedgerWarning, ParseError, fill, render

LEDGER_ENVVAR = "BEANCOUNT_FILE"


def _existing_ledger(ctx: click.Context, param: click.Parameter, value: str) -> str:
    """Check the ledger is one file that exists.

    Fava lets ``BEANCOUNT_FILE`` list several ledgers; only one can be learnt
    from, and guessing which would be worse than asking.
    """
    if Path(value).is_file():
        return value
    if os.pathsep in value:
        raise click.BadParameter(
            f"{value!r} names more than one file; choose one with --ledger."
        )
    raise click.BadParameter(f"File {value!r} does not exist.")


@click.command(
    name="guess-postings", context_settings={"help_option_names": ["-h", "--help"]}
)
@click.option(
    "--ledger",
    "-l",
    required=True,
    envvar=LEDGER_ENVVAR,
    show_envvar=True,
    type=click.Path(),
    callback=_existing_ledger,
    help="Beancount file whose past transactions the guesses are copied from; "
    "usually your main ledger.",
)
@click.option(
    "--threshold",
    default=DEFAULT_THRESHOLD,
    show_default=True,
    type=click.IntRange(0, 100),
    metavar="INTEGER",
    help="Only use fuzz scores better than this, out of 100. Lower the number "
    "to fill in more matches with less confident guesses.",
)
@click.option(
    "--strip-tag",
    "strip_tags",
    multiple=True,
    metavar="TAG",
    help="Leave this tag off completed entries, even if the matched past "
    "transaction has it. Repeatable. Useful when a pushtag in the ledger file "
    "already applies the tag.",
)
@click.option(
    "--mute",
    "mute",
    multiple=True,
    metavar="ACCOUNT",
    help="Comment out every transaction that, once completed, posts to this "
    "account. Repeatable. Useful for transfers that another account's file "
    "already records.",
)
@click.version_option(package_name="beancount-guess-postings")
@click.argument("infile", type=click.Path(exists=True, dir_okay=False))
def fill_cli(
    ledger: str,
    threshold: int,
    strip_tags: tuple[str, ...],
    mute: tuple[str, ...],
    infile: str,
) -> None:
    """Complete the postings of the transactions in INFILE.

    Each transaction is fuzzy-matched against the transactions in the ledger
    that post to the same account, and the postings and tags of the best match
    are copied across. The result goes to standard output.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", LedgerWarning)
        try:
            entries = fill(
                ledger,
                infile,
                threshold,
                strip_tags=[tag.lstrip("#") for tag in strip_tags],
            )
        except ParseError as error:
            printer.print_errors(error.errors, file=sys.stderr)
            raise click.ClickException(str(error)) from error

    for warning in caught:
        if issubclass(warning.category, LedgerWarning):
            click.echo(f"warning: {warning.message}", err=True)
        else:
            warnings.showwarning(
                warning.message, warning.category, warning.filename, warning.lineno
            )

    # UTF-8 whatever the locale, as beancount's own printer writes.
    sys.stdout.buffer.write(render(entries, mute).encode("utf-8"))
