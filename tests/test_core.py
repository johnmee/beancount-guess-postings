import datetime
from pathlib import Path

from beancount.core import amount, data
from beancount.core.number import D
from click.testing import CliRunner

from beancount_guess_postings import build_key, fill, mimic
from beancount_guess_postings.cli import fill_cli
from beancount_guess_postings.core import best_match

DATA = Path(__file__).parent / "data"
TRAINING = str(DATA / "training.beancount")
INCOMING = str(DATA / "incoming.beancount")


def _entry(tags, postings, payee="Shop", narration="coffee"):
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


def _posting(account, number=None):
    units = amount.Amount(D(number), "AUD") if number else None
    return data.Posting(account, units, None, None, None, None)


def _new_and_past(new_tags, past_tags):
    new = _entry(new_tags, [_posting("Assets:Bank:Up", "-5.00")])
    past = _entry(
        past_tags,
        [_posting("Assets:Bank:Up", "-5.00"), _posting("Expenses:Food")],
    )
    return new, past


def test_fill_completes_a_matching_transaction(capsys):
    fill(TRAINING, INCOMING)
    out = capsys.readouterr().out
    # "Example Cafe" matches a past entry posting to Expenses:Food:Eatout, which
    # the incoming file lacks: proof the posting was copied.
    assert "Expenses:Food:Eatout" in out
    assert "Expenses:Transport:Public" in out


def test_fill_leaves_a_transaction_alone_when_nothing_like_it_was_seen_on_that_account(
    capsys,
):
    # The past "Widget Coffee Roasters" entry is on Bob's account, so it cannot
    # teach anything about Alice's.
    fill(TRAINING, INCOMING)
    out = capsys.readouterr().out
    widget = out.split("Widget Coffee Roasters")[1].split("\n\n")[0]
    assert "Expenses:Food:Coffee" not in widget


def test_fill_with_no_past_transactions_for_the_account_leaves_everything_alone(
    tmp_path, capsys
):
    # extractOne has nothing to choose from, and returns None.
    ledger = tmp_path / "empty.beancount"
    ledger.write_text("2025-01-01 open Assets:Bank:Alice-Everyday\n")
    fill(str(ledger), INCOMING)
    out = capsys.readouterr().out
    assert "EXAMPLE CAFE, SYDNEY" in out
    assert "Expenses" not in out


def test_fill_with_nothing_to_import_emits_a_marker_not_a_crash(tmp_path, capsys):
    # An import file with a balance directive but no transactions (say every row
    # was a duplicate the extractor commented out). It must stay valid beancount.
    incoming = tmp_path / "only-balance.beancount"
    incoming.write_text("2026-05-31 balance Assets:Bank:Saver  100.00 AUD\n")
    fill(TRAINING, str(incoming))
    out = capsys.readouterr().out
    assert "; Nothing to import." in out
    assert "balance Assets:Bank:Saver" in out


def test_best_match_scores_out_of_100_as_a_whole_number():
    found = best_match("Example Cafe -9.00 AUD", ["Example Cafe -9.00 AUD", "Other"])
    assert found == ("Example Cafe -9.00 AUD", 100)
    assert best_match("anything", []) is None


def test_equally_good_matches_go_to_the_earliest_key():
    keys = ["Shop coffee 1", "Shop coffee 2", "Shop coffee 3"]
    assert best_match("Shop coffee 9", keys)[0] == "Shop coffee 1"
    assert best_match("Shop coffee 9", keys[::-1])[0] == "Shop coffee 3"


def test_best_match_ignores_case():
    _, score = best_match("EXAMPLE CAFE -9.00 AUD", ["Example Cafe -9.00 AUD"])
    assert score == 100


def test_a_score_equal_to_the_threshold_is_not_good_enough(capsys, monkeypatch):
    monkeypatch.setattr(
        "beancount_guess_postings.core.best_match", lambda query, keys: (keys[0], 86)
    )
    fill(TRAINING, INCOMING, threshold=86)
    assert "Expenses:Food:Eatout" not in capsys.readouterr().out
    fill(TRAINING, INCOMING, threshold=85)
    assert "Expenses:Food" in capsys.readouterr().out


def test_build_key_summarises_payee_narration_and_amount():
    entry = _entry(set(), [_posting("Assets:Bank:Up", "-5.00")], "Shop", "coffee")
    assert build_key(entry) == "Shop coffee -5.00 AUD"
    entry = entry._replace(payee=None)
    assert build_key(entry) == "coffee -5.00 AUD"


def test_mimic_strips_the_named_tags_but_keeps_the_rest():
    new, past = _new_and_past({"alice", "keep"}, {"bob", "coffee"})
    assert mimic(new, past, strip_tags=["alice", "bob"]).tags == {"keep", "coffee"}


def test_mimic_keeps_every_tag_unless_told_to_strip_them():
    new, past = _new_and_past({"alice"}, {"bob"})
    assert mimic(new, past).tags == {"alice", "bob"}


def test_mimic_gives_the_copied_posting_no_amount_and_leaves_the_input_alone():
    new, past = _new_and_past(set(), set())
    result = mimic(new, past)
    assert [p.account for p in result.postings] == ["Assets:Bank:Up", "Expenses:Food"]
    assert result.postings[1].units is None
    assert len(new.postings) == 1


def test_cli_requires_a_training_ledger():
    result = CliRunner().invoke(fill_cli, [INCOMING])
    assert result.exit_code == 2
    assert "--training" in result.output


def test_cli_strips_the_tags_it_is_told_to():
    # The matched past entry is tagged #alice by its pushtag, as is the incoming
    # one; stripping removes it from the completed entry.
    kept = CliRunner().invoke(fill_cli, ["--training", TRAINING, INCOMING])
    stripped = CliRunner().invoke(
        fill_cli,
        [
            "--training",
            TRAINING,
            "--strip-tag",
            "#alice",
            "--strip-tag",
            "bob",
            INCOMING,
        ],
    )
    assert kept.exit_code == stripped.exit_code == 0

    def transit_line(output):
        return next(line for line in output.splitlines() if "Metro Transit" in line)

    assert transit_line(kept.output).endswith("#alice #bus")
    assert transit_line(stripped.output).endswith("#bus")
