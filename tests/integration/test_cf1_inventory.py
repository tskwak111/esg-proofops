"""CF1 exact quote wire: keep source/coverage/replica guards unchanged."""

import copy
import json

import pytest
from proofops.domain.provenance import canonical_hash


def test_cf1_pin_and_request_identity_are_opt_in(tmp_path):
    from proofops.application import analysis_profile as profiles
    from proofops.application.tagging.cf1_inventory import POLICY
    from proofops.application.tagging.element_inventory import inventory_request, plan_inventory

    from tests.acceptance.test_tagging import setup
    from tests.integration.test_sc1_scope import selection

    inputs = setup(tmp_path)
    scope = selection(inputs)
    old = inventory_request(plan_inventory(inputs["original"], scope)["chunks"][0], 1, "a" * 64)
    new = inventory_request(
        plan_inventory(inputs["original"], scope | dict(cf1_inventory=POLICY))["chunks"][0],
        1,
        "a" * 64,
    )
    assert old["prompt_sha256"] != new["prompt_sha256"]
    assert old["request_id"] != new["request_id"]
    assert (
        profiles.policy_for(
            profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I27_POLICY)
        )
        == profiles.FINALS_I27_POLICY
    )
    assert (
        profiles.publication_policy_for(
            profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.CF1_POLICY)
        )
        == profiles.CF1_POLICY
    )


def test_quote_restore_preserves_absolute_unicode_offsets():
    from proofops.application.tagging.cf1_inventory import restore_response

    chunk = dict(
        spans=[
            dict(
                kind="paragraph",
                source_ref=dict(
                    source_id="source",
                    char_start=300,
                    char_end=321,
                    quote="당사는 2025년 국내 사업장을 관리.",
                ),
            )
        ]
    )
    raw = dict(
        complete=True,
        packet_sha256="a" * 64,
        replicate_id=1,
        records=[
            dict(
                element_id="M1",
                state="present",
                evidence="s0",
                attributes=dict(
                    subject="당사",
                    metric=None,
                    site="국내 사업장",
                    period="2025년",
                ),
            )
        ],
    )
    saved = copy.deepcopy(raw)
    value = restore_response(raw, chunk)
    assert raw == saved
    assert value["records"][0]["attributes"]["period"] == dict(
        source_id="source", char_start=304, char_end=309
    )
    for invalid in ["2025", "2026년", "사업장 사업장"]:
        bad = copy.deepcopy(raw)
        bad["records"][0]["attributes"]["period"] = invalid
        if invalid == "2025":
            assert (
                restore_response(bad, chunk)["records"][0]["attributes"]["period"]["char_end"]
                == 308
            )
        else:
            with pytest.raises(ValueError, match="CF1_QUOTE_NOT_UNIQUE"):
                restore_response(bad, chunk)


def test_cf1_bad_period_is_uninspected_with_reason_not_absence(tmp_path):
    from proofops.application.tagging.cf1_inventory import POLICY
    from proofops.application.tagging.element_inventory import build_inventory, replay_inventory

    from tests.acceptance.test_tagging import setup
    from tests.integration.test_sc1_scope import responder, selection

    inputs = setup(tmp_path)

    def invoke(req):
        response = responder(req)
        ref = req["untrusted_document_data"]["spans"][0]["source_ref"]
        raw = dict(
            complete=True,
            packet_sha256=req["packet_sha256"],
            replicate_id=req["replicate_id"],
            records=[
                dict(
                    element_id="M1",
                    state="unknown",
                    evidence="s0",
                    attributes=dict(
                        subject=None,
                        metric=None,
                        site=None,
                        period=ref["quote"],
                    ),
                )
            ],
        )
        return response | dict(raw_response_json=json.dumps(raw))

    result = build_inventory(
        inputs["original"],
        selection(inputs) | dict(cf1_inventory=POLICY),
        model_sha256="a" * 64,
        invoke=invoke,
    )
    assert result["completed_calls"] == 0
    assert result["pages"][0]["status"] == "uninspected"
    assert result["chunks"][0]["votes"][0]["cf1_validation_error"] == "SC1_PERIOD_ROLE_INVALID"
    assert replay_inventory(result, inputs["original"]) == result


def compact_reply(request):
    from tests.integration.test_sc1_scope import responder

    response = responder(request)
    payload = json.loads(response["raw_response_json"])
    spans = request["untrusted_document_data"]["spans"]
    for record in payload["records"]:
        index, ref = next(
            (i, span["source_ref"])
            for i, span in enumerate(spans)
            if span["source_ref"]["source_id"] == record["evidence"]["source_id"]
        )
        record["evidence"] = f"s{index}"
        record["attributes"] = {
            k: ref["quote"][v["char_start"] - ref["char_start"] : v["char_end"] - ref["char_start"]]
            if v
            else None
            for k, v in record["attributes"].items()
        }
    return response | dict(raw_response_json=json.dumps(payload))


def test_cf1_real_worker_transport_receipts_and_replay(tmp_path, monkeypatch):
    from proofops.application.tagging.cf1_inventory import POLICY
    from proofops.application.tagging.element_inventory import inventory_request, plan_inventory
    from proofops_worker.sc1_inventory import load_inventory

    from tests.integration.test_i24_inventory import runtime
    from tests.integration.test_sc1_scope import selection

    live, inputs, calls, events = runtime(tmp_path, monkeypatch)
    live.snapshot["analysis_profile_policy"]["cf1_inventory"] = POLICY
    selected = selection(inputs) | dict(cf1_inventory=POLICY)
    chunk = plan_inventory(live.graph, selected)["chunks"][0]

    def post(body):
        calls.append(body)
        # OpenAI JSON mode rejects a request unless a message mentions JSON.
        # schema_json in probe.complete is only a local response validator.
        from proofops.application.tagging.cf1_inventory import SCHEMA
        from proofops.domain.rulepacks import canonical_json

        assert body["response_format"] == {"type": "json_object"}
        assert "JSON schema: " + canonical_json(SCHEMA) in body["messages"][0]["content"]
        user = json.loads(body["messages"][1]["content"])
        assert "char_start" not in body["messages"][1]["content"]
        assert user["untrusted_document_data"]["spans"][0]["cue_elements"]
        request = inventory_request(chunk, user["replicate_id"], live.settings.model_sha256)
        return dict(
            id="fixture-" + request["request_id"],
            model="gpt-6-luna",
            usage=dict(prompt_tokens=100, completion_tokens=50, prompt_tokens_details={}),
            choices=[
                dict(
                    finish_reason="stop",
                    message=dict(content=compact_reply(request)["raw_response_json"]),
                )
            ],
        )

    monkeypatch.setattr(live.probe, "_post", post)
    inv = load_inventory(live, live.graph, selected)
    assert inv["completed_calls"] == inv["planned_calls"] == len(calls) == 3
    assert inv["pages"][0]["status"] == "inspected"
    assert not inv["chunks"][0]["uncovered_cues"]
    assert load_inventory(live, live.graph, selected) == inv
    assert len(calls) == 3
    assert live.probe.summary()["unsettled_calls"] == 0


@pytest.mark.parametrize(
    "fault",
    [
        "unknown_id",
        "wrong_packet",
        "conflict",
        "unreadable",
        "unknown",
        "omit_cues",
        "missing_page",
    ],
)
def test_cf1_never_confirms_faults_as_absence(tmp_path, fault):
    from proofops.application.tagging.cf1_inventory import POLICY
    from proofops.application.tagging.element_inventory import build_inventory

    from tests.integration.test_sc1_scope import analyze, case, selection

    inputs, runs, _ = case(tmp_path)

    def invoke(request):
        response = compact_reply(request)
        raw = json.loads(response["raw_response_json"])
        if fault == "unknown_id":
            raw["records"][0]["evidence"] = "s999"
        elif fault == "wrong_packet":
            raw["packet_sha256"] = "b" * 64
        elif fault in ("conflict", "unreadable", "unknown"):
            for record in raw["records"]:
                record["state"] = fault
        elif fault == "omit_cues":
            raw["records"] = []
        return response | dict(raw_response_json=json.dumps(raw))

    scope = (
        selection(inputs, pages=[1, 2], total=2) if fault == "missing_page" else selection(inputs)
    )
    inv = build_inventory(
        inputs["original"], scope | dict(cf1_inventory=POLICY), model_sha256="a" * 64, invoke=invoke
    )
    result = analyze(inputs, runs, inv, 3)
    assert result["sc1_confirmation"] is None


def test_cf1_hosted_pin_reaches_child_argv(tmp_path):
    from proofops.application.analysis_profile import CF1_POLICY

    from deploy.public.offline_fixture import source_pdf
    from evaluation.hosted_r108 import prepare_argv

    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(source_pdf())
    pin = canonical_hash(CF1_POLICY)
    argv = prepare_argv(
        pdf,
        tmp_path / "state",
        "11111111-1111-4111-8111-111111111111",
        dict(
            report_year=2025,
            period_start="2025-01-01",
            period_end="2025-12-31",
            analysis_profile="finals-unattended-v2",
        ),
        dict(analysis_profile="finals-unattended-v2", analysis_profile_sha256=pin),
    )
    assert argv[argv.index("--analysis-policy-sha256") + 1] == pin


def test_cf1_ambiguous_literal_is_rejected_without_selecting_an_occurrence():
    from proofops.application.tagging.cf1_inventory import restore_response

    text = "2025년 기준, 2025년 실적"
    chunk = dict(
        spans=[
            dict(
                source_ref=dict(
                    source_id="source", char_start=50, char_end=50 + len(text), quote=text
                )
            )
        ]
    )
    raw = dict(
        complete=True,
        packet_sha256="a" * 64,
        replicate_id=1,
        records=[
            dict(
                element_id="P1",
                state="present",
                evidence="s0",
                attributes=dict(subject=None, metric=None, site=None, period="2025년"),
            )
        ],
    )
    with pytest.raises(ValueError, match="CF1_QUOTE_NOT_UNIQUE"):
        restore_response(raw, chunk)


@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("three_absence", (True, True)),
        ("two_absence_one_unknown", (False, True)),
        ("two_absence_one_unreadable", (False, True)),
        ("two_absence_one_failed", (False, True)),
        ("one_absence_two_unknown", (False, False)),
        ("all_unknown", (False, False)),
        ("all_unreadable", (False, False)),
        ("verified_present_dissent", (False, False)),
        ("verified_conflict_dissent", (False, False)),
        ("contrary_in_invalid_reply", (False, False)),
        ("contrary_with_unresolved_attributes", (True, False)),
        ("two_omit_cues", (False, False)),
        ("missing_source_page", (False, False)),
    ],
)
def test_dec125_scope_comparison_and_false_confirm_counterexamples(tmp_path, scenario, expected):
    from proofops.application.tagging.cf1_inventory import MAJORITY_POLICY, POLICY
    from proofops.application.tagging.element_inventory import build_inventory, replay_inventory

    from tests.integration.test_sc1_scope import analyze, case, selection

    inputs, runs, _ = case(tmp_path)

    def invoke(request):
        response = compact_reply(request)
        raw = json.loads(response["raw_response_json"])
        replica = request["replicate_id"]
        if scenario == "two_absence_one_failed" and replica == 3:
            raise RuntimeError("test transport failure")
        for record in raw["records"]:
            if record["element_id"] == "P1":
                continue
            if (
                (
                    scenario in ("two_absence_one_unknown", "two_absence_one_unreadable")
                    and replica == 3
                )
                or (scenario == "one_absence_two_unknown" and replica >= 2)
                or scenario in ("all_unknown", "all_unreadable")
            ):
                record["state"] = "unreadable" if "unreadable" in scenario else "unknown"
            if (
                scenario
                in (
                    "verified_present_dissent",
                    "verified_conflict_dissent",
                    "contrary_in_invalid_reply",
                    "contrary_with_unresolved_attributes",
                )
                and replica == 3
                and record["element_id"] == "P2"
            ):
                record["state"] = (
                    "conflict" if scenario == "verified_conflict_dissent" else "present"
                )
                if scenario == "contrary_with_unresolved_attributes":
                    record["attributes"]["subject"] = None
        if scenario == "contrary_in_invalid_reply" and replica == 3:
            raw["records"][-1]["evidence"] = "nonexistent-span"
        if scenario == "two_omit_cues" and replica >= 2:
            raw["records"] = []
        return response | dict(raw_response_json=json.dumps(raw))

    scope = (
        selection(inputs, pages=[1, 2], total=2)
        if scenario == "missing_source_page"
        else selection(inputs)
    )
    results = []
    for policy in (POLICY, MAJORITY_POLICY):
        inv = build_inventory(
            inputs["original"],
            scope | dict(cf1_inventory=policy),
            model_sha256="a" * 64,
            invoke=invoke,
        )
        assert replay_inventory(inv, inputs["original"]) == inv
        result = analyze(inputs, runs, inv)
        results.append(bool(result["sc1_confirmation"]))
        if policy == MAJORITY_POLICY:
            assert result["policy"]["cf1_absence_agreement"]["required_absence_votes"] == 2
            if scenario.startswith("verified_") or scenario.startswith("contrary_"):
                assert "SC1_INVENTORY_CONFLICT" in result["reasons"]
            if scenario == "contrary_in_invalid_reply":
                assert inv["completed_calls"] == 2
                assert inv["pages"][0]["status"] == "inspected"
            if scenario == "two_absence_one_failed":
                assert inv["completed_calls"] == 2
                assert inv["chunks"][0]["votes"][2]["valid"] is False
            if result["sc1_confirmation"]:
                assert result["sc1_confirmation"]["evidence_grade"] == "E1"
    assert tuple(results) == expected


@pytest.mark.parametrize("quality", ["unverified", "conflicted", "unreadable", "unlocated"])
def test_dec125_does_not_override_source_coverage(tmp_path, quality):
    from dataclasses import replace

    from proofops.application.tagging.cf1_inventory import MAJORITY_POLICY
    from proofops.application.tagging.element_inventory import build_inventory

    from tests.acceptance.test_tagging import setup
    from tests.integration.test_sc1_scope import selection

    inputs = setup(tmp_path)
    graph = replace(
        inputs["original"],
        blocks=tuple(replace(b, quality=quality) for b in inputs["original"].blocks),
    )
    selected = selection(inputs | dict(original=graph)) | dict(cf1_inventory=MAJORITY_POLICY)
    inv = build_inventory(graph, selected, model_sha256="a" * 64, invoke=compact_reply)
    assert inv["pages"][0]["status"] == "uninspected"
    assert inv["pages"][0]["errors"]
    assert not inv["candidates"]


@pytest.mark.parametrize("rotating_dissent", [False, True])
def test_dec125_requires_same_two_replicas_across_chunks(rotating_dissent):
    from dataclasses import replace

    from proofops.application.fxh_policy import POLICY as FXH_POLICY
    from proofops.application.ingest.graph_fusion import (
        CandidateBatch,
        CandidateBlock,
        fuse_candidates,
    )
    from proofops.application.tagging.analysis_scope import InventoryIndex
    from proofops.application.tagging.cf1_inventory import MAJORITY_POLICY
    from proofops.application.tagging.element_inventory import (
        build_inventory,
        plan_inventory,
        selection_from_snapshot,
    )
    from proofops.domain.documents import NativeSource, PageGeometry

    from tests.acceptance.test_binding import DIMENSIONS
    from tests.acceptance.test_citations import MANIFEST, RUN, TENANT, VERSION

    text = " | ".join(DIMENSIONS.values()) + " | 40%"
    blocks = tuple(
        CandidateBlock(
            "paragraph",
            NativeSource(
                VERSION,
                MANIFEST,
                RUN,
                str(i),
                1,
                None,
                (10, 10 + i * 50, 500, 40 + i * 50),
                "pdf_bottom_left_points",
                text,
                0,
                len(text),
            ),
            PageGeometry(600, 800, 0, (0, 0, 600, 800)),
        )
        for i in range(9)
    )
    batch = CandidateBatch(
        TENANT,
        VERSION,
        MANIFEST,
        "a" * 64,
        RUN,
        "synthetic",
        "1",
        "synthetic",
        "b" * 64,
        blocks,
        synthetic=True,
    )
    graph = fuse_candidates((batch,), tenant_id=TENANT)
    graph = replace(graph, blocks=tuple(replace(b, quality="verified") for b in graph.blocks))
    selection = selection_from_snapshot(
        dict(
            document=dict(version_id=VERSION, sha256=graph.source_sha256, page_count=1),
            selected_pages=[1],
        ),
        graph,
        RUN,
    ) | dict(fxh_inventory_execution=FXH_POLICY, cf1_inventory=MAJORITY_POLICY)
    chunks = plan_inventory(graph, selection)["chunks"]
    assert len(chunks) == 2

    def invoke(request):
        failed = (
            2 if rotating_dissent and request["packet_sha256"] == chunks[1]["chunk_sha256"] else 3
        )
        if request["replicate_id"] == failed:
            raise RuntimeError("synthetic transport failure")
        return compact_reply(request)

    inv = build_inventory(graph, selection, model_sha256="a" * 64, invoke=invoke)
    assert inv["completed_calls"] == 4
    assert inv["pages"][0]["status"] == ("uninspected" if rotating_dissent else "inspected")
    key = tuple(
        DIMENSIONS[k].casefold() for k in ("entity", "metric", "facility", "reporting_period")
    )
    assert InventoryIndex(inv, graph).state("P2", key, 3)[0] == (
        "unknown" if rotating_dissent else "absent_in_scope"
    )
