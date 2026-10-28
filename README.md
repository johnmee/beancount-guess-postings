# beancount-guess-postings

[Beancount](https://beancount.github.io/) importers give you a transaction with
one posting: the bank account's side. You then add the other side by hand, over
and over, for the same coffee shop and the same electricity bill.

`guess-postings` does that for you. It looks at the transactions already in your
ledger, finds the one most like each new transaction, and copies its postings
and tags across. Anything it is not confident about is left exactly as it was.

```
$ cat /tmp/new.beancount
2026-03-02 * "Example Cafe" "EXAMPLE CAFE SYDNEY"
  Assets:Bank:Everyday  -6.50 AUD

$ guess-postings --training main.beancount /tmp/new.beancount
2026-03-02 * "Example Cafe" "EXAMPLE CAFE SYDNEY"
  Assets:Bank:Everyday  -6.50 AUD
  Expenses:Food:Coffee
```

It works with the output of any importer, and was written alongside
[`beancount-upbank`](https://github.com/johnmee/beancount-upbank) and
[`beancount-stgeorge`](https://github.com/johnmee/beancount-stgeorge).

## Install

```
pip install beancount-guess-postings
```

Python 3.10 or newer, and Beancount 3.

## `guess-postings`

```
Usage: guess-postings [OPTIONS] INFILE

  Complete the postings of the transactions in INFILE.

Options:
  --threshold INTEGER  Only use fuzz scores better than this.  [default: 86]
  --training PATH      Beancount file to use as a template for predictions;
                       usually your main ledger.  [required]
  --strip-tag TEXT     Leave this tag off completed entries, even if the
                       matched past transaction has it. Repeatable.
  --help               Show this message and exit.
```

How it decides:

- It learns only from past transactions that post to **the same account** as
  the first transaction in `INFILE`, and that have more than one posting.
- Each is summarised as `payee narration amount`. A new transaction is compared
  with those summaries, and the postings and tags of the best match are copied
  across. When the same summary occurs more than once, the most recent wins.
- A match must score **above `--threshold`** (out of 100) to be used. Raise it to
  be more cautious; lower it to complete more.
- If `INFILE` has no transactions at all (say every row was a duplicate), the
  output is the comment `; Nothing to import.` followed by whatever else was in
  the file, so it is still safe to append to a ledger.

### Tags and `--strip-tag`

If your ledger files open with `pushtag #alice`, every past transaction in them
carries `#alice`. Copying that onto a new entry that will itself be written
inside the same `pushtag` would repeat the tag. Name it with `--strip-tag alice`
(a leading `#` is fine) and it is left off the completed entries.

## `guess-postings-comment`

Silences transactions that another account's ledger already records.

When you import a joint account, a transfer from a personal account appears in
both feeds. If the personal account's import already recorded it, the joint
account's copy would double-count it. `guess-postings-comment` prefixes those
transactions with `;`, so they stay in the file for reference but Beancount
ignores them.

```
guess-postings --training main.beancount /tmp/joint.beancount \
    | guess-postings-comment Assets:Bank:Alice-Upbank Assets:Bank:Bob-Upbank \
    >> joint-2026.beancount
```

A transaction is commented out when one of its **posting lines** names one of
the given accounts exactly. `Assets:Bank:Up` does not match
`Assets:Bank:Up-Savings`; a mention in a narration or comment never matches; and
`balance` directives are never touched.

## From Python

```python
from beancount_guess_postings import comment_transactions, fill

fill("main.beancount", "/tmp/new.beancount", threshold=86, strip_tags=["alice"])
text = comment_transactions(["Assets:Bank:Alice-Upbank"], open("x.beancount").read())
```

## Development

```
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Licence

MIT. See [LICENSE](LICENSE).
