import datetime
import os
from collections.abc import Iterable
from importlib.metadata import entry_points
from pathlib import Path

import pytest
from beancount.core import amount, data
from beancount.core.number import D
from click.testing import CliRunner

from beancount_guess_postings import (
    DEFAULT_THRESHOLD,
    LedgerWarning,
    ParseError,
    __version__,
    best_match,
    build_key,
    fill,
    mimic,
    render,
)
from beancount_guess_postings.cli import fill_cli

DATA = Path(__file__).parent / "data"
TRAINING = str(DATA / "training.beancount")
INCOMING = str(DATA / "incoming.beancount")


def _filled(
    ledger: str,
    infile: str,
    threshold: int = DEFAULT_THRESHOLD,
    mute: str | Iterable[str] = (),
) -> str:
    """The completed import as text, the way the command writes it."""
    return render(fill(ledger, infile, threshold), mute)


def _entry(
    tags: Iterable[str],
    postings: list[data.Posting],
    payee: str | None = "Shop",
    narration: str = "coffee",
) -> data.Transaction:
    return data.Transaction(
        data.new_metadata("t", 0),
        datetime.date(2025, 1, 1),
        "*",
        payee,
        narration,
        frozenset(tags),
        data.EMPTY_SET,
        postings,
    )


def _posting(account: str, number: str | None = None) -> data.Posting:
    units = amount.Amount(D(number), "AUD") if number else None
    return data.Posting(account, units, None, None, None, None)


def _new_and_past(
    new_tags: Iterable[str], past_tags: Iterable[str]
) -> tuple[data.Transaction, data.Transaction]:
    new = _entry(new_tags, [_posting("Assets:Bank:Up", "-5.00")])
    past = _entry(
        past_tags,
        [_posting("Assets:Bank:Up", "-5.00"), _posting("Expenses:Food")],
    )
    return new, past


def _best(query: str, keys: list[str]) -> tuple[str, int]:
    found = best_match(query, keys)
    assert found is not None
    return found


def test_fill_completes_a_matching_transaction() -> None:
    out = _filled(TRAINING, INCOMING)
    # "Example Cafe" matches a past entry posting to Expenses:Food:Eatout, which
    # the incoming file lacks: proof the posting was copied.
    assert "Expenses:Food:Eatout" in out
    assert "Expenses:Transport:Public" in out


def test_fill_leaves_alone_a_transaction_seen_only_on_another_account() -> None:
    # The past "Widget Coffee Roasters" entry is on Bob's account, so it cannot
    # teach anything about Alice's.
    out = _filled(TRAINING, INCOMING)
    widget = out.split("Widget Coffee Roasters")[1].split("\n\n")[0]
    assert "Expenses:Food:Coffee" not in widget


def test_fill_with_no_past_transactions_for_the_account_leaves_everything_alone(
    tmp_path: Path,
) -> None:
    # There is nothing to choose a best match from.
    ledger = tmp_path / "empty.beancount"
    ledger.write_text("2025-01-01 open Assets:Bank:Alice-Everyday\n")
    out = _filled(str(ledger), INCOMING)
    assert "EXAMPLE CAFE, SYDNEY" in out
    assert "Expenses" not in out


def test_fill_with_nothing_to_import_passes_the_rest_through(tmp_path: Path) -> None:
    # An import file with a balance directive but no transactions (say every row
    # was a duplicate the extractor commented out). Only the balance comes out.
    incoming = tmp_path / "only-balance.beancount"
    incoming.write_text("2026-05-31 balance Assets:Bank:Saver  100.00 AUD\n")
    out = _filled(TRAINING, str(incoming))
    assert out.split() == [
        "2026-05-31",
        "balance",
        "Assets:Bank:Saver",
        "100.00",
        "AUD",
    ]


def test_fill_with_an_empty_import_gives_nothing(tmp_path: Path) -> None:
    incoming = tmp_path / "empty.beancount"
    incoming.write_text(";; -*- mode: beancount -*-\n")
    assert fill(TRAINING, str(incoming)) == []
    assert _filled(TRAINING, str(incoming)) == ""


def test_fill_returns_every_directive_in_order_and_prints_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    entries = fill(TRAINING, INCOMING)
    assert [type(entry).__name__ for entry in entries] == [
        *["Transaction"] * 5,
        "Balance",
    ]
    cafe = entries[0]
    assert isinstance(cafe, data.Transaction)
    assert [p.account for p in cafe.postings] == [
        "Assets:Bank:Alice-Everyday",
        "Expenses:Food:Eatout",
    ]
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_render_ends_each_entry_with_a_blank_line() -> None:
    new, _ = _new_and_past(set(), set())
    assert render([new, new]) == (
        '2025-01-01 * "Shop" "coffee"\n  Assets:Bank:Up  -5.00 AUD\n\n' * 2
    )
    assert render([]) == ""


def test_best_match_scores_out_of_100_as_a_whole_number() -> None:
    found = best_match("Example Cafe -9.00 AUD", ["Example Cafe -9.00 AUD", "Other"])
    assert found == ("Example Cafe -9.00 AUD", 100)
    assert best_match("anything", []) is None


def test_equally_good_matches_go_to_the_earliest_key() -> None:
    keys = ["Shop coffee 1", "Shop coffee 2", "Shop coffee 3"]
    assert _best("Shop coffee 9", keys)[0] == "Shop coffee 1"
    assert _best("Shop coffee 9", keys[::-1])[0] == "Shop coffee 3"


def test_best_match_ignores_case() -> None:
    _, score = _best("EXAMPLE CAFE -9.00 AUD", ["Example Cafe -9.00 AUD"])
    assert score == 100


def test_a_score_equal_to_the_threshold_is_not_good_enough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "beancount_guess_postings.core.best_match", lambda query, keys: (keys[0], 86)
    )
    untouched = _filled(TRAINING, INCOMING, threshold=100)
    assert _filled(TRAINING, INCOMING, threshold=86) == untouched
    assert _filled(TRAINING, INCOMING, threshold=85) != untouched


def test_build_key_summarises_payee_narration_and_amount() -> None:
    entry = _entry(set(), [_posting("Assets:Bank:Up", "-5.00")], "Shop", "coffee")
    assert build_key(entry) == "Shop coffee -5.00 AUD"
    entry = entry._replace(payee=None)
    assert build_key(entry) == "coffee -5.00 AUD"


def test_mimic_strips_the_named_tags_but_keeps_the_rest() -> None:
    new, past = _new_and_past({"alice", "keep"}, {"bob", "coffee"})
    assert mimic(new, past, strip_tags=["alice", "bob"]).tags == {"keep", "coffee"}


def test_mimic_keeps_every_tag_unless_told_to_strip_them() -> None:
    new, past = _new_and_past({"alice"}, {"bob"})
    assert mimic(new, past).tags == {"alice", "bob"}


def test_mimic_gives_the_copied_posting_no_amount_and_leaves_the_input_alone() -> None:
    new, past = _new_and_past(set(), set())
    result = mimic(new, past)
    assert [p.account for p in result.postings] == ["Assets:Bank:Up", "Expenses:Food"]
    assert result.postings[1].units is None
    assert len(new.postings) == 1


@pytest.fixture(autouse=True)
def no_ledger_in_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # The developer's own BEANCOUNT_FILE must not leak into the tests.
    monkeypatch.delenv("BEANCOUNT_FILE", raising=False)


def test_cli_requires_a_ledger() -> None:
    result = CliRunner().invoke(fill_cli, [INCOMING])
    assert result.exit_code == 2
    assert "--ledger" in result.output


def test_cli_takes_the_ledger_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BEANCOUNT_FILE", TRAINING)
    result = CliRunner().invoke(fill_cli, [INCOMING])
    assert result.exit_code == 0
    assert "Expenses:Food:Eatout" in result.output


def test_cli_prefers_the_ledger_option_to_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    empty = tmp_path / "empty.beancount"
    empty.write_text("")
    monkeypatch.setenv("BEANCOUNT_FILE", str(empty))
    result = CliRunner().invoke(fill_cli, ["-l", TRAINING, INCOMING])
    assert result.exit_code == 0
    assert "Expenses:Food:Eatout" in result.output


def test_cli_rejects_an_environment_that_names_several_ledgers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BEANCOUNT_FILE", os.pathsep.join([TRAINING, TRAINING]))
    result = CliRunner().invoke(fill_cli, [INCOMING])
    assert result.exit_code == 2
    assert "more than one file" in result.output


def _blocks(output: str) -> dict[str, list[str]]:
    """The blank-line separated entries of some output, keyed by first line."""
    blocks = [block for block in output.split("\n\n") if block.strip()]
    return {block.splitlines()[0]: block.splitlines() for block in blocks}


def _is_commented(lines: list[str]) -> bool:
    return all(line.startswith(";") for line in lines)


def test_render_mutes_transactions_that_post_to_a_muted_account() -> None:
    # The account is not in the import file: it arrives with the guess.
    blocks = _blocks(_filled(TRAINING, INCOMING, mute=["Expenses:Food:Eatout"]))
    cafe = next(lines for first, lines in blocks.items() if "Example Cafe" in first)
    transit = next(lines for first, lines in blocks.items() if "Metro Transit" in first)
    assert _is_commented(cafe)
    assert any("Expenses:Food:Eatout" in line for line in cafe)
    assert not any(line.startswith(";") for line in transit)


def test_render_mutes_only_an_account_named_in_full() -> None:
    entries = fill(TRAINING, INCOMING)
    muted = render(entries, mute=["Expenses:Food", "Expenses:Food:Eat"])
    assert muted == render(entries)


def test_render_never_mutes_a_balance_directive() -> None:
    blocks = _blocks(_filled(TRAINING, INCOMING, mute=["Assets:Bank:Alice-Everyday"]))
    balances = [lines for first, lines in blocks.items() if " balance " in first]
    transactions = [
        lines for first, lines in blocks.items() if " balance " not in first
    ]
    assert balances
    assert not any(_is_commented(lines) for lines in balances)
    assert transactions
    assert all(_is_commented(lines) for lines in transactions)


def test_cli_mutes_each_account_it_is_given() -> None:
    result = CliRunner().invoke(
        fill_cli,
        [
            "--ledger",
            TRAINING,
            "--mute",
            "Expenses:Food:Eatout",
            "--mute",
            "Expenses:Transport:Public",
            INCOMING,
        ],
    )
    assert result.exit_code == 0
    commented = [line for line in result.output.splitlines() if line.startswith(";")]
    assert any("Expenses:Food:Eatout" in line for line in commented)
    assert any("Expenses:Transport:Public" in line for line in commented)
    assert not any("Expenses:Food:Alcohol" in line for line in commented)


def test_cli_strips_the_tags_it_is_told_to() -> None:
    # The matched past entry is tagged #alice by its pushtag, as is the incoming
    # one; stripping removes it from the completed entry.
    kept = CliRunner().invoke(fill_cli, ["--ledger", TRAINING, INCOMING])
    stripped = CliRunner().invoke(
        fill_cli,
        [
            "--ledger",
            TRAINING,
            "--strip-tag",
            "#alice",
            "--strip-tag",
            "bob",
            INCOMING,
        ],
    )
    assert kept.exit_code == stripped.exit_code == 0

    def transit_line(output: str) -> str:
        return next(line for line in output.splitlines() if "Metro Transit" in line)

    assert transit_line(kept.output).endswith("#alice #bus")
    assert transit_line(stripped.output).endswith("#bus")


def test_cli_completes_a_matching_transaction() -> None:
    result = CliRunner().invoke(fill_cli, ["--ledger", TRAINING, INCOMING])
    assert result.exit_code == 0
    assert "Expenses:Food:Eatout" in result.output


def test_cli_with_the_highest_threshold_completes_nothing() -> None:
    result = CliRunner().invoke(
        fill_cli, ["--ledger", TRAINING, "--threshold", "100", INCOMING]
    )
    assert result.exit_code == 0
    assert "Expenses:" not in result.output
    assert "Example Cafe" in result.output


def test_cli_rejects_a_threshold_that_is_not_a_whole_number() -> None:
    result = CliRunner().invoke(
        fill_cli, ["--ledger", TRAINING, "--threshold", "high", INCOMING]
    )
    assert result.exit_code == 2
    assert "--threshold" in result.output


def test_cli_rejects_a_training_ledger_that_does_not_exist(tmp_path: Path) -> None:
    missing = str(tmp_path / "missing.beancount")
    result = CliRunner().invoke(fill_cli, ["--ledger", missing, INCOMING])
    assert result.exit_code == 2
    assert "--ledger" in result.output


def test_cli_rejects_an_import_file_that_does_not_exist(tmp_path: Path) -> None:
    missing = str(tmp_path / "missing.beancount")
    result = CliRunner().invoke(fill_cli, ["--ledger", TRAINING, missing])
    assert result.exit_code == 2
    assert "INFILE" in result.output


def test_cli_requires_an_import_file() -> None:
    result = CliRunner().invoke(fill_cli, ["--ledger", TRAINING])
    assert result.exit_code == 2
    assert "INFILE" in result.output


def test_cli_help_names_the_command() -> None:
    result = CliRunner().invoke(fill_cli, ["--help"], prog_name=fill_cli.name)
    assert result.exit_code == 0
    assert "Usage: guess-postings [OPTIONS] INFILE" in result.output


def test_the_commands_are_installed_under_their_names() -> None:
    scripts = {
        ep.name: ep.value
        for ep in entry_points(group="console_scripts")
        if ep.value.startswith("beancount_guess_postings.")
    }
    assert scripts == {"guess-postings": "beancount_guess_postings.cli:fill_cli"}


def test_mimic_copies_the_amounts_of_a_split_even_when_they_no_longer_balance() -> None:
    # The bank's amount is never altered. A split copied from a past
    # transaction of a different size is left unbalanced for the user to fix.
    new = _entry(set(), [_posting("Assets:Bank:Up", "-12.00")])
    past = _entry(
        set(),
        [
            _posting("Assets:Bank:Up", "-9.00"),
            _posting("Expenses:Food", "5.00"),
            _posting("Expenses:Drinks", "4.00"),
        ],
    )
    result = mimic(new, past)
    assert [(p.account, str(p.units)) for p in result.postings] == [
        ("Assets:Bank:Up", "-12.00 AUD"),
        ("Expenses:Food", "5.00 AUD"),
        ("Expenses:Drinks", "4.00 AUD"),
    ]


def test_build_key_copes_without_an_amount_or_any_postings() -> None:
    entry = _entry(set(), [_posting("Assets:Bank:Up")], "Shop", "coffee")
    assert build_key(entry) == "Shop coffee"
    assert build_key(entry._replace(postings=[])) == "Shop coffee"


def test_fill_passes_a_transaction_with_no_postings_through(tmp_path: Path) -> None:
    incoming = tmp_path / "no-postings.beancount"
    incoming.write_text(
        '2025-01-01 * "Mystery" "NO POSTINGS"\n'
        "\n"
        '2025-01-02 * "Example Cafe" "EXAMPLE CAFE, SYDNEY"\n'
        "  Assets:Bank:Alice-Everyday  -9.00 AUD\n"
    )
    out = _filled(TRAINING, str(incoming))
    assert '"Mystery" "NO POSTINGS"' in out
    assert "Expenses:Food:Eatout" in out


def test_fill_refuses_an_import_file_it_cannot_parse(tmp_path: Path) -> None:
    incoming = tmp_path / "broken.beancount"
    incoming.write_text(
        '2025-01-02 * "Example Cafe" "EXAMPLE CAFE, SYDNEY"\n'
        "  Assets:Bank:Alice-Everyday  -9.00 AUD\n"
        "\n"
        "this line is not beancount\n"
    )
    with pytest.raises(ParseError) as raised:
        fill(TRAINING, str(incoming))
    assert raised.value.errors
    assert raised.value.filename == str(incoming)


def test_fill_warns_about_errors_in_the_ledger_and_learns_from_it_anyway(
    tmp_path: Path,
) -> None:
    training = tmp_path / "training.beancount"
    training.write_text(
        "2020-01-01 open Assets:Bank:Alice-Everyday\n"
        "2020-01-01 open Expenses:Food:Eatout\n"
        "\n"
        '2025-01-02 * "Example Cafe" "EXAMPLE CAFE, SYDNEY"\n'
        "  Assets:Bank:Alice-Everyday  -9.00 AUD\n"
        "  Expenses:Food:Eatout\n"
    )
    # A clean ledger warns of nothing: the suite turns any warning into an error.
    assert "Expenses:Food:Eatout" in _filled(str(training), INCOMING)

    training.write_text(training.read_text() + "\nthis line is not beancount\n")
    with pytest.warns(LedgerWarning, match="run bean-check") as caught:
        out = _filled(str(training), INCOMING)
    assert str(training) in str(caught[0].message)
    assert "Expenses:Food:Eatout" in out


def test_cli_keeps_a_ledger_warning_out_of_the_completed_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = tmp_path / "ledger.beancount"
    ledger.write_text(Path(TRAINING).read_text() + "\nthis line is not beancount\n")
    # Run without CliRunner, which older versions of click cannot make keep the
    # two streams apart.
    fill_cli.main(["--ledger", str(ledger), INCOMING], standalone_mode=False)
    captured = capsys.readouterr()
    assert captured.err.startswith("warning: ")
    assert "run bean-check" in captured.err
    assert "Expenses:Food:Eatout" in captured.out
    assert "warning" not in captured.out


def test_cli_fails_on_an_import_file_it_cannot_parse(tmp_path: Path) -> None:
    incoming = tmp_path / "broken.beancount"
    incoming.write_text("this line is not beancount\n")
    result = CliRunner().invoke(fill_cli, ["--ledger", TRAINING, str(incoming)])
    assert result.exit_code == 1
    assert "broken.beancount" in result.output


def test_build_key_can_take_the_amount_from_a_named_account() -> None:
    entry = _entry(
        set(),
        [_posting("Expenses:Food", "5.00"), _posting("Assets:Bank:Up", "-5.00")],
    )
    assert build_key(entry) == "Shop coffee 5.00 AUD"
    assert build_key(entry, "Assets:Bank:Up") == "Shop coffee -5.00 AUD"
    assert build_key(entry, "Assets:Bank:Other") == "Shop coffee"


def test_mimic_takes_a_lone_tag_as_one_tag_not_its_letters() -> None:
    new, past = _new_and_past({"alice", "a"}, {"bob"})
    assert mimic(new, past, strip_tags="alice").tags == {"a", "bob"}


def test_render_takes_a_lone_account_to_mute_as_one_account() -> None:
    blocks = _blocks(_filled(TRAINING, INCOMING, mute="Expenses:Food:Eatout"))
    cafe = next(lines for first, lines in blocks.items() if "Example Cafe" in first)
    assert _is_commented(cafe)


@pytest.mark.parametrize("threshold", [-1, 101])
def test_fill_rejects_a_threshold_outside_0_to_100(threshold: int) -> None:
    with pytest.raises(ValueError, match="0 to 100"):
        fill(TRAINING, INCOMING, threshold=threshold)


LEDGER_OF_TWO_ACCOUNTS = """\
2020-01-01 open Assets:Bank:Everyday
2020-01-01 open Assets:Bank:Card
2020-01-01 open Expenses:Food:Coffee
2020-01-01 open Expenses:Travel

; The expense is listed first: the match is still made on the bank's side.
2025-01-02 * "Example Cafe" "EXAMPLE CAFE, SYDNEY"
  Expenses:Food:Coffee   6.50 AUD
  Assets:Bank:Everyday  -6.50 AUD

2025-01-03 * "Example Airline" "EXAMPLE AIRLINE, SYDNEY"
  Assets:Bank:Card  -300.00 AUD
  Expenses:Travel
"""


def test_fill_matches_each_transaction_against_its_own_account(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.beancount"
    ledger.write_text(LEDGER_OF_TWO_ACCOUNTS)
    incoming = tmp_path / "incoming.beancount"
    incoming.write_text(
        '2025-02-02 * "Example Cafe" "EXAMPLE CAFE, SYDNEY"\n'
        "  Assets:Bank:Everyday  -6.50 AUD\n"
        "\n"
        '2025-02-03 * "Example Airline" "EXAMPLE AIRLINE, SYDNEY"\n'
        "  Assets:Bank:Card  -300.00 AUD\n"
        "\n"
        # Seen before, but only on the other account: nothing to learn from.
        '2025-02-04 * "Example Airline" "EXAMPLE AIRLINE, SYDNEY"\n'
        "  Assets:Bank:Everyday  -300.00 AUD\n"
    )
    out = _filled(str(ledger), str(incoming))
    blocks = {first[:10]: lines for first, lines in _blocks(out).items()}
    assert any("Expenses:Food:Coffee" in line for line in blocks["2025-02-02"])
    assert any("Expenses:Travel" in line for line in blocks["2025-02-03"])
    assert len(blocks["2025-02-04"]) == 2


@pytest.mark.parametrize("threshold", ["-1", "101"])
def test_cli_rejects_a_threshold_outside_0_to_100(threshold: str) -> None:
    result = CliRunner().invoke(
        fill_cli, ["--ledger", TRAINING, "--threshold", threshold, INCOMING]
    )
    assert result.exit_code == 2
    assert "--threshold" in result.output


def test_cli_rejects_a_directory_as_the_ledger(tmp_path: Path) -> None:
    result = CliRunner().invoke(fill_cli, ["--ledger", str(tmp_path), INCOMING])
    assert result.exit_code == 2
    assert "--ledger" in result.output


def test_cli_rejects_a_directory_as_the_import_file(tmp_path: Path) -> None:
    result = CliRunner().invoke(fill_cli, ["--ledger", TRAINING, str(tmp_path)])
    assert result.exit_code == 2
    assert "INFILE" in result.output


def test_cli_reports_its_version() -> None:
    result = CliRunner().invoke(fill_cli, ["--version"], prog_name=fill_cli.name)
    assert result.exit_code == 0
    assert result.output.strip() == f"guess-postings, version {__version__}"


def test_cli_answers_to_a_short_help_option() -> None:
    result = CliRunner().invoke(fill_cli, ["-h"], prog_name=fill_cli.name)
    assert result.exit_code == 0
    assert "Usage: guess-postings [OPTIONS] INFILE" in result.output
