"""The fresh gate fails on E15's wiring failures, missing proof and timing regressions."""

import importlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


@pytest.fixture
def gate(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("fresh_e2e_gate")


def example(gate):
    baseline = dict(
        evidence="E14 v23 LG13",
        min_claims=107,
        stage_seconds=dict(parse=199.32, extract=161.02, tag=228.37, publish=52.55),
        max_stage_ratio=1.5,
        max_seconds=984.6,
    )
    case = dict(
        kind="lg13",
        source_sha256=gate.LG_SHA256,
        pages=gate.LG_PAGES,
        claim_pages=gate.LG_CLAIM_PAGES,
        tenant_id="d1b9e025-a759-4d28-8713-cbb5940ec89b",
        baseline=baseline,
    )
    observation = dict(
        status="completed",
        seconds=640,
        unsettled_costs=0,
        result=dict(
            claims=[dict(source_quality="verified")] * 107, pipeline=dict(status="completed")
        ),
        c3_generated_calls=3,
        w18=dict(exact_refs=1, default_unchanged=True),
        inventory_completed=27,
        inventory_planned=27,
        outcome=dict(stage_seconds=deepcopy(baseline["stage_seconds"])),
    )
    return case, observation


def test_fresh_gate_rejects_replay_scope_reduction_and_loose_baseline(gate):
    case, observation = example(gate)
    gate.validate_manifest(dict(cases=[case]))
    assert gate.compare(observation, case["baseline"])["status"] == "passed"
    for key, value in (
        ("pages", [36]),
        ("recorded_states", ["saved"]),
        ("source_sha256", "0" * 64),
        ("tenant_id", "random"),
    ):
        with pytest.raises(ValueError):
            gate.validate_manifest(dict(cases=[case | {key: value}]))
    with pytest.raises(ValueError):
        gate.validate_manifest(
            dict(cases=[case | dict(baseline=case["baseline"] | dict(min_claims=1))])
        )


@pytest.mark.parametrize(
    "failure",
    [
        "REPLICA_HEADER_UNRESOLVED",
        "TAG_INPUT_INVALID",
        "TAGGING_INPUT_COUNT_INVALID",
        "inventory",
        "c3",
        "c3_confirmation",
        "time",
        "proof",
        "empty",
        "unsettled",
        "publish",
        "clock",
        "w18",
    ],
)
def test_fresh_gate_cannot_pass_each_regression(gate, failure):
    case, observed = example(gate)
    if failure.startswith(("REPLICA", "TAG_", "TAGGING_")):
        observed["errors"] = {failure: 1}
    elif failure == "inventory":
        observed["inventory_completed"] = 0
    elif failure == "c3":
        observed["c3_generated_calls"] = 0
    elif failure == "c3_confirmation":
        observed["outcome"]["bounded_c3"] = dict(published=True)
    elif failure == "time":
        observed["outcome"]["stage_seconds"]["extract"] = 486
    elif failure == "proof":
        observed["result"]["claims"] = [{}] * 107
    elif failure == "empty":
        observed["result"]["claims"] = []
    elif failure == "unsettled":
        observed["unsettled_costs"] = 1
    elif failure == "clock":
        observed["clock_discontinuity_seconds"] = 30
    elif failure == "w18":
        observed["w18"] = dict(exact_refs=0, default_unchanged=True)
    else:
        del observed["outcome"]["stage_seconds"]["publish"]
    assert gate.compare(observed, case["baseline"])["status"] == "failed"


def test_fresh_c3_generated_reply_is_schema_valid_and_never_asserts_present(gate, monkeypatch):
    import sys

    from proofops.application.tagging.c3_request_binding import SYSTEM
    from proofops.application.tagging.fact_assembly_c2 import vote_schema

    monkeypatch.setitem(
        sys.modules, "predeploy_runtime_base", importlib.import_module("predeploy_runtime")
    )
    runtime = importlib.import_module("fresh_e2e_runtime")
    events = []
    monkeypatch.setattr(runtime, "audit", lambda event, **kw: events.append((event, kw)))
    response = runtime.generate_llm(
        dict(
            model="gpt-6-luna",
            messages=[
                dict(content=SYSTEM),
                dict(
                    content=json.dumps(dict(claim="original", sources=[], packet_sha256="a" * 64))
                ),
            ],
        )
    )
    raw = json.loads(response["choices"][0]["message"]["content"])
    Draft202012Validator(vote_schema()).validate(raw)
    assert all(e["state"] == "unknown" for e in raw["elements"].values())
    assert events[0][1]["role"] == "c3"


def test_native_ocr_simulation_requires_exact_pixels(gate, monkeypatch):
    import hashlib
    import io
    import sys

    from PIL import Image

    monkeypatch.setitem(
        sys.modules, "predeploy_runtime_base", importlib.import_module("predeploy_runtime")
    )
    runtime = importlib.import_module("fresh_e2e_runtime")
    original = Image.new("RGBA", (2, 2), (255, 255, 255, 255))
    key = (original.size, hashlib.sha256(original.tobytes()).hexdigest())
    response = dict(words="test-only-current-page")
    monkeypatch.setattr(runtime, "_native_pages", {key: response})
    buffer = io.BytesIO()
    original.save(buffer, format="PNG")
    assert runtime.native_ocr(buffer.getvalue()) == response
    original.putpixel((0, 0), (0, 0, 0, 255))
    changed = io.BytesIO()
    original.save(changed, format="PNG")
    assert runtime.native_ocr(changed.getvalue()) is None


def test_kakao_auto_gate_retains_source_boundary_and_strict_timings(gate):
    _, observed = example(gate)
    case = dict(
        kind="kakao",
        source_sha256=gate.KAKAO_SHA256,
        selection_mode="automatic",
        baseline=dict(
            evidence="E14 Kakao",
            min_claims=133,
            stage_seconds=gate.KAKAO_STAGES,
            max_stage_ratio=1.5,
            max_seconds=2567.7,
            c3_scope="outside_approved_source",
        ),
    )
    gate.validate_manifest(dict(cases=[case]))
    observed["result"]["claims"] = [dict(source_quality="verified")] * 133
    observed.update(
        c3_generated_calls=0,
        selection=dict(
            automatic=True,
            pages=[51],
            claim_pages=[51],
            proposal=dict(selected_evidence_pages=[51], selected_claim_pages=[51]),
        ),
    )
    observed["outcome"] = dict(
        stage_seconds=gate.KAKAO_STAGES,
        bounded_c3=dict(status="outside_approved_source", published=False),
    )
    assert gate.compare(observed, case["baseline"])["status"] == "passed"
    for update in (dict(c3_generated_calls=3), dict(selection={}), dict(inventory_completed=0)):
        assert gate.compare(observed | update, case["baseline"])["status"] == "failed"
    for update in (dict(pages=[51]), dict(selection_mode="manual"), dict(recorded_states=["old"])):
        with pytest.raises(ValueError):
            gate.validate_manifest(dict(cases=[case | update]))
    with pytest.raises(ValueError):
        gate.validate_manifest(
            dict(cases=[case | dict(baseline=case["baseline"] | dict(max_seconds=3000))])
        )


def current_example(gate):
    from proofops.application import analysis_profile as profiles
    from proofops.domain.provenance import canonical_hash

    case, observed = example(gate)
    policy = profiles.V2_POLICY
    pin = canonical_hash(policy)
    observed["runtime"] = dict(policy_sha256=pin)
    scope = dict(
        absence_basis="system_not_found_or_not_linked_after_three_replicas",
        rule_policy_sha256=canonical_hash(policy["cf6_confirmation"]["scope_rules"]),
        selected_pages=[1],
        tenant_id="tenant",
        document_version_id="document",
        run_id="run",
    )
    decision = dict(
        evidence_grade="E0",
        decision_status="decided",
        label="UNSUBSTANTIATED",
        review_status="auto_confirmed",
        rule_ids=["MGMT_NO_MEANS_IN_SCOPE_E0"],
        confirmation_basis="cf6_element_agreement",
        confirmation_scope=scope,
        confirmation_policy_sha256=canonical_hash(policy["cf6_confirmation"]),
        analysis_policy_sha256=pin,
        cf6_receipt_sha256="a" * 64,
        rule_pack_sha256="b" * 64,
        model_sha256="c" * 64,
        prompt_sha256="d" * 64,
    )
    claim = dict(
        source_quality="verified",
        confirmed_grade="E0",
        cf6_status="confirmed",
        cf6_track="management",
        cf6_hold_reasons=[],
        hold_reason=None,
        cf6_confirmation=decision,
        decision=deepcopy(decision),
        cf6_elements=[
            dict(
                element_id=f"M{i}",
                state="absent_in_scope",
                absence_basis="DEC127_SYSTEM_NON_OBSERVATION",
                evidence_refs=[],
            )
            for i in range(1, 7)
        ],
    )
    observed["result"]["claims"] = [deepcopy(claim) for _ in range(107)]
    return case, observed


def test_dec127_unknown_simulation_can_confirm_only_scoped_rule_e0(gate):
    case, observed = current_example(gate)
    assert gate.compare(observed, case["baseline"])["status"] == "passed"


@pytest.mark.parametrize(
    "change",
    [
        "E1",
        "E2",
        "E3",
        "unknown",
        "conflict",
        "present",
        "missing_elements",
        "absence_basis",
        "decision_grade",
        "rule",
        "source",
        "hold",
        "policy",
        "scope",
        "receipt",
        "decision_missing",
        "confirmation_missing",
    ],
)
def test_dec127_rejects_confirmation_inconsistency(gate, change):
    case, observed = current_example(gate)
    c = observed["result"]["claims"][0]
    if change in {"E1", "E2", "E3"}:
        c["confirmed_grade"] = change
    elif change in {"unknown", "conflict", "present"}:
        c["cf6_elements"][0]["state"] = change
    elif change == "missing_elements":
        c["cf6_elements"] = []
    elif change == "absence_basis":
        c["cf6_elements"][0]["absence_basis"] = "invented"
    elif change == "decision_grade":
        c["decision"]["evidence_grade"] = "E1"
    elif change == "rule":
        c["decision"]["rule_ids"] = ["MGMT_E3"]
        c["cf6_confirmation"] = deepcopy(c["decision"])
    elif change == "source":
        c["source_quality"] = "unverified"
    elif change == "hold":
        c["cf6_hold_reasons"] = ["CF6_TIME_BUDGET"]
    elif change == "policy":
        observed["runtime"]["policy_sha256"] = "0" * 64
    elif change == "scope":
        c["decision"]["confirmation_scope"]["selected_pages"] = []
        c["cf6_confirmation"] = deepcopy(c["decision"])
    elif change == "receipt":
        c["decision"]["cf6_receipt_sha256"] = ""
        c["cf6_confirmation"] = deepcopy(c["decision"])
    elif change == "decision_missing":
        c["decision"] = None
    elif change == "confirmation_missing":
        c["cf6_confirmation"] = None
    assert gate.compare(observed, case["baseline"])["status"] == "failed"


@pytest.mark.parametrize(
    "reason,quality,valid",
    [
        ("CF6_CLAIM_SOURCE_UNVERIFIED", "unverified", True),
        ("CF6_CLAIM_SOURCE_UNVERIFIED", "verified", False),
        ("CF6_TIME_BUDGET", "verified", True),
        ("MADE_UP_HOLD", "unverified", False),
        ("", "unverified", False),
    ],
)
def test_dec127_requires_valid_hold_reason(gate, reason, quality, valid):
    case, observed = current_example(gate)
    observed["result"]["claims"][0].update(
        confirmed_grade=None,
        decision=None,
        cf6_confirmation=None,
        cf6_status="held",
        cf6_hold_reasons=[reason] if reason else [],
        source_quality=quality,
    )
    assert (gate.compare(observed, case["baseline"])["status"] == "passed") is valid


@pytest.mark.parametrize("name", ["FINALS_I26_POLICY", "FINALS_I28_POLICY"])
def test_historical_pins_still_forbid_even_e0_confirmation(gate, name):
    from proofops.application import analysis_profile as profiles
    from proofops.domain.provenance import canonical_hash

    case, observed = current_example(gate)
    observed["runtime"]["policy_sha256"] = canonical_hash(getattr(profiles, name))
    assert (
        "unknown_simulation_published_confirmation"
        in gate.compare(observed, case["baseline"])["failures"]
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing_runtime",
        "different_outcome",
        "scope_policy",
        "analysis_pin",
        "confirmation_pin",
        "missing_e0_rule",
        "label",
        "status",
        "absence_scope",
        "model_hash",
    ],
)
def test_dec127_requires_bound_policy_and_rule_provenance(gate, change):
    case, observed = current_example(gate)
    claim = observed["result"]["claims"][0]
    decision = claim["decision"]
    if change == "missing_runtime":
        observed.pop("runtime")
    elif change == "different_outcome":
        observed["outcome"]["scope"] = dict(analysis_profile_sha256="f" * 64)
    elif change == "scope_policy":
        decision["confirmation_scope"]["rule_policy_sha256"] = "f" * 64
    elif change == "analysis_pin":
        decision["analysis_policy_sha256"] = "f" * 64
    elif change == "confirmation_pin":
        decision["confirmation_policy_sha256"] = "f" * 64
    elif change == "missing_e0_rule":
        decision["rule_ids"] = []
    elif change == "label":
        decision["label"] = "SUBSTANTIATED"
    elif change == "status":
        decision["decision_status"] = "blocked_rule_gap"
    elif change == "absence_scope":
        decision["confirmation_scope"]["absence_basis"] = "document_exhaustive"
    elif change == "model_hash":
        decision["model_sha256"] = "not-a-hash"
    claim["cf6_confirmation"] = deepcopy(decision)
    assert gate.compare(observed, case["baseline"])["status"] == "failed"


def test_missing_policy_cannot_bypass_current_hold_validation(gate):
    case, observed = current_example(gate)
    observed.pop("runtime")
    observed["result"]["claims"] = [dict(source_quality="verified", cf6_status="held")] * 107
    assert "simulation_policy_missing" in gate.compare(observed, case["baseline"])["failures"]
