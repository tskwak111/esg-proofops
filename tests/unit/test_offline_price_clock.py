"""Offline clock isolation and real-time price rejection; no provider calls."""

import importlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime

import pytest

from tests.helpers.price_clock import PRICE_MODULES, SITE_DIRECTORY, PriceDateTime


@pytest.mark.parametrize("name", PRICE_MODULES)
def test_only_price_module_clock_is_fixed(name):
    module = importlib.import_module(name)
    assert module.datetime is PriceDateTime
    assert module.datetime.now(UTC) == datetime(2026, 10, 16, tzinfo=UTC)
    assert importlib.import_module("datetime").datetime is datetime
    deadline = getattr(module, "PRICE_RECHECK_AT", None)
    if deadline is not None:
        assert module.datetime.now(UTC) < deadline


@pytest.mark.parametrize(
    "name",
    ["proofops.adapters.local.upstage_ocr_page", "proofops_api.hosted_ocr"],
)
def test_function_local_datetime_honors_expiry_override(name, monkeypatch):
    module = importlib.import_module(name)

    class ExpiredDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 21, tzinfo=UTC)

    monkeypatch.setattr(module, "datetime", ExpiredDateTime)
    monkeypatch.setattr(
        module.http.client, "HTTPSConnection", lambda *a, **kw: pytest.fail("network dispatch")
    )
    with pytest.raises(ValueError, match="^PRICE_RECHECK_REQUIRED$"):
        module.post_png(b"unused")


def test_unpatched_module_still_rejects_expired_prices(monkeypatch):
    from proofops.adapters.local import openai

    monkeypatch.setattr(openai, "datetime", datetime)
    assert openai.datetime is datetime
    assert datetime.now(UTC) >= openai.PRICE_RECHECK_AT
    with pytest.raises(ValueError, match="^PRICE_RECHECK_REQUIRED$"):
        openai.validate_capacity_policy(openai.CAPACITY_POLICY, model_id=openai.MODEL)


@pytest.mark.parametrize("use_helper", [True, False])
def test_child_price_clock_is_explicit_and_real_guard_survives(tmp_path, use_helper):
    env = os.environ.copy()
    if not use_helper:
        env["PYTHONPATH"] = os.pathsep.join(
            entry
            for entry in env.get("PYTHONPATH", "").split(os.pathsep)
            if entry != str(SITE_DIRECTORY)
        )
    script = """
import importlib
import json
from datetime import UTC, datetime
from proofops.adapters.local import openai

upstage = importlib.import_module("proofops.adapters.local.upstage")

result = {"fixed": openai.datetime is not datetime, "real_expired":
          datetime.now(UTC) >= openai.PRICE_RECHECK_AT}
try:
    openai.validate_capacity_policy(openai.CAPACITY_POLICY, model_id=openai.MODEL)
except ValueError as error:
    result["guard"] = str(error)
else:
    result["guard"] = "admitted"
result["upstage_fixed"] = upstage.datetime is not datetime
print(json.dumps(result))
"""
    child = subprocess.run(
        [sys.executable, "-c", script], env=env, cwd=tmp_path, capture_output=True, text=True
    )
    assert child.returncode == 0, child.stderr
    assert child.stderr == ""
    assert json.loads(child.stdout) == {
        "fixed": use_helper,
        "real_expired": True,
        "guard": "admitted" if use_helper else "PRICE_RECHECK_REQUIRED",
        "upstage_fixed": use_helper,
    }
