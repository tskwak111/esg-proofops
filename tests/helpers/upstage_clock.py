"""Opt-in price clock: import the fixture only in tests that need it."""

from datetime import UTC as _UTC
from datetime import datetime as _RealDatetime

import pytest


# Patch only Upstage's price clock; authorization, budget and lease clocks stay real.
@pytest.fixture(autouse=True)
def _freeze_upstage_price_clock(monkeypatch):
    class FixedDateTime(_RealDatetime):
        @classmethod
        def now(cls, tz=None):
            return _RealDatetime(2026, 9, 10, tzinfo=_UTC).astimezone(tz)

    monkeypatch.setattr("proofops.adapters.local.upstage.datetime", FixedDateTime)
