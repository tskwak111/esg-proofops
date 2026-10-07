"""Offline candidate contracts; these fixtures do not measure model accuracy."""

from dataclasses import replace

import pytest
from proofops.application.ingest.span_alignment import (
    SourceIdentity,
    align_span,
    build_alignment,
    build_candidates,
    occurrence_candidates,
)
from proofops.application.tagging.occurrence_selection import select_occurrence
from proofops.domain.errors import DomainValidationError


def identity(**changes):
    return replace(
        SourceIdentity("tenant", "version", "source", "manifest", "a" * 64, "b" * 64, 84), **changes
    )


def wire(source, span_id, role="entity"):
    return {
        "schema": "occurrence-selection-v1",
        "source_id": source.source_id,
        "role": role,
        "span_id": span_id,
    }


def select(source, candidates, raw, **kwargs):
    return select_occurrence(
        source, candidates, raw, expected_identity=identity(), expected_role="entity", **kwargs
    )


def test_raw_logical_round_trip_preserves_unicode_whitespace_and_crlf():
    raw = "• 조건이면\r\n2030년 −1.5 tCO2eq를 감축하지 않는다.  ﬁ  ２０３０ 😀"
    mapping = build_alignment(raw)
    assert mapping.text == raw.replace("\r\n", "\n")
    assert mapping.restore(0, len(mapping.text)) == raw
    for start in range(len(mapping.text)):
        for end in range(start + 1, len(mapping.text) + 1):
            raw_span = mapping.raw_span(start, end)
            assert mapping.selected_span(*raw_span) == (start, end)
            assert mapping.restore(start, end) == raw[slice(*raw_span)]
    with pytest.raises(DomainValidationError):
        mapping.selected_span(raw.index("\r") + 1, len(raw))


@pytest.mark.parametrize("bounds", [(-1, 1), (0, 99), (2, 1), (1, 1), (True, 2)])
def test_bad_bounds_rejected(bounds):
    with pytest.raises(DomainValidationError):
        build_alignment("abc").raw_span(*bounds)


def test_bullets_and_conservative_clause_preserve_conditions_negation_context():
    raw = (
        "조건 충족 시에만 적용한다.\n"
        "• 2030년까지 감축하지 않는다. 다만 승인 시 재검토한다. • 2040년 목표"
    )
    candidates = build_candidates(identity(), raw)
    assert [c.kind for c in candidates] == ["clause", "bullet", "bullet"]
    assert "감축하지 않는다. 다만 승인 시" in candidates[1].quote
    for c in candidates:
        assert c.quote == raw[c.raw_start : c.raw_end]
        assert c.context_quote == raw  # Shared subject / condition is never discarded.
        assert c.verification_state == "candidate"
    assert (
        build_candidates(identity(), "조건이면\n감축하지 않는다.")[0].quote
        == "조건이면\n감축하지 않는다."
    )


def test_cells_are_explicit_server_ranges_and_not_whole_table_approval():
    raw = "연도\t2030\n값\t−1.5 tCO2eq"
    cells = (("year", 3, 7), ("value", 10, len(raw)))
    candidates = build_candidates(identity(), raw, cells=cells)
    assert [(c.cell_id, c.quote) for c in candidates] == [
        ("year", "2030"),
        ("value", "−1.5 tCO2eq"),
    ]
    assert all(c.kind == "cell" and c.verification_state == "candidate" for c in candidates)


@pytest.mark.parametrize(
    "cells",
    [(("a", -1, 3),), (("a", 0, 99),), (("a", 0, 2), ("a", 2, 3)), (("a", 0, 2), ("b", 1, 3))],
)
def test_invalid_cell_ranges_rejected(cells):
    with pytest.raises(DomainValidationError):
        build_candidates(identity(), "abc", cells=cells)


def test_repeated_and_overlapping_occurrences_have_distinct_stable_ids():
    candidates = occurrence_candidates(identity(), "AAA", "AA")
    assert [c.raw_start for c in candidates] == [0, 1]
    assert [c.occurrence for c in candidates] == [0, 1]
    assert len({c.span_id for c in candidates}) == 2
    assert candidates == occurrence_candidates(identity(), "AAA", "AA")
    for c in candidates:
        selected = select(identity(), candidates, wire(identity(), c.span_id))
        assert selected.span == c
        assert selected.verification_state == "candidate"
        assert selected.role_state == "unresolved"


@pytest.mark.parametrize(
    "change",
    [
        dict(tenant_id="other"),
        dict(document_version_id="other"),
        dict(source_id="other"),
        dict(parse_manifest_id="other"),
        dict(graph_sha256="c" * 64),
        dict(original_sha256="c" * 64),
        dict(physical_page=85),
    ],
)
def test_foreign_context_rejected_and_id_changes(change):
    other = identity(**change)
    candidates = occurrence_candidates(other, "기아", "기아")
    assert candidates[0].span_id != occurrence_candidates(identity(), "기아", "기아")[0].span_id
    with pytest.raises(DomainValidationError):
        select(other, candidates, wire(other, candidates[0].span_id))


@pytest.mark.parametrize(
    "change",
    [
        dict(schema="future"),
        dict(source_id="other"),
        dict(span_id="unknown"),
        dict(span_id=True),
        dict(role="metric"),
        dict(role="grade"),
        dict(start=0),
        dict(quote="2031"),
        dict(grade="E3"),
    ],
)
def test_wire_rejects_unknown_ids_wrong_role_offsets_and_extra_fields(change):
    source = identity()
    candidates = occurrence_candidates(source, "2030", "2030")
    with pytest.raises(DomainValidationError):
        select(source, candidates, wire(source, candidates[0].span_id) | change)


@pytest.mark.parametrize(
    "quote",
    [
        "2031 −1.5 tCO2eq",
        "2030 +1.5 tCO2eq",
        "2030 −1.5 +CO2eq",
        "2030 −1.5 kgCO2eq",
        "2030−1.5tCO2eq",
        "２０３０ −1.5 tCO2eq",
    ],
)
def test_no_numeric_unit_sign_space_or_nfkc_correction(quote):
    raw = "2030 −1.5 tCO2eq"
    assert occurrence_candidates(identity(), raw, quote) == ()
    with pytest.raises(DomainValidationError):
        align_span(build_alignment(raw), 0, len(raw), quote)


def test_only_crlf_equivalence_and_literal_quote_are_allowed():
    assert align_span(build_alignment("A\r\nB"), 0, 3, "A\nB") == (0, 4)
    with pytest.raises(DomainValidationError):
        align_span(build_alignment("정 보"), 0, 3, "정보")


def test_null_is_unresolved_never_absent_and_known_wrong_semantics_never_approved():
    source = identity()
    result = select(source, (), wire(source, None))
    assert result.span is None and result.role_state == "unresolved"
    candidates = occurrence_candidates(source, "2030", "2030")
    # A syntactically valid entity pointing at a year is still only a proposal.
    result = select(source, candidates, wire(source, candidates[0].span_id))
    assert result.role_state == "unresolved" and result.verification_state == "candidate"


def test_catalog_is_server_owned_and_rejects_tampering():
    source = identity()
    candidate = occurrence_candidates(source, "2030", "2030")[0]
    for mutated in [
        replace(candidate, raw_end=99),
        replace(candidate, quote="2031"),
        replace(candidate, identity=identity(source_id="other")),
    ]:
        with pytest.raises(DomainValidationError):
            select(source, (mutated,), wire(source, candidate.span_id))
    with pytest.raises(DomainValidationError):
        select(source, (candidate, candidate), wire(source, candidate.span_id))
