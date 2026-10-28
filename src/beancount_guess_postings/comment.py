"""Silence transactions that another account's ledger already records."""

import re

# An indented line that starts with an account name: a posting, optionally
# preceded by a flag. The account is the first whitespace-delimited token, so a
# mention in a narration, a comment or a metadata value never matches.
POSTING = re.compile(r"^[ \t]+(?:[*!][ \t]+)?(?P<account>\S+)")


def _posts_to(block: str, accounts: frozenset[str]) -> bool:
    """True if any posting line in the block names one of accounts exactly."""
    for line in block.split("\n"):
        match = POSTING.match(line)
        if match and match.group("account") in accounts:
            return True
    return False


def comment_transactions(accounts, text: str) -> str:
    """Return text with any transaction posting to one of accounts commented out.

    Transactions are the blank-line separated blocks of text. A block is
    commented out, line for line, when one of its postings is to exactly one
    of the accounts. Everything else is passed through byte for byte.
    """
    accounts = frozenset(accounts)
    blocks = re.split(r"\n\n", text)
    result = []
    for block in blocks:
        if block.strip() and _posts_to(block, accounts):
            block = "\n".join(
                (";" + line) if line.strip() else line for line in block.split("\n")
            )
        result.append(block)
    return "\n\n".join(result)
