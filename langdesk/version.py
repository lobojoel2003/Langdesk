"""Single source of truth for the Langdesk version.

Release tags (``vX.Y.Z``) must match ``__version__``; the release workflow checks this.
Build metadata is injected at image build time through environment variables.
"""

import os

__version__ = "1.0.0"


def build_info() -> dict[str, str]:
    """Return version and build metadata for display and the health endpoint."""
    commit = os.environ.get("LANGDESK_GIT_SHA", "")
    return {
        "version": __version__,
        "build": os.environ.get("LANGDESK_BUILD_NUMBER", "dev"),
        "commit": commit[:7],
        "built_at": os.environ.get("LANGDESK_BUILD_DATE", ""),
    }
