"""The ``guess-postings`` and ``guess-postings-comment`` commands."""

import sys

import click

from .comment import comment_transactions
from .core import DEFAULT_THRESHOLD, fill


@click.command(name="guess-postings")
@click.option(
    "--threshold",
    default=DEFAULT_THRESHOLD,
    show_default=True,
    type=int,
    help="Only use fuzz scores better than this.",
)
@click.option(
    "--training",
    required=True,
    type=click.Path(exists=True),
    help="Beancount file to use as a template for predictions; usually your "
    "main ledger.",
)
@click.option(
    "--strip-tag",
    "strip_tags",
    multiple=True,
    help="Leave this tag off completed entries, even if the matched past "
    "transaction has it. Repeatable. Useful when a pushtag in the ledger file "
    "already applies the tag.",
)
@click.argument("infile", type=click.Path(exists=True))
def fill_cli(threshold, training, strip_tags, infile):
    """Complete the postings of the transactions in INFILE.

    Each transaction is fuzzy-matched against the transactions in the training
    ledger that post to the same account, and the postings and tags of the best
    match are copied across. The result goes to standard output.
    """
    fill(training, infile, threshold, [tag.lstrip("#") for tag in strip_tags])


@click.command(name="guess-postings-comment")
@click.argument("accounts", nargs=-1, required=True)
def comment_cli(accounts):
    """Read beancount from stdin; comment out transactions posting to ACCOUNTS.

    Any transaction that contains a posting to one of the given ACCOUNTS has
    every line prefixed with ';', turning it into a beancount comment block.
    All other transactions pass through unchanged. An account matches only by
    its full name: Assets:Bank:Up does not match Assets:Bank:Up-Savings.

    Typical use: pipe guess-postings's output through this command before appending
    to your ledger, to silence transfers that are already recorded in another
    account's file.

    \b
    Example:
        guess-postings --training main.beancount /tmp/joint.beancount \\
            | guess-postings-comment Assets:Bank:Alice-Upbank Assets:Bank:Bob-Upbank \\
            >> joint-2026.beancount
    """
    print(comment_transactions(accounts, sys.stdin.read()), end="")
