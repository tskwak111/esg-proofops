from dataclasses import asdict, replace
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from proofops.application.claims import ClaimScope, ExtractionOutputError, discover_atomic_claims
from proofops.application.input_failures import (
    HOSTED_MAX_UPLOAD_BYTES,
    POLICY,
    TABLE_ERRORS,
)
from proofops.domain.provenance import canonical_hash
from proofops_worker.extract_runner import _candidate_extract


def policy():
    return dict(input_failure_policy=POLICY, input_failure_policy_sha256=canonical_hash(POLICY))


@pytest.mark.parametrize("code", sorted(TABLE_ERRORS))
def test_owned_table_failure_is_unknown_only_with_hx5_pin(code):
    def fail(packet):
        raise ValueError(code)

    live = SimpleNamespace(extract=fail)
    packet = dict(untrusted_document_data=dict(kind="table"))
    with pytest.raises(ExtractionOutputError, match="TABLE_GRID_UNREADABLE"):
        _candidate_extract(live, packet, dict(analysis_profile_policy=policy()))
    for snapshot in (
        {},
        dict(analysis_profile_policy=policy() | dict(input_failure_policy_sha256="0" * 64)),
    ):
        with pytest.raises(ValueError) as error:
            _candidate_extract(live, packet, snapshot)
        assert not isinstance(error.value, ExtractionOutputError)
    with pytest.raises(ValueError) as error:
        _candidate_extract(
            live,
            dict(untrusted_document_data=dict(kind="paragraph")),
            dict(analysis_profile_policy=policy()),
        )
    assert not isinstance(error.value, ExtractionOutputError)


@pytest.mark.parametrize(
    "code", ["UPSTAGE_CONTEXT_IDENTITY_MISMATCH", "EXTRACTION_PB1_REPLAY_MISMATCH"]
)
def test_hx5_never_recovers_integrity_failure(code):
    def fail(packet):
        raise ValueError(code)

    with pytest.raises(ValueError) as error:
        _candidate_extract(
            SimpleNamespace(extract=fail),
            dict(untrusted_document_data=dict(kind="table")),
            dict(analysis_profile_policy=policy()),
        )
    assert not isinstance(error.value, ExtractionOutputError)


def test_failed_table_does_not_discard_neighboring_claims():
    from proofops_agent.extraction import SyntheticClaimExtractor

    from tests.unit.test_k5_context import case

    graph, _ = case(
        ["invalid table", "2024년 온실가스 배출량을 10% 줄였습니다."],
        (1, "2024년 온실가스 배출량을 10% 줄였습니다."),
        kinds=["table", "paragraph"],
    )
    inner = SyntheticClaimExtractor()

    def extract(packet):
        if packet["untrusted_document_data"]["kind"] == "table":
            raise ValueError("J8_CELL_GEOMETRY_INVALID")
        return inner.extract(packet)

    class Bound:
        profile = inner.profile

        def extract(self, packet):
            return _candidate_extract(
                SimpleNamespace(extract=extract), packet, dict(analysis_profile_policy=policy())
            )

    result = discover_atomic_claims(
        graph,
        ClaimScope(graph.tenant_id, graph.document_version_id, graph.parse_manifest_id),
        extractor=Bound(),
    )
    assert result.claims and all(
        c.source_refs[0].source_id == graph.blocks[1].source_id for c in result.claims
    )
    assert any(
        e.source_id == graph.blocks[0].source_id and e.state == "unknown" for e in result.exclusions
    )
    assert any(
        r.source_id == graph.blocks[0].source_id and r.status == "failed" for r in result.receipts
    )


@pytest.mark.parametrize(
    "code", ["OCR_PENDING_OR_FAILED", "OCR_RENDER_LIMIT", "OCR_TABLE_RECEIPT_MISMATCH"]
)
def test_scope_attestation_recovers_only_unavailable_spans(monkeypatch, code):
    from proofops.adapters.local import k9_scope_sources as scope
    from proofops.adapters.local import upstage_ocr_profile_v13
    from proofops.application.tagging.k9_contract import BINDING_POLICY

    from tests.unit.test_k5_context import case

    source = b"immutable-pdf-fixture"
    graph, first = case(
        ["직접 배출(Scope 1)은 감축되었습니다.", "간접 배출(Scope 2)은 감축되었습니다."],
        (0, "직접 배출(Scope 1)은 감축되었습니다."),
    )
    graph = replace(graph, source_sha256=sha256(source).hexdigest())
    first = replace(first, source_sha256=graph.source_sha256)
    second = replace(
        first,
        claim_id=str(uuid4()),
        quote=graph.blocks[1].raw_text,
        source_refs=(graph.blocks[1].source_ref(),),
    )
    calls = []

    def attest(graph, source, refs, **kwargs):
        calls.append(refs)
        if refs[0].source_id == graph.blocks[0].source_id:
            raise ValueError(code)
        return dict(
            records=[dict(ref=asdict(refs[0]), status="unresolved", reason="native_mismatch")]
        )

    monkeypatch.setattr(
        upstage_ocr_profile_v13,
        "for_run",
        lambda run_id: SimpleNamespace(attest_claim_spans=attest),
    )
    monkeypatch.setattr(scope, "scope_definition_refs", lambda claim, graph: claim.source_refs)
    options = dict(local_implementation_binding_policy=BINDING_POLICY, **policy())
    if code == "OCR_TABLE_RECEIPT_MISMATCH":
        with pytest.raises(ValueError, match=code):
            scope.scope_graph(
                graph,
                source,
                (first, second),
                tenant_id=graph.tenant_id,
                run_id=str(uuid4()),
                policy=options,
            )
        assert len(calls) == 1
    else:
        result, records = scope.scope_graph(
            graph,
            source,
            (first, second),
            tenant_id=graph.tenant_id,
            run_id=str(uuid4()),
            policy=options,
        )
        assert result is graph and len(calls) == 2
        assert all(not r["source_refs"] and r["rule_credit"] is False for r in records.values())
        receipt = next(iter(records.values()))["receipt"]
        assert all(r["status"] == "unresolved" for r in receipt["records"])
        assert (
            canonical_hash({k: v for k, v in receipt.items() if k != "artifact_sha256"})
            == receipt["artifact_sha256"]
        )


@pytest.mark.parametrize("password", ["", "secret"])
def test_scope_encryption_uses_ingest_gate_preserves_original(tmp_path, password):
    from evaluation.report_scope import inspect
    from evaluation.report_sections import inspect as inspect_sections
    from tests.acceptance.test_upload_security import pdf

    data = pdf(password=password)
    source = tmp_path / "encrypted.pdf"
    source.write_bytes(data)
    for read in (inspect, inspect_sections):
        if password:
            with pytest.raises(ValueError, match="PDF_PASSWORD_REQUIRED"):
                read(source)
        else:
            result = read(source)
            assert result["source_sha256"] == sha256(data).hexdigest()
            assert result["input_security"]["encrypted"] is True
            assert result["input_security"]["original_inspection"] == "complete"
        assert source.read_bytes() == data


def test_scope_empty_password_still_rejects_active_content(tmp_path):
    from evaluation.report_scope import inspect
    from tests.acceptance.test_upload_security import pdf

    source = tmp_path / "unsafe.pdf"
    source.write_bytes(pdf(password="", action=("/JavaScript", "/JS", "alert")))
    with pytest.raises(ValueError, match="PDF_INVALID"):
        inspect(source)


def test_scope_accepts_hosted_size_and_rejects_excess_before_read(tmp_path, monkeypatch):
    from evaluation import scope_input as module
    from tests.acceptance.test_upload_security import pdf

    source = tmp_path / "large.pdf"
    source.write_bytes(pdf())
    with source.open("ab") as stream:
        stream.truncate(100 * 1024 * 1024 + 1)
    with module.scope_input(source) as (analysis, digest, metadata):
        assert analysis == source and not metadata
    with source.open("ab") as stream:
        stream.truncate(HOSTED_MAX_UPLOAD_BYTES + 1)
    monkeypatch.setattr(module, "PdfReader", lambda *args: pytest.fail("read oversized input"))
    with pytest.raises(ValueError, match="150 MiB"):
        with module.scope_input(source):
            pass
