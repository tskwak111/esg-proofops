"""Loaded only when an offline test adds this directory to its child's PYTHONPATH."""

import sys
from pathlib import Path

# Children can run from temporary workspaces rather than the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.helpers.price_clock import install_child_price_clock  # noqa: E402

install_child_price_clock()
