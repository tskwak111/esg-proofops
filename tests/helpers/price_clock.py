"""Recorded-price time for offline tests only; never patch the process-wide clock.

Both pytest and explicitly opted-in Python children use this implementation.
Production price constants, policy bytes, budget and authorization clocks stay intact.
"""

import builtins
import importlib
import importlib.abc
import importlib.machinery
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

PRICE_MODULES = (
    "proofops.adapters.local.openai",
    "proofops.adapters.local.upstage",
    "proofops.adapters.local.upstage_parse",
    "proofops.adapters.local.upstage_extract",
    "proofops.adapters.local.upstage_ocr_page",
    "proofops.adapters.local.upstage_ocr_profile_d2_v21",
    "proofops.adapters.local._frozen_upstage_ocr_profile_v21_20261015",
    "proofops_api.hosted_ocr",
    "scripts.hf1_validate_live",
)
# These two transports import datetime inside post_png, rather than at module scope.
LOCAL_DATETIME_IMPORTS = {
    "proofops.adapters.local.upstage_ocr_page",
    "proofops_api.hosted_ocr",
}
SITE_DIRECTORY = Path(__file__).with_name("price_clock_site")
_real_import = builtins.__import__


class PriceDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        # On/after the latest recorded capture (HF1), before every recheck deadline.
        return datetime(2026, 10, 16, tzinfo=UTC).astimezone(tz)


def _price_import(name, globals=None, locals=None, fromlist=(), level=0):
    module = _real_import(name, globals, locals, fromlist, level)
    caller = (globals or {}).get("__name__")
    if name == "datetime" and caller in LOCAL_DATETIME_IMPORTS:
        # A per-import view leaves the stdlib datetime module and every other caller
        # untouched. Read the module attribute so explicit expiry overrides still win.
        view = ModuleType("datetime")
        view.__dict__.update(vars(module))
        view.datetime = sys.modules[caller].datetime
        return view
    return module


def install_price_clock(set_attribute=setattr):
    """Patch only audited price modules; pytest supplies a reversible setter."""
    for name in PRICE_MODULES:
        set_attribute(importlib.import_module(name), "datetime", PriceDateTime)
    set_attribute(builtins, "__import__", _price_import)


class _PriceClockLoader:
    def __init__(self, loader):
        self.loader = loader

    def __getattr__(self, name):
        return getattr(self.loader, name)

    def create_module(self, spec):
        return self.loader.create_module(spec)

    def exec_module(self, module):
        self.loader.exec_module(module)
        module.datetime = PriceDateTime


class _PriceClockFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname not in PRICE_MODULES:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec is not None and spec.loader is not None:
            spec.loader = _PriceClockLoader(spec.loader)
        return spec


def install_child_price_clock():
    # Do not preload product code: domain-only children must retain pure imports,
    # and unrelated parser/verifier children must not load every provider adapter.
    sys.meta_path.insert(0, _PriceClockFinder())
    builtins.__import__ = _price_import


def child_pythonpath(existing=""):
    """Only a test's child environment should receive this startup directory."""
    return os.pathsep.join([str(SITE_DIRECTORY), *([existing] if existing else [])])
