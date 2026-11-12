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

$ guess-postings --ledger main.beancount /tmp/new.beancount
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

Python 3.11 or newer, and Beancount 3. For the [beangulp hook](#as-a-beangulp-hook),
install the `beangulp` extra, which brings beangulp 0.2 or later:

```
pip install 'beancount-guess-postings[beangulp]'
```

## `guess-postings`

```
Usage: guess-postings [OPTIONS] INFILE

  Complete the postings of the transactions in INFILE.

  Each transaction is fuzzy-matched against the transactions in the ledger
  that post to the same account, and the postings and tags of the best match
  are copied across. The result goes to standard output.

Options:
  -l, --ledger PATH    Beancount file whose past transactions the guesses are
                       copied from; usually your main ledger.  [env var:
                       BEANCOUNT_FILE; required]
  --threshold INTEGER  Only use fuzz scores better than this, out of 100.
                       Lower the number to fill in more matches with less
                       confident guesses.  [default: 86; 0<=x<=100]
  --strip-tag TAG      Leave this tag off completed entries, even if the
                       matched past transaction has it. Repeatable. Useful
                       when a pushtag in the ledger file already applies the
                       tag.
  --version            Show the version and exit.
  -h, --help           Show this message and exit.
```

### Naming your ledger

Pass it with `--ledger` (or `-l`), or set `BEANCOUNT_FILE`, the same variable
[Fava](https://beancount.github.io/fava/) reads:

```
$ export BEANCOUNT_FILE=~/finance/main.beancount
$ guess-postings /tmp/new.beancount
```

`--ledger` wins when both are given. Fava lets `BEANCOUNT_FILE` list several
files; `guess-postings` learns from one, so in that case name it with
`--ledger`.

How it decides:

- A new transaction belongs to the account of its **first posting**, the side
  your importer wrote. It learns only from past transactions that post to that
  same account and have more than one posting. `INFILE` may mix accounts; each
  transaction is matched against its own.
- Each is summarised as `payee narration amount`, the amount being the one
  posted to that account. A new transaction is compared
  with those summaries, and the postings and tags of the best match are copied
  across. When the same summary occurs more than once, the most recent wins.
- A match must score **above `--threshold`** (out of 100) to be used. Raise it to
  be more cautious; lower it to complete more.
- If `INFILE` has no transactions at all (say every row was a duplicate), the
  output is whatever else was in the file, such as `balance` directives, and
  nothing at all if there was nothing else. Comments in `INFILE`, such as the
  duplicates beangulp commented out, are not kept: use the beangulp hook below
  if you want them.
- If `INFILE` is not valid Beancount, the errors go to standard error, nothing
  is output, and the exit status is 1. Errors in the ledger only draw a
  one-line warning.

### Splits are copied as they were

The amount from your bank is never altered. When the matched past transaction
had one other posting, that posting is copied without an amount, so Beancount
balances it for you. When it was split across several, their amounts are copied
exactly as they were:

```
; in your ledger
2026-02-03 * "Example Grocer" "EXAMPLE GROCER SYDNEY"
  Assets:Bank:Everyday  -90.00 AUD
  Expenses:Food:Groceries  70.00 AUD
  Expenses:Household       20.00 AUD

; completed from it
2026-03-02 * "Example Grocer" "EXAMPLE GROCER SYDNEY"
  Assets:Bank:Everyday  -120.00 AUD
  Expenses:Food:Groceries  70.00 AUD
  Expenses:Household       20.00 AUD
```

If the new amount differs, as here, the transaction does not balance. That is
deliberate: Beancount reports it, which is your prompt to adjust the split.

### Tags and `--strip-tag`

If your ledger files open with `pushtag #alice`, every past transaction in them
carries `#alice`. Copying that onto a new entry that will itself be written
inside the same `pushtag` would repeat the tag. Name it with `--strip-tag alice`
(a leading `#` is fine) and it is left off the completed entries.

## As a beangulp hook

`guess-postings` reads beangulp's printed output back in, which loses its
comments, including the `; duplicate of` rows. Run as a beangulp import hook
instead, it completes the entries before beangulp prints them, so the
duplicates are completed too and still come out commented:

```python
from beangulp import Ingest
from beancount_guess_postings import hook

Ingest(
    [MyBankImporter("Assets:Bank:Joint")],
    hooks=[hook(threshold=86, strip_tags=["alice"], mute=["Assets:Bank:Alice-Upbank"])],
)()
```

```
python import.py extract -e main.beancount statement.csv >> joint-2026.beancount
```

It learns from the ledger given to `extract -e`, so pass one. It learns only
from that ledger, never from the other entries being imported. It needs
beangulp 0.2 or later, which marks duplicates before it runs the hooks.

### Muting transfers with `mute`

A transfer between two of your accounts shows up in both banks' downloads, but
it should be booked once. `mute` names the accounts whose own files book it. A
transaction that, **once its postings have been guessed**, posts to one of them
is marked as a duplicate, so beangulp prints it commented out: it stays in the
file for reference but beancount ignores it. That works whichever bank you
import first. If the other bank's file already has it, beangulp has marked it a
duplicate already.

The account has to match exactly: `Assets:Bank:Up` does not match
`Assets:Bank:Up-Savings`. A mention in a narration never matches, and `balance`
directives are never marked. A transfer whose guess falls below the threshold is
not muted. It comes out with only its one posting, which `bean-check` reports.

## From Python

```python
from beancount_guess_postings import fill, render

entries = fill(
    "main.beancount",
    "/tmp/new.beancount",
    threshold=86,
    strip_tags=["alice"],
)
text = render(entries)
```

- `fill` returns every directive of the file, in order, as Beancount entries,
  with the transactions that found a match completed. It prints nothing.
- `render` turns entries into Beancount text.
- `complete(importing, existing, ...)` does what `fill` does, but on entries
  already in memory. `hook(...)` wraps it for beangulp (see above).
- `fill` raises `ParseError` if the file to complete is not valid Beancount,
  and issues a `LedgerWarning` if the ledger has errors.
- `mimic`, `best_match` and `build_key` are the steps `fill` is built from.

## Development

```
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

The package is fully typed and ships a `py.typed` marker.

## Licence

GPL-2.0-only, the same as Beancount. See
[LICENSE](https://github.com/johnmee/beancount-guess-postings/blob/main/LICENSE).
