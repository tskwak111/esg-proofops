"""Explicit test bundles: markers only; no skip, deletion, or assertion rewriting."""

import json
from pathlib import Path

import pytest

CATALOG = json.loads(Path(__file__).with_name("suite_markers.json").read_text())


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    safety = {selector for group in CATALOG["core_safety"].values() for selector in group}
    for item in items:
        # Function selectors cover every parameter; a file selector covers its tests.
        selectors = {item.nodeid.split("::", 1)[0], item.nodeid.split("[", 1)[0]}
        for marker in ("legacy_pin", "slow"):
            if selectors.intersection(CATALOG[marker]):
                item.add_marker(getattr(pytest.mark, marker))
        if selectors.intersection(safety) and any(
            item.get_closest_marker(marker) for marker in ("legacy_pin", "slow")
        ):
            raise pytest.UsageError(f"Core safety test cannot be excluded: {item.nodeid}")
