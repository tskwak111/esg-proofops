"""Synthetic corpus, real source-bound preliminary response validation; no API calls."""

from copy import deepcopy
from dataclasses import asdict, replace

import pytest
from proofops.application.tagging import tracks
from proofops.domain.errors import DomainValidationError

from tests.acceptance.test_binding import DIMENSIONS, corpus
from tests.acceptance.test_citations import OTHER, TENANT


def payload(claim):
    return dict(
        claim_id=claim.claim_id,
        track="performance",
        safe_harbor_category=None,
        track_confidence=0.8,
        dimensions={
            name: dict(
                source_index=0,
                start=claim.quote.index(text),
                end=claim.quote.index(text) + len(text),
                quote=text,
            )
            for name, text in DIMENSIONS.items()
        },
    )


def validate(claim, graph, response, **kwargs):
    from proofops.application.tagging.preliminary import validate_preliminary

    return validate_preliminary(claim, graph, response, tenant_id=kwargs.get("tenant_id", TENANT))


def test_preliminary_boundary_exists():
    # Fail on the missing feature, before importing its implementation.
    import importlib.util

    assert importlib.util.find_spec("proofops.application.tagging.preliminary") is not None


def test_verified_dimensions_preserve_literal_sources_without_grading():
    graph, claim, _ = corpus()
    before = asdict(graph), asdict(claim)
    result = validate(claim, graph, payload(claim))
    assert isinstance(result.track, tracks.TrackCandidate)
    assert result.track.track == "performance" and result.track_confidence == 0.8
    assert result.context.claim == claim
    for name, ref in result.context.dimensions.items():
        assert ref.quote == DIMENSIONS[name] and ref.verification_state == "verified"
        assert ref.bbox == claim.source_refs[0].bbox
    assert (asdict(graph), asdict(claim)) == before


def test_null_track_and_dimensions_remain_unresolved():
    graph, claim, _ = corpus()
    raw = payload(claim) | dict(
        track=None,
        track_confidence=None,
        dimensions=dict(entity=None, metric=None, reporting_period=None),
    )
    result = validate(claim, graph, raw)
    assert result.track is None and result.track_confidence is None
    assert result.context.dimensions == raw["dimensions"]


@pytest.mark.parametrize(
    "change",
    [
        {"grade": "E3"},
        {"claim_id": OTHER + "x"},
        {"track": "unknown"},
        {"track_confidence": True},
        {"track_confidence": float("nan")},
        {"track_confidence": 1.1},
        {"track_confidence": None},
        {"safe_harbor_category": "safe"},
        {"dimensions": {}},
        {"dimensions": {"entity": None, "metric": None, "reporting_period": None, "grade": None}},
    ],
)
def test_invalid_or_grading_fields_are_rejected(change):
    graph, claim, _ = corpus()
    with pytest.raises(DomainValidationError):
        validate(claim, graph, payload(claim) | change)


@pytest.mark.parametrize(
    "change",
    [
        {"source_index": True},
        {"source_index": 1},
        {"start": True},
        {"start": -1},
        {"end": 9999},
        {"quote": "다른 회사"},
        {"verification_state": "verified"},
    ],
)
def test_model_cannot_forge_or_relocate_source_refs(change):
    graph, claim, _ = corpus()
    raw = deepcopy(payload(claim))
    raw["dimensions"]["entity"].update(change)
    with pytest.raises(DomainValidationError):
        validate(claim, graph, raw)


@pytest.mark.parametrize("quality", ["unverified", "conflicted", "unreadable", "unlocated"])
def test_verified_flag_does_not_override_original_graph(quality):
    graph, claim, _ = corpus()
    graph = replace(graph, blocks=tuple(replace(b, quality=quality) for b in graph.blocks))
    with pytest.raises(DomainValidationError):
        validate(claim, graph, payload(claim))


def test_identity_and_claim_text_are_verified_before_model_input():
    from proofops.application.tagging.preliminary import preliminary_request

    graph, claim, _ = corpus()
    for forged in (
        replace(claim, quote="forged"),
        replace(claim, tenant_id=OTHER),
        replace(claim, source_sha256="0" * 64),
        replace(claim, source_quality="unverified"),
    ):
        with pytest.raises(DomainValidationError):
            preliminary_request(forged, graph, tenant_id=TENANT)
    with pytest.raises(DomainValidationError):
        validate(claim, graph, payload(claim), tenant_id=OTHER)


def test_request_is_bounded_to_atomic_sources_and_pins_provenance():
    from proofops.application.tagging.preliminary import preliminary_request
    from proofops.domain.provenance import canonical_hash

    graph, claim, _ = corpus()
    request = preliminary_request(claim, graph, tenant_id=TENANT)
    assert request["schema"] == "preliminary-source-quotes-v2"
    assert request["claim_sha256"] == canonical_hash(asdict(claim))
    assert request["graph_sha256"] == canonical_hash(asdict(graph))
    assert request["untrusted_document_data"]["sources"] == [dict(source_index=0, text=claim.quote)]
    assert "topic_ids" not in request["untrusted_document_data"]


def test_blank_dimension_is_not_verified_evidence():
    graph, claim, _ = corpus()
    raw = payload(claim)
    start = claim.quote.index(" ")
    raw["dimensions"]["entity"] = dict(source_index=0, start=start, end=start + 1, quote=" ")
    with pytest.raises(DomainValidationError):
        validate(claim, graph, raw)


def test_extreme_integer_confidence_rejected_at_boundary():
    graph, claim, _ = corpus()
    with pytest.raises(DomainValidationError):
        validate(claim, graph, payload(claim) | dict(track_confidence=10**500))


def test_unique_literal_quote_resolved_locally_without_model_offsets():
    graph, claim, _ = corpus()
    raw = payload(claim)
    for item in raw["dimensions"].values():
        del item["start"], item["end"]
    result = validate(claim, graph, raw)
    assert result.context.dimensions["entity"].char_start == claim.source_refs[0].char_start
    assert result.context.dimensions["metric"].quote == DIMENSIONS["metric"]


def test_ambiguous_quote_only_is_rejected_instead_of_choosing_first_match():
    graph, claim, _ = corpus()
    raw = payload(claim)
    raw["dimensions"]["entity"] = dict(source_index=0, quote="A")
    assert claim.quote.count("A") > 1
    with pytest.raises(DomainValidationError):
        validate(claim, graph, raw)


def test_quote_offsets_are_relative_to_the_atomic_span_not_the_whole_block():
    graph, claim, refs = corpus()
    start = refs[0].quote.index(DIMENSIONS["metric"])
    atomic = replace(refs[0], char_start=start, quote=refs[0].quote[start:])
    claim = replace(claim, source_refs=(atomic,), quote=atomic.quote)
    raw = dict(
        claim_id=claim.claim_id,
        track="performance",
        safe_harbor_category=None,
        track_confidence=0.5,
        dimensions=dict(
            entity=None,
            reporting_period=None,
            metric=dict(source_index=0, quote=DIMENSIONS["metric"]),
        ),
    )
    result = validate(claim, graph, raw)
    assert result.context.dimensions["metric"].char_start == start
    assert result.context.dimensions["metric"].char_end == start + len(DIMENSIONS["metric"])


def test_safe_harbor_category_is_retained_even_when_track_is_unresolved():
    graph, claim, _ = corpus()
    raw = payload(claim) | dict(
        track=None, track_confidence=None, safe_harbor_category="third_party_information"
    )
    result = validate(claim, graph, raw)
    assert result.track is None
    assert result.safe_harbor_category == "third_party_information"
