from types import SimpleNamespace

import pytest
from proofops.application.claims import ExtractionOutputError
from proofops_agent.upstage_extraction import GraphBoundExtractor


@pytest.mark.parametrize("active", [True, False])
def test_missing_grid_is_unresolved_only_under_new_policy(active):
    def missing(*a, **k):
        raise ValueError("J8_GRID_MISSING")

    inner = SimpleNamespace(
        _context=True,
        _j8=True,
        _i5_tables=active,
        _display_text_profile=None,
        extract=missing,
    )
    bound = GraphBoundExtractor(inner, object())
    packet = {"untrusted_document_data": {"kind": "table"}}
    if active:
        with pytest.raises(ExtractionOutputError, match="TABLE_GRID_UNREADABLE"):
            bound.extract(packet)
    else:
        with pytest.raises(ValueError, match="J8_GRID_MISSING") as failure:
            bound.extract(packet)
        assert not isinstance(failure.value, ExtractionOutputError)


def test_table_guard_never_masks_identity_or_source_integrity_failure():
    def invalid(*a, **k):
        raise ValueError("UPSTAGE_CONTEXT_IDENTITY_MISMATCH")

    inner = SimpleNamespace(
        _context=True,
        _j8=True,
        _i5_tables=True,
        _display_text_profile=None,
        extract=invalid,
    )
    with pytest.raises(ValueError, match="UPSTAGE_CONTEXT_IDENTITY_MISMATCH") as failure:
        GraphBoundExtractor(inner, object()).extract({"untrusted_document_data": {"kind": "table"}})
    assert not isinstance(failure.value, ExtractionOutputError)
