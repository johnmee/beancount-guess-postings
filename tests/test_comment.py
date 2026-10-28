from click.testing import CliRunner

from beancount_guess_postings import comment_transactions
from beancount_guess_postings.cli import comment_cli

ACCOUNTS = ["Assets:Bank:Alice-Upbank", "Assets:Bank:Bob-Upbank"]

TRANSFER_ALICE = """\
2026-05-27 * "Up Alice" "Internet Withdrawal"
  Assets:Bank:Joint-Everyday  -350.00 AUD
  Assets:Bank:Alice-Upbank"""

TRANSFER_BOB = """\
2026-05-27 * "Up Bob" "Internet Withdrawal"
  Assets:Bank:Joint-Everyday  -350.00 AUD
  Assets:Bank:Bob-Upbank"""

UNRELATED = """\
2026-05-28 * "Streaming Co" "Visa Purchase"
  Assets:Bank:Joint-Everyday  -20.99 AUD
  Expenses:Technology"""


def commented(text):
    return "\n".join(";" + line for line in text.splitlines())


def test_comments_a_transfer_to_a_listed_account():
    assert comment_transactions(ACCOUNTS, TRANSFER_ALICE) == commented(TRANSFER_ALICE)
    assert comment_transactions(ACCOUNTS, TRANSFER_BOB) == commented(TRANSFER_BOB)


def test_leaves_unrelated_transactions_unchanged():
    assert comment_transactions(ACCOUNTS, UNRELATED) == UNRELATED


def test_comments_only_the_matching_transactions_in_mixed_input():
    text = f"{TRANSFER_ALICE}\n\n{UNRELATED}\n\n{TRANSFER_BOB}"
    expected = (
        f"{commented(TRANSFER_ALICE)}\n\n{UNRELATED}\n\n{commented(TRANSFER_BOB)}"
    )
    assert comment_transactions(ACCOUNTS, text) == expected


def test_no_accounts_matches_nothing():
    text = f"{TRANSFER_ALICE}\n\n{UNRELATED}"
    assert comment_transactions([], text) == text


def test_account_name_must_match_whole_not_as_a_prefix():
    text = """\
2026-05-27 * "Other" "Internet Withdrawal"
  Assets:Bank:Joint-Everyday  -350.00 AUD
  Assets:Bank:Alice-Upbank-Savings"""
    assert comment_transactions(ACCOUNTS, text) == text


def test_account_mentioned_in_narration_or_comment_does_not_count():
    text = """\
2026-05-27 * "Gift" "Paid back to Assets:Bank:Alice-Upbank"
  Assets:Bank:Joint-Everyday  -20.00 AUD  ; see Assets:Bank:Alice-Upbank
  Expenses:Gifts"""
    assert comment_transactions(ACCOUNTS, text) == text


def test_balance_directives_are_never_commented():
    text = "2026-05-27 balance Assets:Bank:Alice-Upbank  100.00 AUD"
    assert comment_transactions(ACCOUNTS, text) == text


def test_a_flagged_posting_still_matches():
    text = TRANSFER_ALICE.replace(
        "  Assets:Bank:Alice-Upbank", "  ! Assets:Bank:Alice-Upbank"
    )
    result = comment_transactions(ACCOUNTS, text)
    assert all(line.startswith(";") for line in result.splitlines())


def test_the_command_filters_standard_input():
    result = CliRunner().invoke(
        comment_cli, ACCOUNTS, input=f"{TRANSFER_ALICE}\n\n{UNRELATED}\n"
    )
    assert result.exit_code == 0
    assert result.output.startswith(";2026-05-27")
    assert UNRELATED in result.output
