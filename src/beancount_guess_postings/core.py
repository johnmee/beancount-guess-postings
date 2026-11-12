"""Complete imported transactions from the ones already in your ledger."""

import warnings
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from beancount import loader
from beancount.core import data
from beancount.parser import parser, printer
from rapidfuzz import process, utils

DEFAULT_THRESHOLD = 86

# The metadata key beangulp's extract marks a duplicate with. It prints such
# entries commented out (beangulp.extract.DUPLICATE).
DUPLICATE = "__duplicate__"

# What beangulp passes its import hooks: for each document, its name, the entries
# extracted from it, its account and the importer.
Extracted = list[tuple[str, list[data.Directive], str, Any]]


class ParseError(Exception):
    """The file to complete is not valid beancount.

    Completing it anyway would silently drop whatever could not be read, so
    nothing is completed. ``errors`` holds beancount's own error entries.
    """

    def __init__(self, filename: str, errors: list[data.BeancountError]) -> None:
        super().__init__(f"{len(errors)} error(s) in {filename}; nothing was output")
        self.filename = filename
        self.errors = errors


class LedgerWarning(UserWarning):
    """The ledger being learnt from has errors of its own."""


def build_key(trans: data.Transaction, account: str | None = None) -> str:
    """Return a string for comparing the given transaction against others.

    The payee, the narration and an amount, leaving out whichever of them the
    transaction does not have.

    Args:
        trans: the transaction to summarise.
        account: take the amount from the first posting to this account, so a
            past transaction is compared by the same side as a new one however
            its postings are ordered. By default, the first posting of all.
    """
    postings = [p for p in trans.postings if account in (None, p.account)]
    units = postings[0].units if postings else None
    components = [trans.payee, trans.narration, units]
    return " ".join(str(c) for c in components if c is not None)


def _names(names: str | Iterable[str]) -> frozenset[str]:
    """The given names as a set; a lone string is one name, not its letters."""
    return frozenset([names] if isinstance(names, str) else names)


def mimic(
    entry: data.Transaction,
    trans: data.Transaction,
    strip_tags: str | Iterable[str] = (),
) -> data.Transaction:
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
    # accounts. A split of several postings keeps the amounts it had: the
    # entry's own amount is never altered, so when it differs from the past one
    # the result does not balance, and beancount points the user at the split
    # to adjust.
    if len(added_postings) == 1:
        added_postings = [added_postings[0]._replace(units=None)]

    # Copy the tags, but remove the ones the caller does not want repeated.
    tags = entry.tags.union(trans.tags) - _names(strip_tags)
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


def _check_threshold(threshold: int) -> None:
    if not 0 <= threshold <= 100:
        raise ValueError(f"threshold must be from 0 to 100, not {threshold}")


def complete(
    importing: Iterable[data.Directive],
    existing: Iterable[data.Directive],
    threshold: int = DEFAULT_THRESHOLD,
    strip_tags: str | Iterable[str] = (),
) -> list[data.Directive]:
    """Complete the postings of new transactions from the existing ones.

    Each new transaction is fuzzy-matched against the existing transactions that
    post to the same account as its first posting, by a summary of payee,
    narration and amount. The postings and tags of the best match are copied
    across.

    Args:
        importing: the new directives.
        existing: the directives to learn from; usually your main ledger.
        threshold: only copy from a match that scores better than this, from 0
            to 100. At 100 nothing is ever copied.
        strip_tags: tags to leave off the completed entries (see ``mimic``).

    Returns:
        Every one of ``importing``, in order, with the transactions that found
        a match completed.

    Raises:
        ValueError: if ``threshold`` is not from 0 to 100.
    """
    _check_threshold(threshold)
    importing = list(importing)
    past = _index(existing, _accounts(importing))
    return _complete(importing, past, threshold, _names(strip_tags))


def _accounts(importing: Iterable[data.Directive]) -> set[str]:
    """The accounts the new transactions belong to."""
    # A new transaction belongs to the account of its first posting: the side
    # the importer wrote. One with no postings gives nothing to match on.
    return {
        entry.postings[0].account
        for entry in importing
        if isinstance(entry, data.Transaction) and entry.postings
    }


def _index(
    existing: Iterable[data.Directive], accounts: set[str]
) -> dict[str, dict[str, data.Transaction]]:
    """The past transactions to match against, by account and summary."""
    # For each of those accounts, the past transactions that post to it, by
    # summary. A lone posting teaches nothing, and of several transactions with
    # the same summary the latest is the one to copy.
    past: dict[str, dict[str, data.Transaction]] = {a: {} for a in accounts}
    for directive in existing:
        if isinstance(directive, data.Transaction) and len(directive.postings) > 1:
            for account in accounts.intersection(p.account for p in directive.postings):
                past[account][build_key(directive, account)] = directive
    return past


def _complete(
    importing: Iterable[data.Directive],
    past: dict[str, dict[str, data.Transaction]],
    threshold: int,
    stripped: frozenset[str],
) -> list[data.Directive]:
    """``complete``, from an index ``_index`` built for the new transactions."""
    # Complete each new transaction from the best match on its own account. An
    # import with no transactions (every row a duplicate, say) falls straight
    # through, so only its other directives, such as balances, come out.
    completed: list[data.Directive] = []
    for entry in importing:
        if isinstance(entry, data.Transaction) and entry.postings:
            candidates = past[entry.postings[0].account]
            match = best_match(build_key(entry), list(candidates))
            if match is not None and match[1] > threshold:
                entry = mimic(entry, candidates[match[0]], stripped)
        completed.append(entry)
    return completed


def fill(
    ledger: str,
    infile: str,
    threshold: int = DEFAULT_THRESHOLD,
    strip_tags: str | Iterable[str] = (),
) -> list[data.Directive]:
    """Complete the postings of the transactions in a partial ledger file.

    ``complete``, reading the new transactions from ``infile`` and the ones to
    learn from from ``ledger``.

    Args:
        ledger: the ledger to learn from; usually your main ledger.
        infile: the partial ledger file to complete.
        threshold: as for ``complete``.
        strip_tags: as for ``complete``.

    Returns:
        Every directive of ``infile``, in order, with the transactions that
        found a match completed. Pass them to ``render`` for beancount text.

    Raises:
        ParseError: if ``infile`` has syntax errors.
        ValueError: if ``threshold`` is not from 0 to 100.

    Warns:
        LedgerWarning: if the ledger has errors. It is learnt from all the
            same: a ledger that does not yet balance is still worth it.
    """
    # ``complete`` checks it too, but only after the ledger has been loaded.
    _check_threshold(threshold)
    importing, import_errors, _ = parser.parse_file(infile)
    if import_errors:
        raise ParseError(infile, import_errors)

    existing, ledger_errors, _ = loader.load_file(ledger)
    if ledger_errors:
        warnings.warn(
            f"{len(ledger_errors)} error(s) in {ledger}; run bean-check to see them",
            LedgerWarning,
            stacklevel=2,
        )
    return complete(importing, existing, threshold, strip_tags)


def hook(
    threshold: int = DEFAULT_THRESHOLD,
    strip_tags: str | Iterable[str] = (),
    mute: str | Iterable[str] = (),
) -> Callable[[Extracted, Sequence[data.Directive]], Extracted]:
    """A beangulp import hook that completes the extracted transactions.

    Pass it to ``beangulp.Ingest(importers, hooks=[hook(...)])``. It completes
    every extracted entry with ``complete``, learning from the ledger given to
    ``extract --existing``. beangulp runs hooks after it has marked duplicates
    and before it prints, so a duplicate is completed too, and is still printed
    commented out.

    Args:
        threshold: as for ``complete``.
        strip_tags: as for ``complete``.
        mute: accounts that another file books the transfers to. A transaction
            that, once completed, posts to exactly one of them is marked as a
            duplicate, so beangulp prints it commented out. Only transactions
            are ever marked.

    Raises:
        ValueError: if ``threshold`` is not from 0 to 100.
    """
    _check_threshold(threshold)
    stripped = _names(strip_tags)
    muted = _names(mute)

    def guess_postings(
        extracted: Extracted, existing: Sequence[data.Directive]
    ) -> Extracted:
        # beangulp has already added the extracted entries to ``existing``. Learn
        # only from the rest, the ledger, as ``fill`` does: an imported entry
        # would otherwise match itself, or teach the documents after it.
        imported = [e for _, entries, _, _ in extracted for e in entries]
        ids = {id(e) for e in imported}
        ledger = (d for d in existing if id(d) not in ids)

        # One pass over the ledger for every document, not one per document.
        past = _index(ledger, _accounts(imported))
        result: Extracted = []
        for filename, entries, account, importer in extracted:
            marked: list[data.Directive] = []
            for entry in _complete(entries, past, threshold, stripped):
                if (
                    isinstance(entry, data.Transaction)
                    and DUPLICATE not in entry.meta
                    and any(posting.account in muted for posting in entry.postings)
                ):
                    # A new meta: a completed entry shares its meta with the
                    # extracted one, which is in ``existing`` too.
                    entry = entry._replace(meta={**entry.meta, DUPLICATE: True})
                marked.append(entry)
            result.append((filename, marked, account, importer))
        return result

    return guess_postings


def render(entries: Iterable[data.Directive]) -> str:
    """Return the entries as beancount text, a blank line after each.

    Args:
        entries: the directives to write, such as ``fill`` returns.
    """
    return "".join(printer.format_entry(entry) + "\n" for entry in entries)
