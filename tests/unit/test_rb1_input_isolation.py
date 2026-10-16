"""RB1: bad grids never erase independent claims or weaken source checks."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from proofops.application import analysis_profile as profiles
from proofops.application.claims import ExtractionOutputError
from proofops.domain.provenance import canonical_hash
from proofops_worker.extract_runner import _is_text_candidate

from tests.unit.test_h1_parser_context import graph


def isolation():
    from proofops.application.rb1_input_isolation import InputIsolation

    return InputIsolation(profiles.RB1_POLICY)


def test_rb1_pin_is_opt_in_and_old_policies_keep_their_hashes():
    policy = profiles.RB1_POLICY
    assert (
        profiles.policy_for(
            profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I25_POLICY)
        )
        == profiles.FINALS_I25_POLICY
    )
    assert (
        profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=canonical_hash(policy))
        == policy
    )
    assert policy != profiles.FXH_POLICY
    from proofops.application.rb1_input_isolation import InputIsolation

    assert not InputIsolation(profiles.FXH_POLICY).active
    with pytest.raises(ValueError, match="RB1_INPUT_POLICY_MISMATCH"):
        InputIsolation(policy | {"rb1_input_isolation_sha256": "0" * 64})


@pytest.mark.parametrize(
    "missing,code", [(True, "J8_GRID_MISSING"), (False, "W9_GRID_TEXT_MISMATCH")]
)
def test_candidate_routing_records_only_bad_table_and_preserves_exact_error(missing, code):
    g = graph(tamper=not missing)
    table = next(b for b in g.blocks if b.kind == "table")
    if missing:
        g = replace(g, blocks=(table,), edges=())
    args = dict(extraction_qt1=True, graph=g, source_id=table.source_id)
    from proofops.application.ingest.qt1_tables import candidates_for

    with pytest.raises(ValueError, match=code):
        candidates_for(table, g)
    rb1 = isolation()
    assert not _is_text_candidate("table", table.normalized_text, rb1=rb1, **args)
    with pytest.raises(ExtractionOutputError) as held:
        rb1.check(table.source_id)
    assert held.value.failure_code == "TABLE_RB1_" + code
    assert _is_text_candidate("paragraph", "valid independent text", rb1=rb1, source_id="good")
    rb1.check("good")
    assert table.normalized_text not in repr(rb1.failures)


def test_prefetch_isolates_context_before_dispatch_without_skipping_good_pages():
    from proofops_agent.upstage_extraction import GraphBoundExtractor

    rb1 = isolation()

    def context(packet, graph):
        if packet["untrusted_document_data"]["source_id"] == "bad":
            raise ValueError("W9_GRID_TEXT_MISMATCH")
        return [], []

    calls = []
    inner = SimpleNamespace(
        _context=True,
        _packet_text=lambda p: None,
        _validate_context_graph=lambda p, g: None,
        _context_for=context,
        extract=lambda p, **kw: calls.append(p) or {"spans": []},
    )
    g = SimpleNamespace(
        blocks=[
            SimpleNamespace(
                source_id=s, winner=0, bbox=(0, 0, 1, 1), page_num=i, raw_text="some text"
            )
            for i, s in enumerate(("bad", "good"), 1)
        ]
    )
    bound = GraphBoundExtractor(inner, g, display_prefetch_workers=2, rb1=rb1)
    pages = []
    bound._display_catalog = SimpleNamespace(prefetch_pages=lambda p, **kw: pages.extend(p))
    packets = [{"untrusted_document_data": {"source_id": s}} for s in ("bad", "good")]
    bound.prefetch(packets)
    assert pages == [2]
    with pytest.raises(ExtractionOutputError, match="TABLE_RB1_W9_GRID_TEXT_MISMATCH"):
        bound.extract(packets[0])
    bound.extract(packets[1])
    assert calls == [packets[1]]


def test_identity_and_policy_errors_remain_fatal():
    rb1 = isolation()
    for code in (
        "SOURCE_ATTESTATION_REPLAY_MISMATCH",
        "UPSTAGE_CONTEXT_IDENTITY_MISMATCH",
        "LOCAL_TEST_AUTHORIZATION_INVALID",
        "ACCOUNTING_UNAVAILABLE",
    ):
        assert not rb1.capture("bad", ValueError(code))
    assert not rb1.capture("bad", ValueError("secret source text"))
    assert rb1.failures == {}


@pytest.mark.parametrize("phase", ["preliminary", "projection"])
@pytest.mark.parametrize(
    "failure",
    [
        ValueError("W9_GRID_TEXT_MISMATCH"),
        KeyError("private source text"),
        TypeError("private source text"),
    ],
)
def test_tag_input_failure_holds_only_affected_claim(tmp_path, monkeypatch, phase, failure):
    import json
    from uuid import uuid4

    from proofops.application.rb1_input_isolation import POLICY

    from tests.integration.test_local_tag_runner import tag_message
    from tests.integration.test_unattended_pipeline import TENANT, setup

    service, run_id, runner, _, _ = setup(tmp_path, monkeypatch)
    extraction, discovery, g = runner.claims.load_evidence(TENANT, run_id)
    first = discovery.claims[0]
    second = replace(first, claim_id=str(uuid4()))
    discovery = replace(discovery, claims=(first, second))
    monkeypatch.setattr(runner.claims, "load_evidence", lambda *_: (extraction, discovery, g))
    original = runner.preliminary
    seen = []

    def fail_one(claim, graph, *args):
        seen.append(claim.claim_id)
        if claim.claim_id == first.claim_id:
            raise failure
        return original(claim, graph) if phase == "preliminary" else None

    snapshot = service.store.snapshot(TENANT, run_id)
    policy = dict(rb1_input_isolation=POLICY, rb1_input_isolation_sha256=canonical_hash(POLICY))
    if phase == "projection":
        policy["sentence_context_policy"] = {"fixture": True}
        monkeypatch.setattr("proofops.application.ingest.k5_context.configured_context", fail_one)
    else:
        runner.preliminary = fail_one
    snapshot["analysis_profile_policy"] = policy
    message = tag_message(service, run_id, runner.clock())
    lease = service.store.jobs.claim_job(
        message, owner="RB1-test", now=runner.clock(), lease_seconds=300
    )
    result = json.loads(runner._execute(lease, snapshot, {"synthetic_calls": 0}))
    assert result["stage_status"] == "completed"
    bad, good = result["claims"]
    assert bad["reason"] == "TAG_INPUT_INVALID"
    assert bad["rb1_input_hold"]["cause"] == (
        "W9_GRID_TEXT_MISMATCH" if isinstance(failure, ValueError) else "TAG_INPUT_INVALID"
    )
    assert "private source text" not in json.dumps(result)
    assert bad["rb1_input_hold"]["locations"][0]["source_id"] == first.source_refs[0].source_id
    assert first.quote not in json.dumps(bad["rb1_input_hold"], ensure_ascii=False)
    assert bad["decision"] is None and bad["review_inputs"] is None
    assert bad["provisional_grade"]["evidence_grade"] is None
    assert bad["provisional_grade"]["display_type"] == "hold"
    assert not bad["tag_runs"]
    assert len(good["tag_runs"]) == 3
    assert seen == [first.claim_id, second.claim_id]


def test_hosted_subprocess_accepts_rb1_pin(tmp_path):
    from evaluation.hosted_r108 import prepare_argv
    from tests.test_hosted_analysis import source_pdf

    pdf = tmp_path / "selected.pdf"
    pdf.write_bytes(source_pdf())
    pin = canonical_hash(profiles.RB1_POLICY)
    args = prepare_argv(
        pdf,
        tmp_path / "state",
        "11111111-1111-4111-8111-111111111111",
        dict(report_year=2024, period_start="2024-01-01", period_end="2024-12-31"),
        dict(analysis_profile=profiles.V2_PROFILE, analysis_profile_sha256=pin),
    )
    assert args[args.index("--analysis-policy-sha256") + 1] == pin


def test_bad_source_is_unknown_with_original_location_and_cold_replay():
    from dataclasses import asdict

    from proofops.adapters.local.claim_store import _RecordedExtractor, extraction_outcome
    from proofops.application.claims import ClaimScope, discover_atomic_claims
    from proofops_agent.extraction import SyntheticClaimExtractor

    from tests.unit.test_k5_context import case

    g, _ = case(
        ["invalid table", "2024년 온실가스 배출량을 10% 줄였습니다."],
        (1, "2024년 온실가스 배출량을 10% 줄였습니다."),
        kinds=["table", "paragraph"],
    )
    rb1 = isolation()
    bad = g.blocks[0]
    rb1.capture(bad.source_id, ValueError("J8_GRID_MISSING"))
    inner = SyntheticClaimExtractor()

    class Bound:
        profile = inner.profile

        def extract(self, packet):
            rb1.check(packet["untrusted_document_data"]["source_id"])
            return inner.extract(packet)

    scope = ClaimScope(g.tenant_id, g.document_version_id, g.parse_manifest_id)
    discovered = discover_atomic_claims(g, scope, extractor=Bound())
    assert discovered.claims
    assert all(c.source_refs[0].source_id != bad.source_id for c in discovered.claims)
    hold = next(e for e in discovered.exclusions if e.source_id == bad.source_id)
    assert hold.state == "unknown" and hold.reason == "TABLE_RB1_J8_GRID_MISSING"
    outcome = extraction_outcome(g, discovered, claim_pages=[1], include_source_failures=True)
    assert outcome["failed_sources"] == [
        dict(source_id=bad.source_id, physical_page=1, failure_code="TABLE_RB1_J8_GRID_MISSING")
    ]
    assert bad.normalized_text not in repr(outcome)
    replay = discover_atomic_claims(
        g,
        scope,
        extractor=_RecordedExtractor(
            inner.profile, asdict(discovered)["receipts"], failures={bad.source_id: hold.reason}
        ),
    )
    assert replay == discovered


def test_prefetch_known_hold_still_checks_packet_identity():
    from proofops_agent.upstage_extraction import GraphBoundExtractor

    rb1 = isolation()
    rb1.capture("bad", ValueError("W9_GRID_TEXT_MISMATCH"))

    def invalid(*args):
        raise ValueError("UPSTAGE_CONTEXT_IDENTITY_MISMATCH")

    inner = SimpleNamespace(
        _context=True,
        _packet_text=lambda p: None,
        _validate_context_graph=invalid,
        extract=lambda *a, **k: None,
    )
    bound = GraphBoundExtractor(inner, object(), rb1=rb1)
    with pytest.raises(ValueError, match="UPSTAGE_CONTEXT_IDENTITY_MISMATCH") as error:
        bound.extract({"untrusted_document_data": {"source_id": "bad"}})
    assert not isinstance(error.value, ExtractionOutputError)
