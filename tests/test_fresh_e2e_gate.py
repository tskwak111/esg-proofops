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
