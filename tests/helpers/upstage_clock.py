"""Opt-in price clock: import the fixture only in tests that need it."""

import pytest

from tests.helpers.price_clock import PriceDateTime


# Patch only Upstage's price clock; authorization, budget and lease clocks stay real.
@pytest.fixture(autouse=True)
def _freeze_upstage_price_clock(monkeypatch):
    monkeypatch.setattr("proofops.adapters.local.upstage.datetime", PriceDateTime)
