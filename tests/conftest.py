"""Explicit test bundles and isolated offline price clocks; no test exclusions added."""

import json
import os
from pathlib import Path

import pytest

from tests.helpers.price_clock import child_pythonpath, install_price_clock

CATALOG = json.loads(Path(__file__).with_name("suite_markers.json").read_text())


@pytest.fixture(scope="session", autouse=True)
def offline_price_clock():
    # Include module-scoped publication fixtures as well as hosted subprocesses.
    # Restore on session exit; individual tests' explicit expiry overrides still win.
    with pytest.MonkeyPatch.context() as patch:
        install_price_clock(
            lambda module, name, value: patch.setattr(module, name, value, raising=False)
        )
        patch.setenv("PYTHONPATH", child_pythonpath(os.environ.get("PYTHONPATH", "")))
        yield patch


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
