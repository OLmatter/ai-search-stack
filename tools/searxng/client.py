"""Deprecated: use searxng_client instead."""

import warnings

warnings.warn(
    "tools/searxng/client.py is deprecated; import searxng_client instead.",
    DeprecationWarning,
    stacklevel=2,
)

from searxng_client import *  # noqa: E402,F401,F403
