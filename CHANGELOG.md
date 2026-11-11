# Changelog

## 0.1.0

First release, extracted from `aussie-bean-tools`.

- `guess-postings` completes imported transactions by copying the postings and
  tags of the most similar past transaction on the same account.
- Each transaction is matched against the account of its own first posting, so
  one import file may cover several accounts.
- The ledger is named with `--ledger` (or `-l`), or the `BEANCOUNT_FILE`
  environment variable.
- `--mute ACCOUNT` comments out transactions that, once completed, post to that
  account. Repeatable.
- `--strip-tag TAG` leaves a tag off the completed entries. Repeatable.
- A split copied from a past transaction keeps its amounts; the amount from the
  bank is never altered.
- An import file that is not valid Beancount fails with its errors on standard
  error and exit status 1. Errors in the ledger draw a one-line warning.
- Fully typed, with a `py.typed` marker.
