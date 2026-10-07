"""Real context gates and callers; only rendered OCR is substituted, no paid calls."""

import json
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from proofops.adapters.local import claim_source_policies as policies
from proofops.adapters.local import claim_source_verification as base
from proofops.adapters.local import claim_span_typography as current
from proofops.adapters.local import selected_cell_table_verification as selected_cell
from proofops.adapters.local import table_span_source_verification as tables
from proofops.adapters.local.tag_store import LocalTagStore
from proofops.application.evidence.binding import ClaimContext
from proofops.application.evidence.report_level import GRI_ASSURED_PAGE_V1
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.evidence.span_citations import span_verified_graph
from proofops.application.ingest.graph_fusion import fuse_candidates
from proofops.application.reviews import ReviewRejected
from proofops.application.tagging.consensus import form_consensus
from proofops.application.tagging.report_level_link import (
    POLICY,
    POLICY_HASH,
    apply_report_level_link,
    strict_fallback,
)
from proofops.application.tagging.tracks import TrackCandidate
from proofops.domain.provenance import canonical_hash as H

from tests.acceptance.test_citations import RUN, TENANT
from tests.acceptance.test_parsing import candidate
from tests.acceptance.test_report_level_verification import _management_body
from tests.acceptance.test_reviews import workspace
from tests.integration.test_ai_delegated_review import _actor
from tests.integration.test_claim_span_typography import dot_inputs, render_as_bullet, winansi_pdf
from tests.integration.test_local_tag_runner import tag_message, verified_setup
from tests.integration.test_native_table_admission import fixture, ocr


def historical_policy():
    return json.loads(
        Path("tests/fixtures/pipeline/claim-span-typography-history/policy.json").read_text()
    )


def source_store(source, graph, policy, *, jobs=None):
    snapshot = dict(
        tenant_id=TENANT,
        run_id=RUN,
        document={"version_id": graph.document_version_id},
        claim_source_policy=policy,
    )
    store = SimpleNamespace(snapshot=lambda *_: deepcopy(snapshot), jobs=jobs)
    return LocalTagStore(store, SimpleNamespace(read_original=lambda *_: source), None), snapshot


def mixed_case(monkeypatch):
    source, graph = fixture()
    batch = graph.candidates[0]
    original = next(b for b in batch.blocks if b.source.raw_text == "Year")
    paragraph = replace(
        original,
        kind="paragraph",
        source=replace(original.source, source_native_id="paragraph"),
        table_native_id=None,
        row_number=None,
        column_number=None,
    )
    graph = fuse_candidates((replace(batch, blocks=(*batch.blocks, paragraph)),), tenant_id=TENANT)
    refs = tuple(
        b.source_ref()
        for b in graph.blocks
        if b.kind == "paragraph" or (b.kind == "table_cell" and b.raw_text == "79")
    )
    refs = tuple(sorted(refs, key=lambda ref: ref.quote != "Year"))
    monkeypatch.setattr(base, "_rendered_text", ocr)
    monkeypatch.setattr(selected_cell, "_rendered_cell", ocr)
    monkeypatch.setattr(tables, "_rendered_text", ocr)
    inputs = SimpleNamespace(
        run_id=RUN,
        original=graph,
        context=SimpleNamespace(
            claim=SimpleNamespace(
                tenant_id=TENANT, document_version_id=graph.document_version_id, claim_id="claim"
            )
        ),
    )
    return source, graph, refs, inputs


def test_review_appendix_reproduction_is_rejected(monkeypatch):
    source, graph, ref = dot_inputs()
    render_as_bullet(monkeypatch)
    store, _ = source_store(source, graph, historical_policy())
    inputs = SimpleNamespace(
        run_id=RUN,
        original=graph,
        context=SimpleNamespace(
            claim=SimpleNamespace(tenant_id=TENANT, document_version_id=graph.document_version_id)
        ),
    )
    with pytest.raises(ValueError, match="CLAIM_SOURCE_POLICY_MISMATCH"):
        store.verify_context_sources(inputs, (ref,))
    assert not getattr(graph, "verified_spans", ())


@pytest.mark.parametrize("mixed", [False, True])
@pytest.mark.parametrize("historical", [False, True])
def test_new_context_requires_current_publication_policy(monkeypatch, mixed, historical):
    source, graph, refs, inputs = mixed_case(monkeypatch)
    refs = refs if mixed else refs[:1]
    policy = historical_policy() if historical else current.claim_source_policy()
    store, snapshot = source_store(source, graph, policy)
    before = deepcopy(snapshot)
    if historical:
        with pytest.raises(ValueError, match="CLAIM_SOURCE_POLICY_MISMATCH"):
            store.verify_context_sources(inputs, refs)
    else:
        scoped, receipt = store.verify_context_sources(inputs, refs)
        assert all(r["status"] == "verified" for r in receipt["records"])
        assert receipt["artifact_sha256"] == H(
            {k: v for k, v in receipt.items() if k != "artifact_sha256"}
        )
        assert len(scoped.verified_spans) == len(refs)
        paragraph = receipt["receipts"]["paragraph"] if mixed else receipt
        assert paragraph["policy"] == policy
    assert store.store.snapshot(TENANT, RUN) == before
    assert not getattr(graph, "verified_spans", ())


@pytest.mark.parametrize("mixed", [False, True])
def test_only_stored_ref_bound_historical_receipt_replays(monkeypatch, mixed):
    source, graph, refs, inputs = mixed_case(monkeypatch)
    refs = refs if mixed else refs[:1]
    tag = {"report_level_review": []}
    jobs = SimpleNamespace(
        _transaction=lambda: nullcontext(object()),
        _get=lambda _db, _tenant, _run, kind, _key: {"tag_revision": 1}
        if kind == "claim_head"
        else tag,
    )
    store, snapshot = source_store(source, graph, historical_policy(), jobs=jobs)
    # Seed the receipt exactly as the old release published it. Replay below uses
    # the real dispatcher, stored-receipt checks, attesters and comparison.
    with monkeypatch.context() as old_release:
        old_release.setattr(policies, "publication_reader", policies.claim_source_reader)
        expected_graph, saved = store.verify_context_sources(inputs, refs)
    before = deepcopy(saved)
    with pytest.raises(ValueError, match="CONTEXT_SOURCE_REPLAY_MISMATCH"):
        store.verify_context_sources(inputs, refs, replay_receipt=saved)
    tag["report_level_review"] = [{"refs": [asdict(r) for r in refs], "source_receipt": saved}]
    scoped, actual = store.verify_context_sources(inputs, refs, replay_receipt=saved)
    assert actual is saved and actual == before
    assert scoped == expected_graph
    assert store.store.snapshot(TENANT, RUN) == snapshot
    with pytest.raises(ValueError, match="CONTEXT_SOURCE_REPLAY_MISMATCH"):
        store.verify_context_sources(
            inputs, (replace(refs[0], quote="tampered"),), replay_receipt=saved
        )
    assert saved == before


def test_review_new_historical_source_rejected_at_real_store(tmp_path, monkeypatch):
    source, graph, refs, _ = mixed_case(monkeypatch)

    def prepare(inputs):
        # Keep the established review fixture's management contract; source
        # validation uses this real PDF and graph rather than a mocked dispatcher.
        from tests.acceptance.test_report_level_verification import _setup_report_level_case

        inputs, _ = _setup_report_level_case(inputs)
        packet = inputs.packet.to_dict() | {"graph_sha256": H(asdict(graph))}
        packet = freeze_packet({k: v for k, v in packet.items() if k != "packet_sha256"})
        runs = tuple(
            replace(
                run,
                packet_sha256=packet.packet_sha256,
                graph_sha256=H(asdict(graph)),
                guarded=replace(run.guarded, packet_sha256=packet.packet_sha256),
            )
            for run in inputs.tag_runs
        )
        return replace(
            inputs,
            original=graph,
            packet=packet,
            tag_runs=runs,
            rule_context=replace(inputs.rule_context, packet_sha256=packet.packet_sha256),
            consensus=form_consensus(
                runs, packet=packet, rulepack=inputs.rulepack, tenant_id=TENANT, tag_revision=1
            ),
        )

    _, service, _, review, _, _, _ = workspace(tmp_path, prepare_inputs=prepare)
    store, snapshot = source_store(source, graph, historical_policy(), jobs=service.store.jobs)
    service.load_run_snapshot = store.store.snapshot
    service.verify_context_sources = store.verify_context_sources
    body = _management_body(
        dict(
            element_id="M3",
            state="present",
            evidence_refs=[asdict(refs[0])] * 3,
            normalized_value=None,
            credited_from=refs[0].source_id,
            reason_code=GRI_ASSURED_PAGE_V1,
        )
    )
    before = service.store.history(TENANT, RUN, review["claim_id"])
    with pytest.raises(ReviewRejected, match="REPORT_LEVEL_SOURCE_REJECTED") as failure:
        service.resolve_ai_delegated_review(
            _actor(),
            review["review_id"],
            body,
            '"1"',
            str(uuid4()),
            delegated_reviewer="regression",
            delegation_authority="explicit test",
        )
    assert str(failure.value.__cause__) == "CLAIM_SOURCE_POLICY_MISMATCH"
    assert service.store.history(TENANT, RUN, review["claim_id"]) == before
    assert store.store.snapshot(TENANT, RUN) == snapshot


@pytest.mark.parametrize("historical", [False, True])
def test_worker_supplementary_source_uses_publication_gate(tmp_path, monkeypatch, historical):
    service, run_id, runner, now, _ = verified_setup(tmp_path, monkeypatch)
    extraction, discovery, graph = runner.claims.load_evidence(TENANT, run_id)
    claim = discovery.claims[0]
    graph = replace(graph, blocks=tuple(replace(b, quality="unverified") for b in graph.blocks))
    graph = span_verified_graph(
        graph,
        tuple(replace(r, verification_state="verified") for r in claim.source_refs),
        "claim-source",
    )
    ref = replace(claim.source_refs[0], quote="1234", char_start=0, char_end=4)
    # Fixture source begins with 1234; keep the exact source offsets.
    start = graph.blocks[0].raw_text.index(ref.quote)
    ref = replace(ref, char_start=start, char_end=start + len(ref.quote))
    monkeypatch.setattr(runner.claims, "load_evidence", lambda *_: (extraction, discovery, graph))
    monkeypatch.setattr(base, "_rendered_text", ocr)
    monkeypatch.setattr(selected_cell, "_rendered_cell", ocr)
    runner.preliminary = lambda claim, graph: (
        TrackCandidate(claim, "management", None),
        ClaimContext(claim, {}),
        {},
    )
    snapshot = service.store.snapshot(TENANT, run_id)
    policy = historical_policy() if historical else current.claim_source_policy()
    execution_snapshot = snapshot | {
        "claim_source_policy": policy,
        "report_level_link": {
            "policy": POLICY,
            "policy_hash": POLICY_HASH,
            "refs": {"M3": [asdict(ref)] * 3},
        },
    }
    outcomes = []
    real_verify = runner.tags.verify_context_sources

    def observe(*args, **kwargs):
        try:
            result = real_verify(*args, **kwargs)
        except ValueError as exc:
            outcomes.append(str(exc))
            raise
        outcomes.append(result[1])
        return result

    monkeypatch.setattr(runner.tags, "verify_context_sources", observe)
    message = tag_message(service, run_id, now[0])
    lease = service.store.jobs.claim_job(
        message, owner="context-test", now=now[0], lease_seconds=300
    )
    runner._execute(lease, execution_snapshot, {"model_calls": 0, "synthetic_calls": 0})
    assert len(outcomes) == 1
    if historical:
        assert outcomes == ["CLAIM_SOURCE_POLICY_MISMATCH"]
    else:
        assert outcomes[0]["policy"] == policy
        assert all(record["status"] == "verified" for record in outcomes[0]["records"])
    assert service.store.snapshot(TENANT, run_id) == snapshot


@pytest.mark.parametrize("historical", [False, True])
def test_load_inputs_replays_saved_report_link_without_new_publication(
    tmp_path, monkeypatch, historical
):
    from tests.acceptance.test_report_level_verification import _setup_report_level_case

    text = "GRI Index 3-3 Topics 85 Independent Assurance 3-3 AA1000AS"
    source = winansi_pdf(text)
    batch = candidate("report-link", [("P", "paragraph", text, (70, 710, 580, 741), ())])
    batch = replace(
        batch,
        source_sha256=sha256(source).hexdigest(),
        blocks=tuple(
            replace(b, source=replace(b.source, printed_page_label="85")) for b in batch.blocks
        ),
    )
    graph = fuse_candidates((batch,), tenant_id=TENANT)
    block = graph.blocks[0]

    def ref(quote, start=None):
        start = text.index(quote) if start is None else start
        return block.source_ref(normalized_char_start=start, normalized_char_end=start + len(quote))

    claim_ref = replace(ref("GRI Index"), verification_state="verified")
    graph = span_verified_graph(graph, (claim_ref,), "claim-source")
    refs = (ref("3-3 Topics 85"), ref("Independent Assurance 3-3"), ref("AA1000AS"))
    policy = historical_policy() if historical else current.claim_source_policy()
    source_tags, snapshot = source_store(source, graph, policy)
    monkeypatch.setattr(base, "_rendered_text", ocr)
    monkeypatch.setattr(selected_cell, "_rendered_cell", ocr)
    config = json.loads(
        json.dumps(
            {
                "policy": POLICY,
                "policy_hash": POLICY_HASH,
                "refs": {"M3": [asdict(r) for r in refs]},
            }
        )
    )

    def prepare(inputs):
        inputs, _ = _setup_report_level_case(inputs)
        packet = inputs.packet.to_dict() | {"graph_sha256": H(asdict(graph))}
        packet = freeze_packet({k: v for k, v in packet.items() if k != "packet_sha256"})
        runs = tuple(
            replace(
                r,
                packet_sha256=packet.packet_sha256,
                graph_sha256=H(asdict(graph)),
                guarded=replace(r.guarded, packet_sha256=packet.packet_sha256),
            )
            for r in inputs.tag_runs
        )
        context = ClaimContext(
            replace(
                inputs.context.claim,
                document_version_id=graph.document_version_id,
                quote=claim_ref.quote,
                source_refs=(claim_ref,),
            ),
            {},
        )
        inputs = replace(
            inputs,
            original=graph,
            context=context,
            packet=packet,
            tag_runs=runs,
            rule_context=replace(
                inputs.rule_context,
                document_version_id=graph.document_version_id,
                packet_sha256=packet.packet_sha256,
            ),
            consensus=form_consensus(
                runs, packet=packet, rulepack=inputs.rulepack, tenant_id=TENANT, tag_revision=1
            ),
        )
        with monkeypatch.context() as old_release:
            old_release.setattr(policies, "publication_reader", policies.claim_source_reader)
            scoped, saved = source_tags.verify_context_sources(inputs, refs)
        linked, receipts = apply_report_level_link(
            inputs.consensus,
            config=config,
            context=context,
            graph=graph,
            attest=lambda _: (scoped, saved),
            fallback_tags=strict_fallback(runs, packet, inputs.rulepack, TENANT, 1, "strict-v1"),
        )
        assert len(receipts) == 1
        return replace(
            inputs, consensus=linked, report_level_link=config, report_level_review=receipts
        )

    _, service, inputs, review, _, _, _ = workspace(tmp_path, prepare_inputs=prepare)
    source_tags.store.jobs = service.store.jobs
    snapshot.update(rulepack=asdict(inputs.rulepack), report_level_link=config)
    # Substitute only the already-validated checkpoint/evidence handoff; the
    # initial tag and receipt are genuinely persisted by ReviewService.publish.
    with service.store.jobs._transaction() as db:
        run = service.store.jobs._get(db, TENANT, RUN, "run", "META")
        run["tag_job"] = {}
        service.store.jobs._put(db, TENANT, RUN, "run", "META", run)
    raw = json.loads(json.dumps(inputs.snapshot()))
    envelope = {"claims": [{"claim_id": review["claim_id"], "review_inputs": raw}]}
    evidence = ({}, SimpleNamespace(claims=(inputs.context.claim,)), graph)
    monkeypatch.setattr(
        source_tags, "_load_snapshot_with_evidence", lambda *_: (envelope, evidence)
    )
    before = deepcopy(raw)
    history = service.store.history(TENANT, RUN, review["claim_id"])
    loaded = source_tags.load_inputs(TENANT, RUN, review["claim_id"])
    assert H(loaded.report_level_review) == H(inputs.report_level_review)
    assert H(loaded.snapshot()) == H(inputs.snapshot())
    assert raw == before
    assert service.store.history(TENANT, RUN, review["claim_id"]) == history
    service.verify_context_sources = source_tags.verify_context_sources
    service.load_run_snapshot = source_tags.store.snapshot
    body = _management_body(
        dict(
            element_id="M3",
            state="present",
            evidence_refs=[asdict(r) for r in refs],
            normalized_value=None,
            credited_from=refs[1].source_id,
            reason_code=GRI_ASSURED_PAGE_V1,
        )
    )
    result = service.resolve_ai_delegated_review(
        _actor(),
        review["review_id"],
        body,
        '"1"',
        str(uuid4()),
        delegated_reviewer="regression",
        delegation_authority="explicit test",
    )
    assert result["new_tag_revision"] == 2
    after = service.store.history(TENANT, RUN, review["claim_id"])
    assert after["tags"][:-1] == history["tags"]
    assert H(after["tags"][-1]["report_level_review"][0]["source_receipt"]) == H(
        inputs.report_level_review[0]["source_receipt"]
    )
