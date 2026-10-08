"""Bounded v3 catalog; immutable v2 and existing citation/binding guards."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from proofops.application.ingest.span_alignment import SourceIdentity
from proofops.application.tagging.relations import (
    OCCURRENCE_PROFILE,
    OCCURRENCE_V3_POLICY,
    OCCURRENCE_V3_PROFILE,
    OCCURRENCE_V3_SCHEMA,
    OCCURRENCE_V3_SYSTEM_PROMPT,
    bounded_occurrence_sources,
    ranked_occurrence_catalog,
    relation_request,
    validate_relations,
)
from proofops.domain.errors import DomainValidationError
from proofops.domain.provenance import canonical_hash

from tests.acceptance.test_binding import DIMENSIONS, bind, corpus, span
from tests.acceptance.test_citations import TENANT


def packet(refs, graph, claim, **kwargs):
    return relation_request(
        refs,
        graph,
        tenant_id=TENANT,
        profile=OCCURRENCE_V3_PROFILE,
        claim_text=claim.quote,
        dimensions=DIMENSIONS,
        **kwargs,
    )


def response(envelope):
    return {
        "relations": [
            dict(
                source_index=s["source_index"],
                dimensions=dict(entity=None, metric=None, reporting_period=None),
            )
            for s in envelope["untrusted_document_data"]["sources"]
        ]
    }


def validate(refs, graph, claim, raw):
    return validate_relations(
        refs,
        graph,
        raw,
        tenant_id=TENANT,
        profile=OCCURRENCE_V3_PROFILE,
        claim_text=claim.quote,
        dimensions=DIMENSIONS,
    )


def selected(envelope, index, quote, role):
    return next(
        c["span_id"]
        for c in envelope["untrusted_document_data"]["sources"][index]["occurrences"]
        if c["quote"] == quote and role in c["roles"]
    )


def test_v3_deterministic_windows_and_v2_unchanged():
    graph, claim, refs = corpus()
    old = relation_request(refs, graph, tenant_id=TENANT, profile=OCCURRENCE_PROFILE)
    old_hash = canonical_hash(old)
    p = packet(refs, graph, claim)
    assert p == packet(refs, graph, claim)
    assert p["schema"] == OCCURRENCE_V3_SCHEMA
    assert (
        canonical_hash(relation_request(refs, graph, tenant_id=TENANT, profile=OCCURRENCE_PROFILE))
        == old_hash
    )
    assert Path("prompts/source_relations_occurrence_v3.md").read_text() == (
        OCCURRENCE_V3_SYSTEM_PROMPT
    )
    for source, ref in zip(p["untrusted_document_data"]["sources"], refs):
        assert "text" not in source
        for w in source["windows"]:
            assert w["text"] == ref.quote[w["start"] : w["end"]]
        for c in source["occurrences"]:
            assert c["quote"] == ref.quote[c["start"] : c["end"]]
            assert any(w["start"] <= c["start"] < c["end"] <= w["end"] for w in source["windows"])
        for role in DIMENSIONS:
            assert (
                sum(role in c["roles"] for c in source["occurrences"])
                <= (OCCURRENCE_V3_POLICY["per_dimension"])
            )


@pytest.mark.parametrize(
    "fault", ["foreign_source", "fabricated_id", "pruned_id", "offset", "graph", "tenant"]
)
def test_v3_rejects_unissued_or_wrong_role_selections(fault):
    graph, claim, refs = corpus()
    p = packet(refs, graph, claim)
    raw = response(p)
    choice = selected(p, 1, "함유비율", "metric")
    if fault == "foreign_source":
        choice = selected(p, 0, "함유비율", "metric")
    elif fault == "fabricated_id":
        choice = "0" * 64
    elif fault == "pruned_id":
        old = relation_request(refs, graph, tenant_id=TENANT, profile=OCCURRENCE_PROFILE)
        ids = {
            c["span_id"]
            for c in p["untrusted_document_data"]["sources"][1]["occurrences"]
            if "metric" in c["roles"]
        }
        choice = next(
            c["span_id"]
            for c in old["untrusted_document_data"]["sources"][1]["occurrences"]
            if c["span_id"] not in ids
        )
    elif fault == "offset":
        choice = dict(quote="함유비率", start=0, end=4)
    elif fault == "graph":
        graph = replace(graph, source_sha256="f" * 64)
    elif fault == "tenant":
        graph = replace(graph, tenant_id="77777777-7777-4777-8777-777777777777")
    raw["relations"][1]["dimensions"]["metric"] = choice
    with pytest.raises(DomainValidationError):
        validate(refs, graph, claim, raw)


def test_v3_null_remains_unresolved():
    graph, claim, refs = corpus()
    p = packet(refs, graph, claim)
    roles = validate(refs, graph, claim, response(p))
    assert all(v is None for r in roles.values() for v in r.values())
    assert bind(graph, claim, span(refs[1], "40%"), roles[refs[1].source_id]) == "undetermined"


@pytest.mark.parametrize("changes", [{}, {"product": "제품B"}, {"reporting_period": "2030"}])
def test_v3_preserves_existing_binding_veto(changes):
    graph, claim, refs = corpus(**changes)
    # Changed roles may be omitted by selection. Omission cannot establish approval.
    p = packet(refs, graph, claim)
    raw = response(p)
    values = DIMENSIONS | changes
    for role, quote in values.items():
        available = [
            c["span_id"]
            for c in p["untrusted_document_data"]["sources"][1]["occurrences"]
            if c["quote"] == quote and role in c["roles"]
        ]
        raw["relations"][1]["dimensions"][role] = available[0] if available else None
    roles = validate(refs, graph, claim, raw)[refs[1].source_id]
    state = bind(graph, claim, span(refs[1], "40%"), roles)
    assert state == "accepted" if not changes else state in {"rejected", "undetermined"}


def test_many_sources_share_one_budget_and_keep_late_anchor():
    identity = SourceIdentity(TENANT, "version", "source", "manifest", "a" * 64, "b" * 64, 1)
    text = " unrelated" * 50 + " 회사A 2025 배출량 40%"
    inputs = tuple((replace(identity, source_id=f"source-{n}"), text) for n in range(12))
    packets, ranked = bounded_occurrence_sources(
        inputs, claim_text="회사A 2025 배출량 40%", dimensions={"metric": "배출량"}
    )
    size = sum(
        len(
            json.dumps(
                json.dumps(p, ensure_ascii=False, separators=(",", ":")), ensure_ascii=False
            ).encode()
        )
        for p in packets
    )
    assert size + len(packets) + 1 <= OCCURRENCE_V3_POLICY["source_packets_bytes"]
    assert len(packets) == 12
    assert all(any(c.quote == "배출량" for c in r["metric"]) for r in ranked)
    assert ranked_occurrence_catalog(identity, text, claim_text="", dimensions={}) == (
        ranked_occurrence_catalog(identity, text, claim_text="", dimensions={})
    )


def test_role_name_alone_never_approves_a_reporting_period():
    graph, claim, refs = corpus()
    p = packet(refs, graph, claim)
    raw = response(p)
    for role, quote in DIMENSIONS.items():
        raw["relations"][1]["dimensions"][role] = selected(p, 1, quote, role)
    options = [
        c["span_id"]
        for c in p["untrusted_document_data"]["sources"][1]["occurrences"]
        if c["quote"] == "함유비율" and "reporting_period" in c["roles"]
    ]
    if options:
        raw["relations"][1]["dimensions"]["reporting_period"] = options[0]
        roles = validate(refs, graph, claim, raw)[refs[1].source_id]
        assert bind(graph, claim, span(refs[1], "40%"), roles) != "accepted"
    else:
        raw["relations"][1]["dimensions"]["reporting_period"] = selected(p, 1, "함유비율", "metric")
        with pytest.raises(DomainValidationError):
            validate(refs, graph, claim, raw)


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "window",
        "boolean_offset",
        "foreign_role",
        "duplicate",
        "source_hash",
        "missing_window",
        "axis_limit",
    ],
)
def test_v3_transport_checks_literal_windows_and_per_axis_bounds(fault):
    from copy import deepcopy

    from proofops_agent.upstage_relations import UpstageOccurrenceV3RelationsTransport

    graph, claim, refs = corpus()
    source = deepcopy(packet(refs, graph, claim)["untrusted_document_data"]["sources"][0])
    transport = object.__new__(UpstageOccurrenceV3RelationsTransport)
    if fault == "window":
        source["windows"][0]["text"] = "foreign"
    elif fault == "boolean_offset":
        source["occurrences"][0]["start"] = True
    elif fault == "foreign_role":
        source["occurrences"][0]["roles"] = ["grade"]
    elif fault == "duplicate":
        source["occurrences"].append(deepcopy(source["occurrences"][0]))
    elif fault == "source_hash":
        source["raw_text_sha256"] = "invalid"
    elif fault == "missing_window":
        source["windows"] = []
    elif fault == "axis_limit":
        candidate = source["occurrences"][0]
        source["occurrences"] = [
            candidate | {"span_id": f"{n:064x}", "roles": ["entity"]}
            for n in range(OCCURRENCE_V3_POLICY["per_dimension"] + 1)
        ]
    if fault is None:
        transport._validate_occurrences(source)
        source.update(occurrences=[], windows=[])
        transport._validate_occurrences(source)  # Incomplete catalogs allow only null downstream.
    else:
        with pytest.raises(ValueError, match="UPSTAGE_RELATIONS_OCCURRENCES_INVALID"):
            transport._validate_occurrences(source)
