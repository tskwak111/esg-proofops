"""E12: a malformed neighbouring table must not invalidate a paragraph reply."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from proofops.application.ingest.graph_fusion import CanonicalBlock
from proofops.application.tagging.dec24 import adjacent_table
from proofops.domain.errors import DomainValidationError

from tests.acceptance.test_parsing import JAVA
from tests.integration.test_claim_source_v3 import synthetic


def graph_with_unlocated_table():
    _, graph, _ = synthetic("Environmental policy reduces emissions 10%")
    focal = graph.blocks[0]
    candidate = focal.candidates[0]
    malformed = replace(
        candidate,
        kind="table",
        source=replace(
            candidate.source, source_native_id="bad-table", native_bbox=(-8, -8, 900, 900)
        ),
        parser_bbox=None,
        parser_to_canonical=None,
    )
    table = CanonicalBlock("bad-table", "table", (malformed,), ("test",), "unlocated", 0)
    return focal, table


def test_unlocated_neighbour_does_not_invalidate_valid_source_or_grant_context():
    focal, table = graph_with_unlocated_table()
    packet = dict(untrusted_document_data=dict(source_id=focal.source_id, kind="paragraph"))
    graph = SimpleNamespace(blocks=(focal, table))
    with pytest.raises(DomainValidationError):
        table.source_ref()  # The original geometry guard remains mandatory.
    with pytest.raises(DomainValidationError):
        adjacent_table(packet, graph)  # Historical resolver remains reproducible.
    assert not adjacent_table(packet, graph, located_only=True)
    assert focal.source_ref().quote == focal.raw_text


def test_valid_table_after_unlocated_table_still_excludes_its_note():
    focal, table = graph_with_unlocated_table()
    focal = SimpleNamespace(
        source_id="note",
        kind="paragraph",
        winner=0,
        page_num=1,
        bbox=(10, 100, 200, 120),
        source_ref=lambda: SimpleNamespace(bbox=(10, 100, 200, 120)),
    )
    valid = SimpleNamespace(
        kind="table",
        winner=0,
        page_num=1,
        bbox=(10, 10, 200, 95),
        source_ref=lambda: SimpleNamespace(bbox=(10, 10, 200, 95)),
    )
    packet = dict(untrusted_document_data=dict(source_id="note", kind="paragraph"))
    assert adjacent_table(packet, SimpleNamespace(blocks=(focal, table, valid)), located_only=True)


def test_p2_pin_is_distinct_and_v18_remains_registered():
    from proofops.application import analysis_profile as profiles
    from proofops.domain.provenance import canonical_hash

    assert canonical_hash(profiles.FINALS_I18_POLICY) == (
        "5793bdc313c653ab1ee4c7a833c412aca081c11ab06530aa81d2c0568b6aa3ab"
    )
    for policy in (profiles.FINALS_I18_POLICY, profiles.FINALS_P2_POLICY):
        pin = canonical_hash(policy)
        assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=pin) == policy
        assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=pin) == policy
    assert canonical_hash(profiles.FINALS_P2_POLICY) != canonical_hash(profiles.FINALS_I18_POLICY)


@pytest.mark.parametrize("failure", [False, True])
def test_claim_layout_attempts_provider_and_retains_local_on_failure(monkeypatch, failure):
    from proofops.adapters.parsing import hx6_upstage as hx6

    _, graph, _ = synthetic("Environmental policy reduces emissions 10%")
    local = graph.candidates[0]
    provider = replace(local, parser_name="upstage_async_standard")
    monkeypatch.setattr(hx6, "native_pages", lambda *a: [1])
    monkeypatch.setattr(hx6, "candidate_batch", lambda *a, **k: (provider, {}))
    calls = []

    def call(pages, mode):
        calls.append((pages, mode))
        if failure:
            raise ValueError("UPSTAGE_REQUEST_TIMEOUT")
        return {"raw_batches": []}, True

    profile = SimpleNamespace(claim_physical_pages=(1,), mixed_ocr_max_pages=0)
    batches, routing, output = hx6.recover(
        None, profile, [1], [local], call, config_hash="p2", claim_layout=True
    )
    assert calls == [((1,), "standard")]
    assert routing["unreadable_pages"] == []
    assert routing["local_pages"] == ([1] if failure else [])
    assert routing["provider_pages"] == ([] if failure else [1])
    assert bool(output["failed_batches"]) is failure
    assert output["profile"] == hx6.CLAIM_LAYOUT_POLICY
    assert batches[-1].blocks == (local if failure else provider).blocks


def test_new_extractor_hash_and_forged_selector_rejection(tmp_path):
    import json

    from proofops_agent.upstage_extraction import UpstageClaimExtractor

    probe = SimpleNamespace(complete=lambda *a, **k: None)
    flags = dict(extraction_source_ids=True, extraction_table_footnotes=True)
    old = UpstageClaimExtractor(probe, tmp_path / "old", **flags)
    new = UpstageClaimExtractor(
        probe, tmp_path / "new", **flags, extraction_located_table_context=True
    )
    assert old.profile != new.profile
    for payload in ({"sentence_ids": ["forged"]}, {"sentence_ids": ["c0", "c0"]}):
        with pytest.raises(ValueError, match="unknown or repeated"):
            new._resolve_payload(payload, "Environmental policy 10%", "source")
    with pytest.raises(ValueError):
        new._validate_spans(
            {"spans": [{"char_start": 0, "char_end": 27, "quote": "Environmental policy 2027"}]},
            "Environmental policy 10%",
        )
    directory = tmp_path / "failure"
    directory.mkdir()
    with pytest.raises(ValueError):
        new._fail(directory, "a" * 64, "request", "MODEL_SELECTOR_INVALID")
    assert json.loads((directory / "failure.json").read_text())["reason_code"] == (
        "MODEL_SELECTOR_INVALID"
    )


def test_claim_layout_parser_replays_new_policy_and_rejects_policy_tampering(tmp_path, monkeypatch):
    import json
    from hashlib import sha256
    from uuid import uuid4

    from proofops.adapters.parsing import hx6_upstage as hx6
    from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser, ParseFailure
    from proofops.application.ingest.graph_fusion import ParserProfile, SourceArtifact
    from proofops.domain.provenance import canonical_hash

    from deploy.public.offline_fixture import fake_parse, source_pdf

    pdf = source_pdf()
    source = SourceArtifact(
        str(uuid4()), str(uuid4()), str(uuid4()), sha256(pdf).hexdigest(), "p2", pdf
    )
    profile = ParserProfile(
        str(uuid4()),
        physical_pages=(1, 2),
        claim_physical_pages=(1,),
        java_executable=JAVA,
        parser_mode="mixed-v1",
        local_resource_policy="selected-pdf-h6-v2",
        failure_policy="partial-v6",
        timeout_seconds=120,
    )
    monkeypatch.setattr(hx6, "native_pages", lambda *a: [1, 2])

    class SavedProvider:
        calls = 0

        def parse_async(self, content, **kwargs):
            self.calls += 1
            raw = [fake_parse(content, "standard")]
            return dict(raw_batches=raw, response_sha256=canonical_hash(raw))

    provider = SavedProvider()
    parser = OpenDataLoaderParser(tmp_path / "parser", upstage_probe=provider)
    graph = parser.parse(source, profile, tenant_id=source.tenant_id)
    assert provider.calls == 1
    assert (
        parser.load_verified(source, profile, tenant_id=source.tenant_id).to_dict()
        == graph.to_dict()
    )
    assert provider.calls == 1  # cold replay cannot perform another paid parse
    prep = next((tmp_path / "parser").rglob("manifest.json")).parent
    routing = json.loads((prep / "page-routing.json").read_text())
    assert routing["provider_pages"] == [1] and routing["local_pages"] == [2]
    path = prep / "upstage.json"
    value = json.loads(path.read_text())
    assert value["profile"] == hx6.CLAIM_LAYOUT_POLICY
    value["profile"] = hx6.POLICY
    path.chmod(0o600)
    path.write_text(json.dumps(value))
    with pytest.raises(ParseFailure, match="INTEGRITY_MISMATCH"):
        parser.load_verified(source, profile, tenant_id=source.tenant_id)


def test_hosted_new_pin_freezes_and_resumes_located_context(tmp_path, monkeypatch):
    import inspect
    import json
    import sys
    from dataclasses import asdict

    from proofops_agent.upstage_extraction import UpstageClaimExtractor

    from deploy.public.offline_fixture import source_pdf
    from evaluation import local_upstage_pilot as pilot
    from evaluation.hosted_r108 import prepare_argv

    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(source_pdf())
    argv = prepare_argv(
        pdf,
        tmp_path / "state",
        "11111111-1111-4111-8111-111111111111",
        dict(
            analysis_profile="finals-unattended-v2",
            report_year=2024,
            period_start="2024-01-01",
            period_end="2024-12-31",
        ),
        options=dict(pages=[1, 2], claim_pages=[1]),
    )
    monkeypatch.setattr(sys, "argv", argv)
    assert pilot.main() == 0
    settings = json.loads((tmp_path / "state/settings.json").read_text())
    manifest = json.loads((tmp_path / "state/pilot.json").read_text())
    assert settings["extraction_located_table_context"] is True
    assert manifest["extraction_located_table_context"] is True
    flags = {
        k: v
        for k, v in settings.items()
        if k.startswith("extraction_")
        and type(v) is bool
        and k in inspect.signature(UpstageClaimExtractor).parameters
    }
    probe = SimpleNamespace(model="gpt-6-luna", wire_policy_version=2, complete=lambda *a: None)
    extractor = UpstageClaimExtractor(
        probe,
        tmp_path / "resolver",
        **flags,
        display_text_profile=settings.get("display_text_policy", {}).get("profile"),
    )
    assert asdict(extractor.profile) == settings["extraction_profile"]
