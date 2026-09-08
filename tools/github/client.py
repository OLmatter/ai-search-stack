"""Deprecated: use github_client instead."""

import warnings

warnings.warn(
    "tools/github/client.py is deprecated; import github_client instead.",
    DeprecationWarning,
    stacklevel=2,
)

from github_client import *  # noqa: E402,F401,F403
