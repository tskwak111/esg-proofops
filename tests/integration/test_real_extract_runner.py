"""Bounded real extraction: fake transport, real worker and claim replay."""

import json
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import pytest
from proofops.adapters.local.claim_store import LocalClaimStore
from proofops.adapters.local.run_store import LocalSQLiteRunStore
from proofops.application.ingest.graph_fusion import (
    CandidateBatch,
    CandidateBlock,
    fuse_candidates,
)
from proofops.domain.documents import NativeSource, PageGeometry
from proofops_agent.upstage_extraction import UpstageClaimExtractor
from proofops_worker.extract_runner import LocalExtractRunner

from tests.acceptance.test_upload import TENANT

MANIFEST = "44444444-4444-4444-8444-444444444444"


class FakeProbe:
    """Real reserve/settle ledger, stub only the HTTP response."""

    def __init__(self, content=None, error=None):
        from tempfile import TemporaryDirectory

        from proofops.adapters.local.upstage import UpstageProbe

        self._directory = TemporaryDirectory()
        self._client = UpstageProbe("test-only-key", Path(self._directory.name) / "budget.sqlite3")
        self.ledger = self._client.ledger
        self.content, self.error, self.calls = content, error, []
        self._client._post = self._post

    def _post(self, body):
        if self.error is not None:
            raise self.error
        return dict(
            id="test-provider",
            model="solar-pro3",
            usage=dict(prompt_tokens=50, completion_tokens=10),
            choices=[dict(finish_reason="stop", message=dict(content=self.content))],
        )

    def complete(self, system, user_json, *, request_id, max_tokens=1024, json_mode=False):
        self.calls.append(dict(request_id=request_id, max_tokens=max_tokens, user_json=user_json))
        if str(self.error) in {
            "BUDGET_EXHAUSTED",
            "PRICE_RECHECK_REQUIRED",
            "PROBE_REQUEST_TOO_LARGE",
        }:
            raise self.error
        return self._client.complete(
            system, user_json, request_id=request_id, max_tokens=max_tokens, json_mode=json_mode
        )


def graph_of_kinds(kinds, source_sha=None, doc_version=None, parse_manifest=None):
    run = str(uuid5(UUID(MANIFEST), "synthetic-real-test"))
    sha = source_sha or "a" * 64
    doc_ver = doc_version or "33333333-3333-4333-8333-333333333333"
    pm = parse_manifest or MANIFEST
    batch = CandidateBatch(
        TENANT,
        doc_ver,
        pm,
        sha,
        run,
        "synthetic-text",
        "1",
        "synthetic",
        "b" * 64,
        tuple(
            CandidateBlock(
                kind,
                NativeSource(
                    doc_ver,
                    pm,
                    run,
                    str(i),
                    i % 3 + 1,
                    None,
                    (10, 10 + (i // 3) * 70, 590, 50 + (i // 3) * 70),
                    "pdf_bottom_left_points",
                    f"paragraph block {i} with carbon emission claim text {i}",
                    0,
                    len(f"paragraph block {i} with carbon emission claim text {i}"),
                ),
                PageGeometry(600, 800, 0, (0, 0, 600, 800)),
            )
            for i, kind in enumerate(kinds)
        ),
        synthetic=False,
    )
    return fuse_candidates((batch,), tenant_id=TENANT)


def real_setup(tmp_path, monkeypatch, *, limit=2, probe=None):
    from proofops.application.registry import artifact_sha256

    from tests.integration import test_run_lifecycle as lifecycle
    from tests.integration.test_local_parser_runner import runner_setup
    from tests.integration.test_upstage_runtime import profiles

    probe = probe or FakeProbe('{"claims":[]}')
    extractor = UpstageClaimExtractor(probe, tmp_path / "receipts")
    original = lifecycle.setup

    def setup(directory):
        service, body = original(directory)
        service.extraction_mode = "upstage_probe"
        service.extraction_profile = extractor.profile
        service.extraction_limits = dict(max_calls=limit, max_output_tokens=1024)
        body.update(scope="declared_subset", selected_pages=[1, 2, 3])
        pair = profiles()
        document = service.uploads.version_snapshot(TENANT, body["document_version_id"])
        pair[1]["allowed_source_sha256"] = [document["sha256"]]
        pair[1]["allowed_document_rights"] = [document["metadata"]["rights_profile_id"]]
        for kind, artifact, field in [
            ("runtime", pair[0], "runtime_binding_id"),
            ("consent", pair[1], "consent_profile_id"),
        ]:
            artifact[field] = str(uuid4())
            body[field] = artifact[field]
            service.registry.with_option(
                TENANT,
                kind,
                artifact[field],
                "test",
                status="approved",
                version="1",
                artifact=artifact,
                sha256=artifact_sha256(artifact),
                approved_by="test-user",
                approved_at=artifact["approved_at"],
                local_synthetic=False,
            )
        return service, body

    monkeypatch.setattr(lifecycle, "setup", setup)
    service, run_id, parser, now, _ = runner_setup(tmp_path, monkeypatch)
    assert parser.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    runner = LocalExtractRunner(
        service.store,
        service.uploads,
        parser.parser,
        extractor=extractor,
        telemetry=parser.telemetry,
        clock=lambda: now[0],
    )
    return service, run_id, runner, now, probe


def inject_graph(monkeypatch, service, run_id, kinds):
    from proofops.application.ports.jobs import JobMessage

    snapshot = service.store.snapshot(TENANT, run_id)
    current = service.store.jobs.get_run(TENANT, run_id)
    parsed = json.loads(service.store.jobs.read_checkpoint(JobMessage(**current["parse_job"])))
    graph = graph_of_kinds(
        kinds,
        source_sha=snapshot["document"]["sha256"],
        doc_version=snapshot["document"]["version_id"],
        parse_manifest=parsed["parse_manifest_id"],
    )
    for module in (
        "proofops.adapters.local.claim_store",
        "proofops.adapters.local.run_artifacts",
        "proofops_worker.extract_runner",
    ):
        monkeypatch.setattr(module + ".load_run_graph", lambda *a, **k: graph)
    return graph


@pytest.mark.parametrize("limit", [1, 2, 20])
def test_paragraph_limit_and_immutable_replay(tmp_path, monkeypatch, limit):
    from tests.integration.test_local_extract_runner import extract_message

    service, run_id, runner, now, probe = real_setup(tmp_path, monkeypatch, limit=limit)
    inject_graph(monkeypatch, service, run_id, ["paragraph"] * 25 + ["table"])
    snapshot = service.store.snapshot(TENANT, run_id)
    message = extract_message(service, run_id, now[0])
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    assert len(probe.calls) == limit
    discovery = runner.claims.load(TENANT, run_id)
    assert {"non_paragraph_kind", "beyond_extraction_limit"} <= {
        e.reason for e in discovery.exclusions
    }
    reopened = LocalClaimStore(
        LocalSQLiteRunStore(service.store.path), service.uploads, runner.parser
    )
    assert reopened.load(TENANT, run_id) == discovery
    assert service.store.snapshot(TENANT, run_id) == snapshot
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "pending_downstream"
    assert len(probe.calls) == limit
    usage = service.store.jobs.get_usage(message, fencing_token=1)
    assert usage["model_calls"] == usage["settled_calls"] == limit
    assert usage["input_tokens"] == 50 * limit
    assert usage["token_usage_complete"] is True
    cost = service.cost(TENANT, run_id)
    assert cost["attempt_count"] == limit
    assert cost["input_tokens"] == 50 * limit
    assert cost["amount"] == usage["cost_with_vat_reserve_usd"]
    assert cost["cost_status"] == "known"


def test_invalid_model_output_consumes_slot(tmp_path, monkeypatch):
    probe = FakeProbe('{"claims":["invented quote"]}')
    service, run_id, runner, _, _ = real_setup(tmp_path, monkeypatch, limit=1, probe=probe)
    inject_graph(monkeypatch, service, run_id, ["paragraph"] * 3)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    assert len(probe.calls) == 1
    assert not runner.claims.load(TENANT, run_id).claims
    assert runner.extractor.usage["settled_calls"] == 1


@pytest.mark.parametrize(
    "code,reserved",
    [
        ("BUDGET_EXHAUSTED", 0),
        ("PRICE_RECHECK_REQUIRED", 0),
        ("UPSTAGE_HTTP_429", 1),
        ("UPSTAGE_HTTP_503", 1),
        ("UPSTAGE_REQUEST_FAILED", 1),
        ("UPSTAGE_RECEIPT_INVALID_RESERVATION_RETAINED", 1),
    ],
)
def test_hard_stop_and_unsettled_accounting(tmp_path, monkeypatch, code, reserved):
    from tests.integration.test_local_extract_runner import extract_message

    probe = FakeProbe(error=ValueError(code))
    service, run_id, runner, now, _ = real_setup(tmp_path, monkeypatch, probe=probe)
    inject_graph(monkeypatch, service, run_id, ["paragraph"] * 3)
    message = extract_message(service, run_id, now[0])
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "failed"
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "idle"
    assert len(probe.calls) == 1
    usage = service.store.jobs.get_usage(message, fencing_token=1)
    assert usage["reserved_calls"] == reserved
    assert usage["unsettled_calls"] == reserved
    assert usage["token_usage_complete"] is (not reserved)
    cost = service.cost(TENANT, run_id)
    assert cost["amount"] is None
    assert cost["cost_status"] == "unknown_cost"
    assert cost["attempt_count"] == reserved
    if reserved:
        assert usage["cost_with_vat_reserve_usd"] == "unknown"


def test_expired_authorization_blocks_transport(tmp_path, monkeypatch):
    service, run_id, runner, now, probe = real_setup(tmp_path, monkeypatch)
    inject_graph(monkeypatch, service, run_id, ["paragraph"])
    now[0] += 10 * 86400
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "failed"
    assert not probe.calls


def test_paragraph_selection_stable_across_source_uuids(tmp_path, monkeypatch):
    """Same content/geometry with different source UUIDs must select the same paragraph.

    Regression for UUID-dependent capping: legacy discovery visits blocks in
    ``(page_num, source_id)`` order, so a bare call-count cap picks different
    paragraphs when only manifest/source UUIDs change. The worker now
    pre-selects a stable eligible set by canonical ``(page, bbox, text)``
    before the legacy discovery loop.
    """

    import json as _json
    from dataclasses import replace

    from proofops.adapters.local.claim_store import claim_scope
    from proofops_worker.extract_runner import select_stable_paragraph_sources

    kinds = ["paragraph"] * 6

    def remap(graph, *, reverse):
        count = len(graph.blocks)

        def remapped_id(index):
            key = (count - 1 - index) if reverse else index
            return f"11111111-1111-4111-8111-{key:012d}"

        blocks = tuple(
            replace(block, source_id=remapped_id(index))
            for index, block in enumerate(
                sorted(
                    graph.blocks, key=lambda b: (b.page_num, tuple(b.bbox or ()), b.normalized_text)
                )
            )
        )
        return replace(graph, blocks=blocks)

    def repatch(graph):
        for module in (
            "proofops.adapters.local.claim_store",
            "proofops.adapters.local.run_artifacts",
            "proofops_worker.extract_runner",
        ):
            monkeypatch.setattr(module + ".load_run_graph", lambda *a, **k: graph)

    def probe_texts(probe):
        return [
            _json.loads(call["user_json"])["untrusted_document_data"]["text"]
            for call in probe.calls
        ]

    service_a, run_a, runner_a, _, probe_a = real_setup(tmp_path / "run_a", monkeypatch, limit=1)
    base_a = inject_graph(monkeypatch, service_a, run_a, kinds)
    graph_a = remap(base_a, reverse=False)
    repatch(graph_a)
    assert runner_a.run_once(tenant_id=TENANT, run_id=run_a) == "committed"
    texts_a = probe_texts(probe_a)
    assert len(texts_a) == 1

    service_b, run_b, runner_b, _, probe_b = real_setup(tmp_path / "run_b", monkeypatch, limit=1)
    base_b = inject_graph(monkeypatch, service_b, run_b, kinds)
    graph_b = remap(base_b, reverse=True)
    repatch(graph_b)
    assert runner_b.run_once(tenant_id=TENANT, run_id=run_b) == "committed"
    texts_b = probe_texts(probe_b)
    assert len(texts_b) == 1

    # The regression is meaningful: legacy (page, source_id) visitation order
    # differs, and a bare call-count cap would pick different paragraphs.
    def _legacy_key(block):
        return (block.page_num, block.source_id)

    def legacy_order(graph):
        return [b.source_id for b in sorted(graph.blocks, key=_legacy_key)]

    legacy_a = legacy_order(graph_a)
    legacy_b = legacy_order(graph_b)
    assert legacy_a != legacy_b
    legacy_first_a = sorted(graph_a.blocks, key=_legacy_key)[0]
    legacy_first_b = sorted(graph_b.blocks, key=_legacy_key)[0]
    assert legacy_first_a.normalized_text != legacy_first_b.normalized_text

    # Stable helper agrees at canonical granularity across the UUID remap.
    scope_a = claim_scope(service_a.store.snapshot(TENANT, run_a), graph_a)
    scope_b = claim_scope(service_b.store.snapshot(TENANT, run_b), graph_b)
    eligible_a = select_stable_paragraph_sources(graph_a, scope_a, 1)
    eligible_b = select_stable_paragraph_sources(graph_b, scope_b, 1)

    def canonical(graph, ids):
        return sorted(
            (
                block.page_num,
                tuple(block.bbox) if block.bbox is not None else None,
                block.normalized_text,
            )
            for block in graph.blocks
            if block.source_id in ids
        )

    assert canonical(graph_a, eligible_a) == canonical(graph_b, eligible_b)
    # The bounded worker actually called the same canonical paragraph twice.
    assert texts_a == texts_b == [canonical(graph_a, eligible_a)[0][2]]


def test_accounting_filters_operation_and_manifest(tmp_path):
    from tests.integration.test_upstage_extraction import make_extractor

    probe = FakeProbe('{"claims":[]}')
    extractor, first = make_extractor(probe, tmp_path)
    extractor.extract(first)
    checkpoint = extractor.usage_checkpoint()
    second = dict(first, parse_manifest_id=str(uuid4()))
    extractor.extract(second)
    assert extractor.cumulative_usage(since=checkpoint)["settled_calls"] == 1
    assert (
        extractor.cumulative_usage(parse_manifest_id=first["parse_manifest_id"])["settled_calls"]
        == 1
    )
    assert (
        extractor.cumulative_usage(since=checkpoint, parse_manifest_id=first["parse_manifest_id"])[
            "settled_calls"
        ]
        == 0
    )


def test_request_usage_shared_accounting(tmp_path):
    """Shared ledger query: distinct IDs, unsettled unknown, foreign ignored, read-only."""
    import sqlite3

    # Build a controlled ledger with one settled, one unsettled reservation.
    from proofops.adapters.local.upstage import UpstageProbe, request_usage

    ledger = tmp_path / "shared?#budget.sqlite3"
    client = UpstageProbe("test-only-key", ledger)
    settled_id, unsettled_id = "req-settled-1", "req-unsettled-1"
    client._reserve(settled_id, {"m": settled_id})
    client._reserve(unsettled_id, {"m": unsettled_id})
    with sqlite3.connect(ledger) as db:
        receipt = db.execute(
            "SELECT receipt FROM probe_calls WHERE request_id=?", (settled_id,)
        ).fetchone()
        assert receipt == (None,)
    # Settle manually with a minimal valid receipt.
    with sqlite3.connect(ledger) as db:
        db.execute(
            "UPDATE probe_calls SET committed=?, receipt=? WHERE request_id=?",
            (
                "0.0000099",
                json.dumps({"input_tokens": 50, "output_tokens": 10}),
                settled_id,
            ),
        )
    foreign_id = "preflight-no-reservation"
    usage = request_usage(ledger, [settled_id, settled_id, unsettled_id, foreign_id])
    assert usage["model_calls"] == 2  # distinct supplied IDs only; foreign ignored
    assert usage["reserved_calls"] == 2
    assert usage["settled_calls"] == 1
    assert usage["unsettled_calls"] == 1
    assert usage["token_usage_complete"] is False
    assert usage["cost_with_vat_reserve_usd"] == "unknown"
    assert usage["input_tokens"] == 50
    assert usage["output_tokens"] == 10
    # Unsettled reservation preserved in committed_or_reserved_usd.
    from decimal import Decimal

    assert Decimal(usage["committed_or_reserved_usd"]) == Decimal("0.0000099") + Decimal("1.00")
    assert "extractor_calls" not in usage
    # Empty IDs return zero without opening a ledger; missing ledger stays missing.
    missing = tmp_path / "missing-budget.sqlite3"
    empty = request_usage(missing, [])
    assert empty["model_calls"] == 0 and empty["token_usage_complete"] is True
    assert empty["committed_or_reserved_usd"] == "0"
    assert not missing.exists()
    # Non-empty query on missing ledger fails closed without creating a file.
    with pytest.raises(ValueError, match="ACCOUNTING_UNAVAILABLE"):
        request_usage(missing, [settled_id])
    assert not missing.exists()
    # Global totals never leak: extra ledger row not in supplied IDs is ignored.
    client._reserve("req-other-global", {"m": "other"})
    again = request_usage(ledger, [settled_id, unsettled_id])
    assert again["model_calls"] == 2
    assert Decimal(again["committed_or_reserved_usd"]) == Decimal(
        usage["committed_or_reserved_usd"]
    )


def test_long_heading_reaches_real_extractor_without_reclassifying_source(tmp_path, monkeypatch):
    """Real-report regression: prose styled as heading must not silently miss extraction."""
    from dataclasses import replace

    service, run_id, runner, _, probe = real_setup(tmp_path, monkeypatch, limit=1)
    graph = inject_graph(monkeypatch, service, run_id, ["heading"])
    text = (
        "삼성생명은 기후변화 대응 전략을 수립하고, 온실가스 감축과 에너지 전환을 위한 노력을 "
        "지속적으로 추진하고 있습니다. 또한 기후리스크를 사전에 식별하고 "
        "대응할 수 있는 체계를 강화합니다."
    )
    batch = graph.candidates[0]
    block = batch.blocks[0]
    updated = replace(block, source=replace(block.source, raw_text=text, char_end=len(text)))
    graph = fuse_candidates((replace(batch, blocks=(updated,)),), tenant_id=TENANT)
    for module in (
        "proofops.adapters.local.claim_store",
        "proofops.adapters.local.run_artifacts",
        "proofops_worker.extract_runner",
    ):
        monkeypatch.setattr(module + ".load_run_graph", lambda *a, **k: graph)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    assert len(probe.calls) == 1
    data = json.loads(probe.calls[0]["user_json"])["untrusted_document_data"]
    assert data["text"] == text
    assert graph.blocks[0].kind == "heading"
