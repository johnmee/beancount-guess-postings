"""Complete imported Beancount transactions by fuzzy-matching your past ones."""

from importlib.metadata import PackageNotFoundError, version

from .comment import comment_transactions
from .core import build_key, fill, mimic

try:
    __version__ = version("beancount-guess-postings")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0+unknown"

__all__ = ["__version__", "build_key", "comment_transactions", "fill", "mimic"]
