"""CF6 controlled facts, actual rule engine; these fixtures are not model accuracy."""

import json
from copy import deepcopy
from dataclasses import asdict, replace

import pytest
from proofops.application.analysis_profile import (
    CF6_V2_POLICY,
    V2_POLICY,
    policy_for,
    publication_policy_for,
)
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.tagging.cf6_confirmation import confirmation_result, policy, resolve_votes
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.engine import RuleContext

from tests.acceptance.test_tagging import execute, setup


def seal(run, selected):
    provider = dict(
        request_id=run.request.request_id,
        provider_request_id=run.usage.provider_request_id,
        schema_valid=True,
        content=run.raw_response_json,
        simulated=False,
    )
    receipt = dict(
        schema="cf6-authenticated-transport-v1",
        authenticated=True,
        fresh_model_call=True,
        replay=False,
        response_sha256=canonical_hash(provider),
        expanded_sha256=canonical_hash(run.raw_response_json),
        provider_request_id=run.usage.provider_request_id,
        binding=dict(
            request_id=run.request.request_id,
            request_signature=run.request.request_signature,
            tenant_id=run.tenant_id,
            packet_sha256=run.packet_sha256,
            replica=run.replicate_id,
            model_sha256=run.model_sha256,
            prompt_sha256=run.prompt_sha256,
            analysis_policy_sha256=canonical_hash(selected),
        ),
    )
    return replace(
        run, provider_response_json=json.dumps(provider | dict(cf6_transport_receipt=receipt))
    )


def prepared(tmp_path, required=2, third="unknown", selected_pages=None):
    inputs = setup(tmp_path)
    selected = dict(cf6_confirmation=policy(required))
    data = inputs["packet"].to_dict()
    data.pop("packet_sha256")
    data.update(
        cf6_confirmation=selected["cf6_confirmation"],
        cf6_analysis_policy_sha256=canonical_hash(selected),
        cf6_selected_pages=sorted({b.page_num for b in inputs["original"].blocks})
        if selected_pages is None
        else selected_pages,
    )
    inputs["packet"] = freeze_packet(data)
    runs = execute(inputs)
    changed = []
    for r in runs:
        source = r.guarded.elements[0]
        elements = tuple(
            replace(
                e,
                state=third if r.replicate_id == 3 else "present",
                normalized_value=("covered" if e.element_id == "P4" else source.normalized_value)
                if r.replicate_id != 3 or third == "present"
                else None,
                evidence_refs=source.evidence_refs
                if r.replicate_id != 3 or third == "present"
                else (),
            )
            if e.element_id in ("P1", "P2", "P3", "P4")
            else e
            for e in r.guarded.elements
        )
        guarded = replace(r.guarded, elements=elements)
        changed.append(
            seal(
                replace(
                    r,
                    guarded=guarded,
                    raw_response_json=json.dumps(asdict(guarded)),
                    synthetic=False,
                    product_variant=False,
                    binding_hashes=tuple((f"P{i}", "b" * 64) for i in range(1, 5)),
                    source_scopes=tuple(
                        (f"P{i}", "global_bound" if i == 4 else "local_claim") for i in range(1, 5)
                    ),
                    errors=(),
                ),
                selected,
            )
        )
    return inputs, tuple(changed), selected


def assess(inputs, runs, selected, **kw):
    claim = inputs["context"].claim
    return confirmation_result(
        runs,
        inputs["packet"],
        inputs["rulepack"],
        RuleContext(
            claim.tenant_id,
            claim.document_version_id,
            claim.claim_id,
            inputs["packet"].packet_sha256,
            local_synthetic=True,
        ),
        claim=claim,
        graph=inputs["original"],
        analysis_policy=selected,
        prior_projection=kw.pop("prior_projection", {}),
        **kw,
    )


def test_two_verified_unknown_decides_e3_three_threshold_is_scoped_e0(tmp_path):
    inputs, runs, selected = prepared(tmp_path)
    result = assess(inputs, runs, selected)
    assert result["reasons"] == []
    assert result["cf6_confirmation"]["evidence_grade"] == "E3"
    assert result["cf6_confirmation"]["decision_status"] == "decided"
    assert result["cf6_confirmation"]["confirmation_display"] == "확정"
    assert assess(inputs, runs, selected) == result
    path = tmp_path / "three"
    path.mkdir()
    inputs, runs, selected = prepared(path, 3)
    assert assess(inputs, runs, selected)["cf6_confirmation"]["evidence_grade"] == "E0"


@pytest.mark.parametrize("manual", [None, {"evidence_grade": "E1", "decision_status": "decided"}])
def test_hosted_projection_exposes_rule_decision_and_preserves_manual_priority(
    tmp_path, monkeypatch, manual
):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from proofops_api import hosted_results

    inputs, runs, selected = prepared(tmp_path)
    confirmation = assess(inputs, runs, selected)["cf6_confirmation"]
    claim = inputs["context"].claim
    projection = dict(claim_id=claim.claim_id, cf6_confirmation=confirmation)
    # Exercise the public projection of an admitted checkpoint. Authentication
    # and checkpoint replay are covered independently, not faked by this facade.
    claims = SimpleNamespace(
        store=SimpleNamespace(
            jobs=SimpleNamespace(get_run=lambda *args: dict(extract_job={}, tag_job={}))
        ),
        current_tag=lambda *args: None,
        summary=lambda *args: dict(
            claim_id=claim.claim_id, page_num=1, track="performance", decision=manual
        ),
        missing_evidence=lambda *args, **kwargs: [],
    )
    tags = SimpleNamespace(
        _load_snapshot_with_evidence=lambda *args: (
            dict(claims=[projection]),
            ({}, SimpleNamespace(claims=[claim]), inputs["original"]),
        )
    )
    reviews = SimpleNamespace(store=SimpleNamespace(page=lambda *args, **kwargs: dict(items=[])))

    @contextmanager
    def services(*args):
        yield "run", claims, tags, reviews

    monkeypatch.setattr(hosted_results, "services", services)
    (tmp_path / "pilot.json").write_text("{}")
    (tmp_path / "outcome.json").write_text("{}")
    row = hosted_results.read_result(tmp_path, claim.tenant_id, [7])["claims"][0]
    assert row["cf6_confirmation"] == confirmation
    assert row["decision"] == (manual or confirmation)
    assert row["confirmed_grade"] == ("E1" if manual else "E3")
    assert row["cf6_status"] == "confirmed"
    assert row["original_page_num"] == 7


@pytest.mark.parametrize("third", ["conflict", "not_applicable"])
def test_conflict_or_unresolved_third_never_becomes_absent(tmp_path, third):
    inputs, runs, selected = prepared(tmp_path, third=third)
    if third == "conflict":
        assert assess(inputs, runs, selected)["cf6_confirmation"] is None
    assert not any(e["state"] == "absent" for e in assess(inputs, runs, selected)["elements"])


@pytest.mark.parametrize("state", ["present", "absent"])
def test_symmetric_two_of_three_with_trusted_evidence(state):
    votes = [
        dict(state=state, verified=True, value=None, binding="b", scope="same", replica=i)
        for i in (1, 2)
    ]
    votes.append(dict(state="unknown", replica=3))
    assert resolve_votes(votes)[0] == state
    assert resolve_votes(votes, 3)[0] == "unknown"
    votes[2] = dict(
        state="absent" if state == "present" else "present",
        verified=True,
        binding="b",
        scope="same",
        replica=3,
    )
    assert resolve_votes(votes)[0] == "conflict"
    votes[2]["verified"] = False
    assert resolve_votes(votes)[0] == state
    votes[2]["state"] = "unreadable"
    assert resolve_votes(votes)[0] == "unknown"


@pytest.mark.parametrize(
    "failure",
    [
        "replay",
        "fresh",
        "policy",
        "packet",
        "body",
        "provider",
        "synthetic",
        "source",
        "binding",
        "track",
        "missing",
        "unverified",
    ],
)
def test_freshness_source_independence_and_track_guards(tmp_path, failure):
    inputs, runs, selected = prepared(tmp_path)
    runs = list(runs)
    r = runs[2]
    if failure in ("replay", "fresh", "policy", "packet", "body"):
        data = json.loads(r.provider_response_json)
        if failure == "replay":
            data["response_reuse"] = {}
        elif failure == "fresh":
            data["cf6_transport_receipt"]["fresh_model_call"] = False
        elif failure == "policy":
            data["cf6_transport_receipt"]["binding"]["analysis_policy_sha256"] = "a" * 64
        elif failure == "packet":
            data["cf6_transport_receipt"]["binding"]["packet_sha256"] = "a" * 64
        else:
            data["content"] = "changed"
        runs[2] = replace(r, provider_response_json=json.dumps(data))
    elif failure == "provider":
        runs[2] = replace(
            r, usage=replace(r.usage, provider_request_id=runs[0].usage.provider_request_id)
        )
    elif failure == "synthetic":
        runs[2] = replace(r, synthetic=True)
    elif failure == "source":
        inputs["context"] = replace(
            inputs["context"], claim=replace(inputs["context"].claim, source_quality="unverified")
        )
    elif failure == "binding":
        runs[1] = replace(runs[1], binding_hashes=tuple((f"P{i}", "c" * 64) for i in range(1, 5)))
    elif failure == "track":
        runs[2] = replace(r, guarded=replace(r.guarded, track="management"))
    elif failure == "missing":
        runs[2] = replace(r, guarded=None)
    else:
        r = runs[1]
        runs[1] = replace(
            r,
            guarded=replace(
                r.guarded,
                elements=tuple(
                    replace(
                        e,
                        evidence_refs=tuple(
                            replace(ref, verification_state="candidate") for ref in e.evidence_refs
                        ),
                    )
                    for e in r.guarded.elements
                ),
            ),
        )
    result = assess(inputs, tuple(runs), selected)
    if failure == "unverified":
        # The claim source still verifies; rejected element citations supply no
        # present votes and DEC-127 now permits conservative scoped absence.
        assert result["cf6_confirmation"]["evidence_grade"] == "E0"
        assert all(e["state"] != "present" for e in result["elements"])
    else:
        assert result["cf6_confirmation"] is None


def test_dec127_unknown_is_scoped_absence_but_conflict_stays_held(tmp_path):
    inputs, runs, selected = prepared(tmp_path)
    for state in ("unknown", "absent", "conflict"):
        changed = []
        for r in runs:
            guarded = replace(
                r.guarded,
                elements=tuple(
                    replace(e, state=state, evidence_refs=(), normalized_value=None)
                    if e.element_id == "P4"
                    else e
                    for e in r.guarded.elements
                ),
            )
            changed.append(
                seal(
                    replace(r, guarded=guarded, raw_response_json=json.dumps(asdict(guarded))),
                    selected,
                )
            )
        result = assess(inputs, tuple(changed), selected)
        assert (result["cf6_confirmation"] or {}).get("evidence_grade") == (
            None if state == "conflict" else "E2"
        )
        assert next(e for e in result["elements"] if e["element_id"] == "P4")["state"] == (
            "conflict" if state == "conflict" else "absent_in_scope"
        )


def test_registry_is_opt_in_and_old_policy_stays_default(tmp_path):
    from evaluation.hosted_r108 import prepare_argv
    from tests.integration.test_mixed_parser import document

    source = tmp_path / "source.pdf"
    source.write_bytes(document().content)
    pin = canonical_hash(CF6_V2_POLICY)
    argv = prepare_argv(
        source,
        tmp_path / "state",
        "11111111-1111-4111-8111-111111111111",
        dict(
            analysis_profile="finals-unattended-v2",
            report_year=2024,
            period_start="2024-01-01",
            period_end="2024-12-31",
        ),
        dict(analysis_profile_sha256=pin),
    )
    assert argv[argv.index("--analysis-policy-sha256") + 1] == pin
    before = deepcopy(V2_POLICY)
    assert policy_for("finals-unattended-v2") == before
    for selector in (policy_for, publication_policy_for):
        assert (
            selector("finals-unattended-v2", pinned_hash=canonical_hash(CF6_V2_POLICY))
            == CF6_V2_POLICY
        )
    assert CF6_V2_POLICY != before and V2_POLICY == before


@pytest.mark.parametrize(
    "third,expected", [("unknown", "E1"), ("failed", None), ("conflict", None)]
)
def test_dec127_non_observation_after_three_replicas(tmp_path, third, expected):
    inputs, runs, selected = prepared(tmp_path)
    changed = []
    for r in runs:
        guarded = replace(
            r.guarded,
            elements=tuple(
                replace(
                    e,
                    state=third if r.replicate_id == 3 and third != "failed" else "unknown",
                    evidence_refs=(),
                    normalized_value=None,
                )
                if e.element_id in ("P2", "P3", "P4")
                else e
                for e in r.guarded.elements
            ),
        )
        if third == "failed" and r.replicate_id == 3:
            r = replace(r, usage=replace(r.usage, status="failed", error_code="TIME_BUDGET"))
        changed.append(
            seal(
                replace(r, guarded=guarded, raw_response_json=json.dumps(asdict(guarded))), selected
            )
        )
    result = assess(inputs, tuple(changed), selected)
    assert (result["cf6_confirmation"] or {}).get("evidence_grade") == expected
    if expected:
        confirmed = result["cf6_confirmation"]
        assert confirmed["confirmation_scope"]["selected_pages"] == [1]
        assert confirmed["model_sha256"] == runs[0].model_sha256
        assert confirmed["prompt_sha256"] == runs[0].prompt_sha256
        assert (
            next(e for e in result["elements"] if e["element_id"] == "P4")["state"]
            == "absent_in_scope"
        )


@pytest.mark.parametrize("reason", ["TIME_BUDGET", "RB3_TIME_BUDGET", "blocked_rule_gap"])
def test_dec127_retains_time_budget_and_prior_gap_holds(tmp_path, reason):
    inputs, runs, selected = prepared(tmp_path)
    assert assess(inputs, runs, selected, hold_reason=reason)["cf6_confirmation"] is None


def test_dec127_requires_claim_source_and_selected_scope(tmp_path):
    inputs, runs, selected = prepared(tmp_path)
    inputs["context"] = replace(
        inputs["context"], claim=replace(inputs["context"].claim, source_quality="unresolved")
    )
    assert assess(inputs, runs, selected)["cf6_confirmation"] is None


def test_dec127_missing_scope_or_grade_blocking_gap_is_held(tmp_path):
    inputs, runs, selected = prepared(tmp_path, selected_pages=[])
    result = assess(inputs, runs, selected)
    assert result["cf6_confirmation"] is None
    assert "CF6_SELECTED_SCOPE_REQUIRED" in result["reasons"]
    assert not any(e["state"] == "absent_in_scope" for e in result["elements"])
    assert (
        assess(inputs, runs, selected, prior_projection={"gap_ids": ["GAP-001"]})[
            "cf6_confirmation"
        ]
        is None
    )


def test_verified_negative_source_veto_survives_guard_unknown(tmp_path):
    inputs, runs, selected = prepared(tmp_path)
    r = runs[2]
    raw = json.loads(r.raw_response_json)
    element = next(e for e in raw["elements"] if e["element_id"] == "P1")
    element.update(
        state="absent",
        evidence_refs=[asdict(ref) for ref in runs[0].guarded.elements[0].evidence_refs],
    )
    changed = (*runs[:2], seal(replace(r, raw_response_json=json.dumps(raw)), selected))
    result = assess(inputs, changed, selected)
    assert result["cf6_confirmation"] is None
    assert next(e for e in result["elements"] if e["element_id"] == "P1")["state"] == "conflict"


def test_worker_checkpoint_wires_cf6_and_replays_without_synthetic_promotion(tmp_path, monkeypatch):
    from proofops.application.runs import RunService

    from tests.integration.test_local_tag_runner import TENANT, verified_setup

    init = RunService.__init__

    def configured(self, *args, **kwargs):
        kwargs.update(
            pipeline_profile="finals-unattended-v2",
            analysis_policy_sha256=canonical_hash(CF6_V2_POLICY),
        )
        init(self, *args, **kwargs)

    monkeypatch.setattr(RunService, "__init__", configured)
    service, run_id, runner, _, _ = verified_setup(tmp_path, monkeypatch)
    from proofops.application.rb3_deadline import Deadline

    deadline_policy = CF6_V2_POLICY["rb3_deadline"]
    runner.rb3_deadline = Deadline(
        deadline_policy["hard_cap_seconds"], policy=deadline_policy, clock=lambda: 0
    )
    execute_worker = runner._execute
    captured = []

    def traced(*args, **kwargs):
        try:
            return execute_worker(*args, **kwargs)
        except Exception as error:
            captured.append(error)
            raise

    monkeypatch.setattr(runner, "_execute", traced)
    status = runner.run_once(tenant_id=TENANT, run_id=run_id)
    if captured:
        raise captured[0]
    assert status == "completed"
    envelope = runner.tags.load_snapshot(TENANT, run_id)
    tagged = [c for c in envelope["claims"] if c.get("tag_runs")]
    assert tagged
    for record in tagged:
        assert record["cf6_confirmation"] is None
        assert "CF6_CURRENT_RESPONSES_REQUIRED" in record["cf6_receipt"]["reasons"]
        assert record["frozen_packet"]["cf6_analysis_policy_sha256"] == canonical_hash(
            CF6_V2_POLICY
        )
        assert record["provisional_grade"]["decision_status"] == "provisional"
    assert runner.tags.load_snapshot(TENANT, run_id) == envelope


@pytest.mark.parametrize(
    "version,source_quality,expected",
    [(2, "verified", "E0"), (2, "unverified", None), (1, "verified", None)],
)
def test_management_all_unknown_reaches_public_confirmation_with_v1_replay(
    tmp_path, version, source_quality, expected
):
    inputs, runs, _ = prepared(tmp_path)
    selected = dict(cf6_confirmation=policy(version=version))
    data = inputs["packet"].to_dict()
    data.pop("packet_sha256")
    data.update(
        track="management",
        allowed_elements=[f"M{i}" for i in range(1, 7)],
        cf6_confirmation=selected["cf6_confirmation"],
        cf6_analysis_policy_sha256=canonical_hash(selected),
    )
    inputs["packet"] = freeze_packet(data)
    inputs["context"] = replace(
        inputs["context"], claim=replace(inputs["context"].claim, source_quality=source_quality)
    )
    changed = []
    for r in runs:
        guarded = replace(
            r.guarded,
            track="management",
            packet_sha256=inputs["packet"].packet_sha256,
            elements=tuple(
                replace(
                    e, element_id=f"M{i}", state="unknown", evidence_refs=(), normalized_value=None
                )
                for i, e in enumerate(r.guarded.elements, 1)
            ),
        )
        changed.append(
            seal(
                replace(
                    r,
                    packet_sha256=inputs["packet"].packet_sha256,
                    guarded=guarded,
                    raw_response_json=json.dumps(asdict(guarded)),
                    binding_hashes=(),
                    source_scopes=(),
                ),
                selected,
            )
        )
    result = assess(inputs, tuple(changed), selected)
    assert (result["cf6_confirmation"] or {}).get("evidence_grade") == expected
    assert all(e["state"] == "absent_in_scope" for e in result["elements"])
    if version == 2:
        assert result["engine_decision"]["decision_status"] == "decided"
        assert "MGMT_NO_MEANS_IN_SCOPE_E0" in result["engine_decision"]["rule_ids"]
        assert result["engine_decision"]["missing_elements"] == ["M1", "M2", "M3", "M4"]
    if source_quality == "unverified":
        assert "CF6_CLAIM_SOURCE_UNVERIFIED" in result["reasons"]


def test_surviving_auxiliary_conflict_cannot_publish_even_if_ladder_decides(tmp_path, monkeypatch):
    from proofops.application.tagging import cf6_confirmation
    from proofops.domain.rules.engine import ConfirmedFact

    inputs, runs, selected = prepared(tmp_path)
    original = cf6_confirmation.form_consensus

    def with_conflict(*args, **kwargs):
        result = original(*args, **kwargs)
        tags = result.confirmed_tags
        assert tags is not None
        return replace(
            result,
            confirmed_tags=replace(
                tags, facts=(*tags.facts, ConfirmedFact("comparison_basis", "conflict"))
            ),
        )

    monkeypatch.setattr(cf6_confirmation, "form_consensus", with_conflict)
    result = assess(inputs, runs, selected)
    assert result["cf6_confirmation"] is None
    assert "CF6_CONFLICT:comparison_basis" in result["reasons"]
