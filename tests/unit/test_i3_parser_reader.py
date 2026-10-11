"""The parser must bind the K3 reader to the owning run before source gates."""

from types import SimpleNamespace

import pytest
from proofops.adapters.local import upstage_ocr_profile_v11 as reader
from proofops_worker.local_runner import LocalParserRunner


def test_parser_selects_run_scoped_v11_reader(monkeypatch):
    class ReaderSelected(Exception):
        pass

    def select(run_id):
        assert run_id == "owning-run"
        raise ReaderSelected

    monkeypatch.setattr(reader, "for_run", select)
    runner = object.__new__(LocalParserRunner)
    runner.store = SimpleNamespace(
        snapshot=lambda tenant, run: {"claim_source_policy": reader.claim_source_policy()},
        jobs=SimpleNamespace(get_run=lambda tenant, run: {}),
    )
    runner._raster_enabled = lambda snapshot: False
    runner.verify_paragraphs = False
    runner.native_typography_tolerance = False
    runner.profile = SimpleNamespace(table_source_policy_sha256=None)
    with pytest.raises(ReaderSelected):
        runner.run_once(tenant_id="owning-tenant", run_id="owning-run")
