"""Offline occurrence wire through the real citation and binding boundaries."""

from dataclasses import replace

import pytest
from proofops.application.tagging.relations import (
    OCCURRENCE_PROFILE,
    OCCURRENCE_SCHEMA,
    relation_request,
    validate_relations,
)
from proofops.domain.errors import DomainValidationError

from tests.acceptance.test_binding import DIMENSIONS, bind, corpus, span
from tests.acceptance.test_citations import TENANT


def packet(refs, graph):
    return relation_request(refs, graph, tenant_id=TENANT, profile=OCCURRENCE_PROFILE)


def selected(packet, index, quote, occurrence=0):
    source = packet["untrusted_document_data"]["sources"][index]
    matches = [c for c in source["occurrences"] if c["quote"] == quote]
    return sorted(matches, key=lambda c: c["start"])[occurrence]["span_id"]


def response(packet):
    return {
        "relations": [
            {
                "source_index": s["source_index"],
                "dimensions": {"entity": None, "metric": None, "reporting_period": None},
            }
            for s in packet["untrusted_document_data"]["sources"]
        ]
    }


def validate(refs, graph, raw):
    return validate_relations(refs, graph, raw, tenant_id=TENANT, profile=OCCURRENCE_PROFILE)


def test_repeated_literal_resolves_exact_second_occurrence_with_server_offsets():
    graph, _, refs = corpus(claim_dimensions={"entity": "기아는 기아는"})
    p = packet(refs, graph)
    assert p["schema"] == OCCURRENCE_SCHEMA
    raw = response(p)
    raw["relations"][0]["dimensions"]["entity"] = selected(p, 0, "기아", 1)
    role = validate(refs, graph, raw)[refs[0].source_id]["entity"]
    assert role.quote == "기아" and role.char_start == refs[0].char_start + 4
    assert role.verification_state == "verified"
    assert validate(refs, graph, raw)[refs[0].source_id]["metric"] is None


@pytest.mark.parametrize("fault", ["foreign_source", "unknown", "offset", "quote", "grade", "bool"])
def test_only_issued_same_source_ids_or_null_are_accepted(fault):
    graph, _, refs = corpus()
    p = packet(refs, graph)
    raw = response(p)
    choice = {
        "foreign_source": selected(p, 1, "회사A"),
        "unknown": "0" * 64,
        "offset": {"start": 0, "end": 3},
        "quote": {"quote": "회사A"},
        "grade": {"span_id": selected(p, 0, "회사A"), "grade": "E3"},
        "bool": True,
    }[fault]
    raw["relations"][0]["dimensions"]["entity"] = choice
    with pytest.raises(DomainValidationError) as error:
        validate(refs, graph, raw)
    assert error.value.code.startswith("RELATION_")


def test_id_is_bound_to_graph_and_tenant():
    graph, _, refs = corpus()
    p = packet(refs, graph)
    raw = response(p)
    raw["relations"][0]["dimensions"]["entity"] = selected(p, 0, "회사A")
    with pytest.raises(DomainValidationError):
        validate(refs, replace(graph, source_sha256="f" * 64), raw)
    with pytest.raises(DomainValidationError):
        validate_relations(
            refs,
            graph,
            raw,
            tenant_id="77777777-7777-4777-8777-777777777777",
            profile=OCCURRENCE_PROFILE,
        )


@pytest.mark.parametrize("changes", [{}, {"product": "제품B"}, {"reporting_period": "2030"}])
def test_selected_ids_still_go_through_existing_role_and_year_binding(changes):
    graph, claim, refs = corpus(**changes)
    p = packet(refs, graph)
    raw = response(p)
    raw["relations"][1]["dimensions"] = {
        role: selected(p, 1, quote) for role, quote in (DIMENSIONS | changes).items()
    }
    roles = validate(refs, graph, raw)[refs[1].source_id]
    assert bind(graph, claim, span(refs[1], "40%"), roles) == (
        "rejected" if changes else "accepted"
    )


def test_old_profile_is_default_and_new_wire_cannot_enter_old_validator():
    graph, _, refs = corpus()
    assert relation_request(refs, graph, tenant_id=TENANT)["schema"] == "source-relations-v1"
    p = packet(refs, graph)
    raw = response(p)
    raw["relations"][0]["dimensions"]["entity"] = selected(p, 0, "회사A")
    with pytest.raises(DomainValidationError):
        validate_relations(refs, graph, raw, tenant_id=TENANT)
    with pytest.raises(DomainValidationError):
        relation_request(refs, graph, tenant_id=TENANT, profile="typo")


def configured_transport(tmp_path, monkeypatch):
    import json
    from dataclasses import asdict

    from proofops.application.preflight import check_local_upstage_tagger
    from proofops.application.tagging.relations import OCCURRENCE_SYSTEM_PROMPT
    from proofops.domain.provenance import canonical_hash
    from proofops_agent.upstage_relations import UpstageOccurrenceRelationsTransport

    from tests.integration.test_upstage_relations_transport import configured
    from tests.integration.test_upstage_tagger_preflight import configured as approvals

    old, probe, calls, request, envelope = configured(tmp_path, monkeypatch)
    graph, _, refs = corpus()
    envelope = envelope | packet((refs[0],), graph)
    settings = replace(
        old._settings, model_profile=OCCURRENCE_PROFILE, system_prompt=OCCURRENCE_SYSTEM_PROMPT
    )
    authorization = approvals()
    authorization.pop("settings")
    authorization["binding"].update(
        model_id=settings.model_id, tagging_settings_sha256=canonical_hash(asdict(settings))
    )

    def authorize(selected, request):
        # Transport-only fixture: production preflight intentionally still blocks
        # this profile until its owner integrates the new pinned allow-list.
        from proofops.application.preflight import Check, Preflight

        assert selected == settings and request["model_profile"] == OCCURRENCE_PROFILE
        return Preflight(
            True,
            tuple(
                Check(name, "pass", "synthetic transport fixture")
                for name in (
                    "runtime_approval",
                    "consent_approval",
                    "model_binding",
                    "document_scope",
                    "document_rights",
                    "data_consent",
                    "tagging_settings",
                    "selected_document_rights",
                )
            ),
            canonical_hash(authorization["binding"]),
            authorization["checked_at"],
        )

    assert not check_local_upstage_tagger(settings=settings, **authorization).ready
    adapter = UpstageOccurrenceRelationsTransport(
        probe, tmp_path / "v2-receipts", settings=settings, tenant_id=TENANT, authorize=authorize
    )
    request.update(
        model_profile=settings.model_profile,
        system_prompt=settings.rendered_system,
        user_json=json.dumps(envelope),
        packet_sha256=canonical_hash(envelope),
    )
    return adapter, probe, calls, request, envelope


@pytest.fixture
def price_clock(monkeypatch):
    from datetime import UTC, datetime

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 10, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr("proofops.adapters.local.upstage.datetime", Clock)


def test_v2_fake_http_preserves_raw_ids_and_three_distinct_receipts(
    tmp_path, monkeypatch, price_clock
):
    import json
    from uuid import UUID

    from proofops.domain.provenance import canonical_hash

    adapter, probe, calls, request, envelope = configured_transport(tmp_path, monkeypatch)
    raw = response(envelope)
    raw["relations"][0]["dimensions"]["entity"] = selected(envelope, 0, "회사A")

    def post(body):
        calls.append(body)
        assert json.loads(body["messages"][1]["content"]) == envelope
        return {
            "id": f"fake-{len(calls)}",
            "model": probe.model,
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(raw)}}],
        }

    monkeypatch.setattr(probe, "_post", post)
    for replica in (1, 2, 3):
        req = request | {
            "replicate_id": replica,
            "request_id": str(UUID(int=900 + replica)),
            "request_signature": canonical_hash(str(replica)),
        }
        result = adapter.invoke(req)
        assert json.loads(result.raw_response_json) == raw
        receipt = json.loads(
            (tmp_path / "v2-receipts" / req["request_id"] / "request.json").read_text()
        )
        assert receipt["transport_version"] == "relation-occurrence-selection-v2"
    assert len(calls) == 3


@pytest.mark.parametrize("fault", ["schema", "prompt", "offset", "quote", "duplicate", "source"])
def test_v2_bad_packet_stops_before_fake_http(tmp_path, monkeypatch, price_clock, fault):
    import json

    from proofops.domain.provenance import canonical_hash

    adapter, probe, calls, request, envelope = configured_transport(tmp_path, monkeypatch)
    source = envelope["untrusted_document_data"]["sources"][0]
    if fault == "schema":
        envelope["schema"] = "source-relations-v1"
    elif fault == "prompt":
        envelope["prompt_sha256"] = "0" * 64
    elif fault == "offset":
        source["occurrences"][0]["start"] = True
    elif fault == "quote":
        source["occurrences"][0]["quote"] = "2031"
    elif fault == "duplicate":
        source["occurrences"].append(source["occurrences"][0])
    else:
        source["source_id"] = "foreign"
    request.update(user_json=json.dumps(envelope), packet_sha256=canonical_hash(envelope))
    with pytest.raises(ValueError):
        adapter.invoke(request)
    assert calls == [] and probe.summary()["calls"] == 0


def test_published_prompt_schema_and_catalog_bounds():
    import json
    from pathlib import Path

    import jsonschema
    from proofops.application.ingest.span_alignment import SourceIdentity
    from proofops.application.tagging.relations import (
        OCCURRENCE_SYSTEM_PROMPT,
        relation_occurrence_catalog,
    )

    assert Path("prompts/source_relations_occurrence_v2.md").read_text() == OCCURRENCE_SYSTEM_PROMPT
    graph, _, refs = corpus()
    p = packet(refs, graph)
    raw = response(p)
    raw["relations"][0]["dimensions"]["entity"] = selected(p, 0, "회사A")
    schema = json.loads(Path("prompts/source_relations_occurrence_v2.schema.json").read_text())
    jsonschema.validate(raw, schema)
    raw["relations"][0]["dimensions"]["entity"] = {"quote": "회사A"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw, schema)
    identity = SourceIdentity(
        TENANT,
        graph.document_version_id,
        refs[0].source_id,
        graph.parse_manifest_id,
        "a" * 64,
        "b" * 64,
        1,
    )
    with pytest.raises(DomainValidationError, match="RELATION_CATALOG_LIMIT"):
        relation_occurrence_catalog(identity, "가" * 8193)
    with pytest.raises(DomainValidationError, match="RELATION_CATALOG_LIMIT"):
        relation_occurrence_catalog(identity, "word " * 513)


def test_occurrence_catalog_candidate_limit_fails_without_truncation():
    from proofops.application.ingest.span_alignment import SourceIdentity
    from proofops.application.tagging.relations import relation_occurrence_catalog

    graph, _, refs = corpus()
    identity = SourceIdentity(
        TENANT,
        graph.document_version_id,
        refs[0].source_id,
        graph.parse_manifest_id,
        "a" * 64,
        "b" * 64,
        1,
    )
    with pytest.raises(DomainValidationError, match="RELATION_CATALOG_LIMIT"):
        relation_occurrence_catalog(identity, "가" * 92)
