"""SC1 offline contract tests: real guards/rules, explicitly synthetic extraction."""

import copy
import json
from dataclasses import asdict, replace

import pytest
from proofops.application.tagging.analysis_scope import (
    analyze_scope,
    confirmation_policy,
)
from proofops.application.tagging.element_inventory import (
    POLICY,
    build_inventory,
    replay_inventory,
    selection_from_snapshot,
)
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.engine import RuleContext, evaluate

from tests.acceptance.test_binding import DIMENSIONS
from tests.acceptance.test_tagging import execute, setup


def selection(inputs, pages=None, total=1):
    graph = inputs["original"]
    return selection_from_snapshot(
        dict(
            document=dict(
                version_id=graph.document_version_id, sha256=graph.source_sha256, page_count=total
            ),
            selected_pages=[1] if pages is None else pages,
        ),
        graph,
        inputs["packet"].to_dict()["run_id"],
    )


def responder(request):
    records = []
    for span in request["untrusted_document_data"]["spans"]:
        ref = span["source_ref"]

        def attr(value):
            start = ref["quote"].find(value)
            if start < 0:
                return None
            return dict(
                source_id=ref["source_id"],
                char_start=ref["char_start"] + start,
                char_end=ref["char_start"] + start + len(value),
            )

        attrs = dict(
            subject=attr(DIMENSIONS["entity"]),
            metric=attr(DIMENSIONS["metric"]),
            site=attr(DIMENSIONS["facility"]),
            period=attr(DIMENSIONS["reporting_period"]),
        )
        for eid in POLICY["terms"]:
            records.append(
                dict(
                    element_id=eid,
                    state="present" if eid == "P1" else "not_applicable",
                    evidence={k: ref[k] for k in ("source_id", "char_start", "char_end")},
                    attributes=attrs,
                )
            )
    return dict(
        **{
            k: request[k]
            for k in (
                "request_id",
                "request_signature",
                "packet_sha256",
                "replicate_id",
                "model_sha256",
                "prompt_sha256",
            )
        },
        provider_response_id="sim-" + request["request_id"],
        synthetic=True,
        status="succeeded",
        raw_response_json=json.dumps(
            dict(
                complete=True,
                records=records,
                packet_sha256=request["packet_sha256"],
                replicate_id=request["replicate_id"],
            )
        ),
    )


def case(tmp_path, *, invoke=responder, pages=None, total=1):
    inputs = setup(tmp_path)
    runs = tuple(replace(r, product_variant=False) for r in execute(inputs))
    inv = build_inventory(
        inputs["original"], selection(inputs, pages, total), model_sha256="a" * 64, invoke=invoke
    )
    return inputs, runs, inv


def analyze(inputs, runs, inv, required=3, **kw):
    claim = inputs["context"].claim
    return analyze_scope(
        runs=runs,
        packet=inputs["packet"],
        context=inputs["context"],
        graph=inputs["original"],
        rulepack=inputs["rulepack"],
        rule_context=RuleContext(
            claim.tenant_id,
            claim.document_version_id,
            claim.claim_id,
            inputs["packet"].packet_sha256,
            local_synthetic=True,
        ),
        inventory=inv,
        required_present_votes=required,
        **kw,
    )


def test_inventory_once_replay_scope_and_legacy_grade_unchanged(tmp_path):
    calls = []

    def invoke(request):
        calls.append(request)
        return responder(request)

    inputs, runs, inv = case(tmp_path, invoke=invoke)
    assert len(calls) == inv["planned_calls"] == 3
    assert replay_inventory(inv, inputs["original"]) == inv
    before = canonical_hash([asdict(r) for r in runs])
    result = analyze(inputs, runs, inv)
    assert result["sc1_confirmation"]["evidence_grade"] == "E1"
    assert result["sc1_confirmation"]["confirmation_basis"] == "analysis_scope"
    assert {
        e["state"] for e in result["sc1_elements"] if e["element_id"] in ("P2", "P3", "P4")
    } == {"absent_in_scope"}
    for _ in range(5):
        assert analyze(inputs, runs, inv) == result
    assert len(calls) == 3
    assert canonical_hash([asdict(r) for r in runs]) == before
    assert len({canonical_hash(confirmation_policy(n)) for n in (1, 2, 3)}) == 3


@pytest.mark.parametrize(
    "votes,expected", [(3, [True, True, True]), (2, [False, True, True]), (1, [False, False, True])]
)
def test_threshold_matrix(tmp_path, votes, expected):
    inputs, runs, inv = case(tmp_path)
    changed = []
    for i, run in enumerate(runs):
        if i < votes:
            changed.append(run)
        else:
            raw = json.loads(run.raw_response_json)
            raw["elements"][0].update(state="unknown", evidence_refs=[], normalized_value=None)
            elements = tuple(
                replace(e, state="unknown", evidence_refs=(), normalized_value=None)
                if e.element_id == "P1"
                else e
                for e in run.guarded.elements
            )
            changed.append(
                replace(
                    run,
                    raw_response_json=json.dumps(raw),
                    guarded=replace(run.guarded, elements=elements),
                )
            )
    assert [
        bool(analyze(inputs, tuple(changed), inv, n)["sc1_confirmation"]) for n in (3, 2, 1)
    ] == expected


@pytest.mark.parametrize("contrary", ["absent", "conflict"])
@pytest.mark.parametrize("required", [1, 2, 3])
def test_any_contrary_replica_blocks_all_thresholds(tmp_path, contrary, required):
    inputs, runs, inv = case(tmp_path)
    raw = json.loads(runs[2].raw_response_json)
    raw["elements"][0].update(state=contrary, evidence_refs=[], normalized_value=None)
    runs = (*runs[:2], replace(runs[2], raw_response_json=json.dumps(raw)))
    result = analyze(inputs, runs, inv, required)
    assert result["sc1_confirmation"] is None and "SC1_CONFLICT" in result["reasons"]


@pytest.mark.parametrize("pages,total", [([], 1), ([1, 2], 2)])
def test_empty_or_missing_page_is_uninspected(tmp_path, pages, total):
    inputs, runs, inv = case(tmp_path, pages=pages, total=total)
    result = analyze(inputs, runs, inv)
    assert result["sc1_confirmation"] is None
    assert "SC1_UNINSPECTED_PAGES" in result["reasons"]


@pytest.mark.parametrize(
    "failure",
    [
        "empty",
        "partial",
        "conflict",
        "unverified",
        "wrong_request",
        "same_provider",
        "wrong_period",
        "missing_attributes",
        "rewrapped_raw",
        "saved_response",
    ],
)
def test_unsafe_inventory_never_supplies_absence(tmp_path, failure):
    def invoke(request):
        result = responder(request)
        raw = json.loads(result["raw_response_json"])
        if failure == "empty":
            raw["records"] = []
        elif failure == "partial" and request["replicate_id"] == 3:
            raw["complete"] = False
        elif failure == "conflict":
            for r in raw["records"]:
                if r["element_id"] == "P2":
                    r["state"] = "conflict"
        elif failure == "unverified":
            raw["records"][0]["evidence"]["char_end"] = 10000
        elif failure == "wrong_request":
            result["request_signature"] = "b" * 64
        elif failure == "same_provider":
            result["provider_response_id"] = "replayed"
        elif failure == "rewrapped_raw":
            raw["packet_sha256"] = "b" * 64
        elif failure == "saved_response":
            result["synthetic"] = False
            result["saved_response_origin"] = dict(replay=True, fresh_model_call=False)
        elif failure == "wrong_period":
            # A period span selected from the metric is literal but cannot match the claim.
            for r in raw["records"]:
                r["attributes"]["period"] = r["attributes"]["metric"]
                r["state"] = "present"
        elif failure == "missing_attributes":
            for r in raw["records"]:
                r["attributes"]["period"] = None
        result["raw_response_json"] = json.dumps(raw)
        return result

    inputs, runs, inv = case(tmp_path, invoke=invoke)
    result = analyze(inputs, runs, inv)
    # Wrong-role attribute must not be accepted as evidence of a different period.
    assert result["sc1_confirmation"] is None


def test_inventory_tampering_and_other_run_rejected(tmp_path):
    inputs, runs, inv = case(tmp_path)
    changed = copy.deepcopy(inv)
    changed["pages"][0]["block_count"] += 1
    with pytest.raises(ValueError, match="REPLAY_MISMATCH"):
        analyze(inputs, runs, changed)
    changed = copy.deepcopy(inv)
    changed["selection"]["document_version_id"] = "00000000-0000-0000-0000-000000000099"
    with pytest.raises(ValueError):
        analyze(inputs, runs, changed)


def test_historical_evaluator_rejects_scoped_state(tmp_path):
    inputs, runs, inv = case(tmp_path)
    from proofops.application.tagging.analysis_scope import _consensus

    tags = _consensus(runs, inputs["packet"], inputs["rulepack"], 1).confirmed_tags
    facts = tuple(
        replace(f, state="absent_in_scope") if f.name == "comparison_baseline" else f
        for f in tags.facts
    )
    claim = inputs["context"].claim
    context = RuleContext(
        claim.tenant_id,
        claim.document_version_id,
        claim.claim_id,
        inputs["packet"].packet_sha256,
        local_synthetic=True,
    )
    with pytest.raises(ValueError, match="scoped absence"):
        evaluate(replace(tags, facts=facts), context, inputs["rulepack"])


def test_new_registry_entries_do_not_change_default():
    from proofops.application.analysis_profile import (
        FINALS_I23_POLICY,
        V2_PROFILE,
        policy_for,
        publication_policy_for,
        sc1_inventory_policies,
    )

    assert (
        policy_for(V2_PROFILE, pinned_hash=canonical_hash(FINALS_I23_POLICY)) == FINALS_I23_POLICY
    )
    for policy in sc1_inventory_policies:
        digest = canonical_hash(policy)
        assert policy_for(V2_PROFILE, pinned_hash=digest) == policy
        assert publication_policy_for(V2_PROFILE, pinned_hash=digest) == policy
        assert policy["integration_profile"].startswith("sc1_")


def test_inventory_provider_caches_once_and_keeps_new_scope_separate(tmp_path):
    from proofops.adapters.local.sc1_inventory_store import SC1InventoryProvider

    inputs = setup(tmp_path)
    calls = []

    def invoke(request):
        calls.append(request)
        return responder(request)

    provider = SC1InventoryProvider(tmp_path / "inventory", model_sha256="a" * 64, invoke=invoke)
    scope = selection(inputs)
    first = provider(inputs["original"], scope)
    assert provider(inputs["original"], scope) == first
    assert len(calls) == first["planned_calls"]
    newer = provider(inputs["original"], selection(inputs, [1, 2], 2))
    assert newer["inventory_sha256"] != first["inventory_sha256"]
    assert provider(inputs["original"], scope) == first


def test_worker_inventory_hook_once_and_checkpoint_replay(tmp_path, monkeypatch):
    from proofops.application.analysis_profile import sc1_inventory_policies
    from proofops.application.runs import RunService

    from tests.integration.test_local_tag_runner import TENANT, verified_setup

    init = RunService.__init__

    def selected(self, *args, **kwargs):
        kwargs.update(
            pipeline_profile="finals-unattended-v2",
            analysis_policy_sha256=canonical_hash(sc1_inventory_policies[0]),
        )
        init(self, *args, **kwargs)

    monkeypatch.setattr(RunService, "__init__", selected)
    service, run_id, runner, _, _ = verified_setup(tmp_path, monkeypatch)
    invocations = []

    def provider(graph, scope):
        invocations.append(scope)
        # The fixture has no semantic inventory labels; the closed gate is intentional.
        return build_inventory(
            graph,
            scope,
            model_sha256="a" * 64,
            invoke=lambda request: {
                **responder(request),
                "raw_response_json": json.dumps(
                    dict(
                        complete=True,
                        records=[],
                        packet_sha256=request["packet_sha256"],
                        replicate_id=request["replicate_id"],
                    )
                ),
            },
        )

    runner.sc1_inventory_provider = provider
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "completed"
    checkpoint = runner.tags.load_snapshot(TENANT, run_id)
    assert len(invocations) == 1
    assert "sc1_inventory" in checkpoint
    assert all(c.get("sc1_confirmation") is None for c in checkpoint["claims"])
    assert runner.tags.load_snapshot(TENANT, run_id) == checkpoint


def test_scope_fields_roundtrip_in_report_formats(tmp_path):
    from proofops.application.reporting import render_report

    inputs, runs, inv = case(tmp_path)
    result = analyze(inputs, runs, inv)
    # Exercise the actual renderer with the additive contract, without changing
    # the existing full-evidence grade or provisional decision meaning.
    from tests.acceptance.test_report import decisions as report_decisions
    from tests.acceptance.test_report import manifest as report_manifest

    manifest, decisions = report_manifest(), report_decisions()
    record = next(iter(decisions.values()))
    record.update({k: result[k] for k in ("sc1_confirmation", "sc1_elements")})
    from proofops.application.reporting import build_report_model

    model = build_report_model(manifest, decisions)
    assert model["claims"][0]["sc1_confirmation"] == result["sc1_confirmation"]
    assert b"sc1_confirmation" in render_report(model, "csv")
    assert "분석 범위 기준 확정" in render_report(model, "html").decode()
    assert "sc1_confirmation" in json.loads(render_report(model, "json"))["claims"][0]


def test_partial_positive_never_becomes_scoped_absence(tmp_path):
    inputs, runs, inv = case(tmp_path)
    first = runs[0]
    source = first.guarded.elements[0].evidence_refs
    elements = tuple(
        replace(e, state="present", evidence_refs=source, normalized_value="40%")
        if e.element_id == "P2"
        else e
        for e in first.guarded.elements
    )
    first = replace(
        first,
        guarded=replace(first.guarded, elements=elements),
        binding_hashes=first.binding_hashes + (("P2", "a" * 64),),
    )
    result = analyze(inputs, (first, *runs[1:]), inv)
    assert next(e for e in result["sc1_elements"] if e["element_id"] == "P2")["state"] == "unknown"


def test_conflict_survives_uncovered_cues(tmp_path):
    from proofops.application.tagging.analysis_scope import InventoryIndex

    from tests.acceptance.test_binding import DIMENSIONS

    def invoke(request):
        result = responder(request)
        raw = json.loads(result["raw_response_json"])
        for record in raw["records"]:
            if record["element_id"] == "P2":
                record["state"] = "conflict"
        # Drop another source's P2 cue, retaining the explicit conflict.
        source_id = raw["records"][0]["evidence"]["source_id"]
        raw["records"] = [
            r
            for r in raw["records"]
            if r["element_id"] != "P2" or r["evidence"]["source_id"] == source_id
        ]
        result["raw_response_json"] = json.dumps(raw)
        return result

    inputs, runs, inv = case(tmp_path, invoke=invoke)
    index = InventoryIndex(inv, inputs["original"])
    key = tuple(
        DIMENSIONS[k].casefold() for k in ("entity", "metric", "facility", "reporting_period")
    )
    assert index.state("P2", key, 3)[0] == "conflict"
    assert analyze(inputs, runs, inv)["sc1_confirmation"] is None
