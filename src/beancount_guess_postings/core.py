"""Complete imported transactions from the ones already in your ledger."""

from beancount import loader
from beancount.core import data
from beancount.parser import parser, printer
from rapidfuzz import process, utils

DEFAULT_THRESHOLD = 86


def build_key(trans: data.Transaction) -> str:
    """Return a string for comparing the given transaction against others."""
    components = [trans.payee, trans.narration, str(trans.postings[0].units)]
    return " ".join([c for c in components if c is not None])


def mimic(entry, trans, strip_tags=()):
    """Complete the entry with postings copied from the transaction.

    Args:
        entry: the incomplete entry.
        trans: the past transaction to copy postings and tags from.
        strip_tags: tags to leave off the result, whichever entry they came
            from. For tags that a ``pushtag`` in the ledger file already adds.

    Returns:
        A new entry; ``entry`` is left as it was.
    """
    # Copy postings to accounts not already there.
    entry_accounts = {p.account for p in entry.postings}
    added_postings = [p for p in trans.postings if p.account not in entry_accounts]

    # Drop the value of one added posting so the known value applies to both
    # accounts.
    if len(added_postings) == 1:
        added_postings = [added_postings[0]._replace(units=None)]

    # Copy the tags, but remove the ones the caller does not want repeated.
    tags = entry.tags.union(trans.tags) - frozenset(strip_tags)
    return entry._replace(postings=[*entry.postings, *added_postings], tags=tags)


def best_match(query: str, keys: list[str]) -> tuple[str, int] | None:
    """The key most like the query, and how alike they are out of 100.

    Scores are whole numbers, and keys that tie on score go to the earliest, so
    the answer does not depend on how the scorer happens to order equals.

    Returns None when there are no keys to match against.
    """
    found = process.extract(query, keys, processor=utils.default_process, limit=None)
    if not found:
        return None
    best = max(round(score) for _, score, _ in found)
    index = min(i for _, score, i in found if round(score) == best)
    return keys[index], best


def fill(
    training: str, infile: str, threshold: int = DEFAULT_THRESHOLD, strip_tags=()
) -> None:
    """Complete the postings of the transactions in a partial ledger file.

    Builds a dictionary of the past transactions that post to the same account,
    keyed by a summary of payee, narration and amount. Each new transaction is
    fuzzy-matched against those keys, and the postings and tags of the best
    match are copied across.

    Args:
        training: the ledger to learn from; usually your main ledger.
        infile: the partial ledger file to complete.
        threshold: only copy from a match that scores better than this, out of
            100.
        strip_tags: tags to leave off the completed entries (see ``mimic``).

    Prints the result to stdout.
    """
    existing, _, _ = loader.load_file(training)
    importing, _, _ = parser.parse_file(infile)

    # Assume the target account is the first posting found in the import file.
    # This means the training ignores postings targeted to other accounts.
    target_account = None
    for directive in importing:
        if isinstance(directive, data.Transaction):
            target_account = directive.postings[0].account
            break

    # Nothing to complete: the import has no transactions. This happens when the
    # source had no in-range rows, or every row was a duplicate the extractor
    # commented out, leaving only balance directives. Emit a comment marker plus
    # any remaining directives (e.g. balances) so the output stays valid
    # beancount when appended to the ledger, and skip fuzzy matching.
    if target_account is None:
        print("; Nothing to import.")
        for entry in importing:
            printer.print_entry(entry)
        return

    # Build a dictionary of historical entries.
    transactions: dict[str, list[data.Transaction]] = {}
    for directive in existing:
        if isinstance(directive, data.Transaction):
            # Only consider transactions which post to the target account, and
            # that have something to copy: a lone posting teaches nothing.
            accounts = [p.account for p in directive.postings]
            if target_account not in accounts or len(accounts) == 1:
                continue
            transactions.setdefault(build_key(directive), []).append(directive)
    keys = list(transactions)

    # Present completion options for each new transaction.
    for entry in importing:
        if not isinstance(entry, data.Transaction):
            printer.print_entry(entry)
            continue
        match = best_match(build_key(entry), keys)
        if match is None or match[1] <= threshold:
            printer.print_entry(entry)
        else:
            printer.print_entry(mimic(entry, transactions[match[0]][-1], strip_tags))
