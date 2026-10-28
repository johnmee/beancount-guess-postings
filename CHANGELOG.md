# Changelog

## 0.1.0

First release, extracted from `aussie-bean-tools`.

- `guess-postings` completes imported transactions from similar past ones.
- `guess-postings-comment` comments out transactions another ledger already records.
- Matching moved from `fuzzywuzzy` to `rapidfuzz`.
- Does not crash when the ledger has no past transactions for the account.
