from dataclasses import replace

import pytest
from proofops.application.ingest.graph_fusion import ParserProfile

from tests.acceptance.test_parsing import MANIFEST


def test_execution_is_explicit_and_old_parser_hash_is_preserved():
    old = ParserProfile(MANIFEST)
    assert "execution_policy" not in old.invocation_snapshot()
    new = replace(old, execution_policy="spp-parse-v1")
    assert new.config_hash() != old.config_hash()
    with pytest.raises(ValueError):
        replace(old, execution_policy="unregistered")


def test_direct_reader_still_checks_current_policy_and_rejects_drift(monkeypatch):
    from proofops.adapters.local import upstage_ocr_profile_v21 as reader
    from proofops.adapters.parsing import spp_execution as spp

    digest = reader.table_policy_sha256()
    assert spp.table_verifier(digest) is reader
    monkeypatch.setattr(reader, "table_policy_sha256", lambda: "f" * 64)
    with pytest.raises(ValueError, match="TABLE_SOURCE_POLICY_MISMATCH"):
        spp.table_verifier(digest)


def test_new_analysis_pin_preserves_every_v29b_semantic_field():
    from proofops.application import analysis_profile as p
    from proofops.domain.provenance import canonical_hash

    assert (
        p.policy_for(p.V2_PROFILE, pinned_hash=canonical_hash(p.FINALS_I29B_POLICY))
        == p.FINALS_I29B_POLICY
    )
    candidate = p.SPP_POLICY
    assert candidate == p.FINALS_I29B_POLICY | dict(
        integration_profile="spp_finals_parse_v1", parser_execution_policy="spp-parse-v1"
    )
    pin = canonical_hash(candidate)
    assert p.policy_for(p.V2_PROFILE, pinned_hash=pin) == candidate
    assert p.publication_policy_for(p.V2_PROFILE, pinned_hash=pin) == candidate


@pytest.mark.parametrize("failure", [None, "BUDGET_EXHAUSTED", "UPSTAGE_HTTP_401"])
def test_first_wave_overlaps_local_preserves_context_and_terminal_stop(
    tmp_path, monkeypatch, failure
):
    from contextvars import ContextVar
    from threading import Barrier, Lock
    from types import SimpleNamespace

    from proofops.adapters.parsing import h6_local_pages_v2, hx6_upstage
    from proofops.adapters.parsing.spp_execution import PageRequests
    from proofops.domain.provenance import canonical_hash

    scope = ContextVar("spp_test_scope", default=None)
    scope.set("tenant-run-lease")
    barrier, lock = Barrier(5, timeout=5), Lock()
    calls = []
    source = SimpleNamespace(sha256="a" * 64, content=b"source")
    profile = SimpleNamespace(claim_physical_pages=tuple(range(1, 9)), mixed_ocr_max_pages=0)
    monkeypatch.setattr(h6_local_pages_v2, "subset", lambda content, pages: bytes(pages))
    monkeypatch.setattr(hx6_upstage, "native_pages", lambda *a: [])
    monkeypatch.setattr(
        hx6_upstage,
        "candidate_batch",
        lambda *a, **k: (
            SimpleNamespace(blocks=[SimpleNamespace(source=SimpleNamespace(raw_text="text"))]),
            {},
        ),
    )

    def send(payload, **kwargs):
        assert scope.get() == "tenant-run-lease"
        page = payload[0]
        with lock:
            calls.append(page)
        if page <= 4:
            barrier.wait()
        if page == 4 and failure:
            raise ValueError(failure)
        raw = [page]
        return dict(raw_batches=raw, response_sha256=canonical_hash(raw))

    requests = PageRequests(
        source, profile, tuple(range(1, 9)), tmp_path, SimpleNamespace(parse_async=send)
    )
    requests.execute_local(lambda: barrier.wait())
    _, routing, output = hx6_upstage.recover(
        source,
        profile,
        tuple(range(1, 9)),
        (),
        requests,
        config_hash="test",
        claim_layout=True,
        page_workers=4,
    )
    assert sorted(calls) == list(range(1, 5 if failure else 9))
    assert routing["provider_pages"] == list(range(1, 4 if failure else 9))
    assert len(output["failed_batches"]) == (5 if failure else 0)
    assert not any(record["cache_hit"] for record in output["page_records"])


def test_page_cache_reuses_decoding_and_closes_at_source_boundary(tmp_path):
    from proofops.adapters.parsing.spp_execution import LocalPageCache

    from tests.acceptance.test_parsing import pdf

    path = tmp_path / "source.pdf"
    path.write_bytes(pdf())
    cache = LocalPageCache()
    with cache.open(path) as first:
        words = first.pages[0].extract_words()
    with cache.open(path) as second:
        assert second is first
        assert second.pages[0].extract_words() == words
    cache.close()
    assert first.stream.closed


@pytest.mark.parametrize("fault", ["corrupt_cache", "subset_failure"])
def test_preparation_errors_stay_at_original_page_recovery_boundary(tmp_path, monkeypatch, fault):
    from types import SimpleNamespace

    from proofops.adapters.parsing import h6_local_pages_v2, hx6_upstage
    from proofops.adapters.parsing.spp_execution import PageRequests

    source = SimpleNamespace(content=b"source", sha256="a" * 64)
    profile = SimpleNamespace(claim_physical_pages=(1,), mixed_ocr_max_pages=0)
    probe = SimpleNamespace(parse_async=lambda *a, **k: pytest.fail("no paid request"))
    requests = PageRequests(source, profile, (1,), tmp_path, probe)
    if fault == "corrupt_cache":
        requests._path((1,), "standard").write_text('{"raw_batches":[],"response_sha256":"bad"}')
    else:

        def invalid(*args):
            raise ValueError("PARSER_GEOMETRY_INVALID")

        monkeypatch.setattr(h6_local_pages_v2, "subset", invalid)
    executed = []
    requests.execute_local(lambda: executed.append(True))
    assert executed == [True]
    monkeypatch.setattr(hx6_upstage, "native_pages", lambda *a: [1])
    _, routing, output = hx6_upstage.recover(
        source, profile, (1,), (), requests, config_hash="test", claim_layout=True, page_workers=4
    )
    assert routing["local_pages"] == [1]
    assert len(output["failed_batches"]) == 1


def test_hosted_candidate_reaches_existing_replica_and_source_paths(tmp_path):
    from proofops.application.analysis_profile import SPP_POLICY

    from tests.integration.test_i28_profile import test_hosted_child_preserves_integrated_pins

    test_hosted_child_preserves_integrated_pins(tmp_path, SPP_POLICY)


def test_real_parser_candidate_roundtrip_and_historical_output(tmp_path):
    import json
    from hashlib import sha256
    from uuid import uuid4

    from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser, ParseFailure
    from proofops.application.ingest.graph_fusion import SourceArtifact
    from proofops.domain.provenance import canonical_hash

    from deploy.public.offline_fixture import fake_parse, source_pdf
    from tests.acceptance.test_parsing import JAVA

    content = source_pdf()
    source = SourceArtifact(
        str(uuid4()), str(uuid4()), str(uuid4()), sha256(content).hexdigest(), "v1", content
    )
    original = ParserProfile(
        str(uuid4()),
        java_executable=JAVA,
        physical_pages=(1, 2),
        claim_physical_pages=(1, 2),
        parser_mode="mixed-v1",
        local_resource_policy="selected-pdf-h6-v2",
        failure_policy="s3_partial-v7",
    )

    class Provider:
        def parse_async(self, content, **kwargs):
            raw = [fake_parse(content, "standard")]
            return dict(raw_batches=raw, response_sha256=canonical_hash(raw))

    graphs = []
    for arm, policy in (("baseline", None), ("candidate", "spp-parse-v1")):
        profile = replace(original, parse_manifest_id=str(uuid4()), execution_policy=policy)
        parser = OpenDataLoaderParser(tmp_path / arm, upstage_probe=Provider())
        graph = parser.parse(source, profile, tenant_id=source.tenant_id)
        assert parser.load_verified(source, profile, tenant_id=source.tenant_id) == graph
        with pytest.raises(ParseFailure):
            parser.load_verified(
                replace(source, content=content + b"changed"), profile, tenant_id=source.tenant_id
            )
        graphs.append(graph)
        if policy:
            manifest = next((tmp_path / arm / source.tenant_id).rglob("manifest.json"))
            value = json.loads(manifest.read_bytes())
            value["parser_profile"]["execution_policy"] = None
            manifest.chmod(0o600)
            manifest.write_text(json.dumps(value))
            with pytest.raises(ParseFailure):
                parser.load_verified(source, profile, tenant_id=source.tenant_id)

    def raw_candidates(graph):
        return sorted(
            (
                b.kind,
                b.source.physical_page,
                b.source.raw_text,
                b.bbox,
                b.context,
                b.row_number,
                b.column_number,
                b.row_span,
                b.column_span,
            )
            for batch in graph.candidates
            for b in batch.blocks
        )

    assert raw_candidates(graphs[0]) == raw_candidates(graphs[1])
    assert all(b.quality != "verified" for g in graphs for b in g.blocks)
