"""Complete imported Beancount transactions by fuzzy-matching from your past ones."""

from importlib.metadata import PackageNotFoundError, version

from .core import (
    DEFAULT_THRESHOLD,
    LedgerWarning,
    ParseError,
    best_match,
    build_key,
    fill,
    mimic,
    render,
)

try:
    __version__ = version("beancount-guess-postings")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0+unknown"

__all__ = [
    "DEFAULT_THRESHOLD",
    "LedgerWarning",
    "ParseError",
    "__version__",
    "best_match",
    "build_key",
    "fill",
    "mimic",
    "render",
]
