"""Operator-set local parser memory reaches new hosted runs; unset keeps 768 MiB."""

import json
import sys

import pytest

from evaluation.hosted_r108 import prepare_argv
from tests.test_hosted_analysis import source_pdf

TENANT = "11111111-1111-4111-8111-111111111111"
CONFIG = dict(
    analysis_profile="finals-unattended-v2",
    report_year=2024,
    period_start="2024-01-01",
    period_end="2024-12-31",
)
OPTIONS = dict(pages=[10, 20], claim_pages=[10], pipeline_profile="finals-unattended-v2")


def _argv(tmp_path):
    source = tmp_path / "selected.pdf"
    source.write_bytes(source_pdf())
    return prepare_argv(source, tmp_path / "state", TENANT, CONFIG, OPTIONS)


def test_unset_keeps_pilot_default(tmp_path, monkeypatch):
    monkeypatch.delenv("HOSTED_PARSER_MEMORY_BYTES", raising=False)
    assert "--parser-memory-bytes" not in _argv(tmp_path)


@pytest.mark.parametrize("value", ["0", "abc", "-1", str(4 * 1024**3 + 1)])
def test_invalid_value_is_rejected(tmp_path, monkeypatch, value):
    monkeypatch.setenv("HOSTED_PARSER_MEMORY_BYTES", value)
    with pytest.raises(ValueError, match="HOSTED_PARSER_MEMORY_BYTES_INVALID"):
        _argv(tmp_path)


def test_set_value_is_frozen_in_new_run(tmp_path, monkeypatch):
    from evaluation import local_upstage_pilot as pilot

    __import__("pypdfium2")  # Load the native library before overriding sys.platform.
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("HOSTED_PARSER_MEMORY_BYTES", str(2 * 1024**3))
    argv = _argv(tmp_path)
    assert argv[argv.index("--parser-memory-bytes") + 1] == str(2 * 1024**3)
    monkeypatch.setattr(sys, "argv", argv)
    assert pilot.main() == 0
    manifest = json.loads((tmp_path / "state" / "pilot.json").read_text())
    assert manifest["parser_memory_bytes"] == 2 * 1024**3
