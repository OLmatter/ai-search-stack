"""Deprecated: use hackernews_client instead."""

import warnings

warnings.warn(
    "tools/hackernews/client.py is deprecated; import hackernews_client instead.",
    DeprecationWarning,
    stacklevel=2,
)

from hackernews_client import *  # noqa: E402,F401,F403
