"""Promotion fails on completed-but-regressed outputs and unknown replay inputs."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


replies = module("predeploy_replies")
gate = module("predeploy_gate")
BASELINE = dict(claims=105, verified=105, tentative=85, max_seconds=361.957, evidence="E9/v12")


def observation(claims=105, verified=105, tentative=85, seconds=350):
    return dict(
        status="completed",
        seconds=seconds,
        unsettled_costs=0,
        result=dict(
            claims=[
                dict(
                    source_quality="verified" if i < verified else "unverified",
                    provisional_grade=dict(evidence_grade="E1" if i < tentative else None),
                )
                for i in range(claims)
            ],
            hold_reasons=[],
            pipeline=dict(status="completed"),
        ),
    )


def test_e12_completed_regression_is_a_release_failure():
    result = gate.compare(observation(62, 47, 28, 905.47), BASELINE)
    assert result["status"] == "failed"
    assert result["failures"] == [
        "claims:62<105",
        "verified:47<105",
        "tentative:28<85",
        "time:905.47>361.957",
    ]


def test_positive_output_at_baseline_passes():
    assert gate.compare(observation(), BASELINE)["status"] == "passed"


@pytest.mark.parametrize("failure", ["empty", "partial", "unsettled", "blocked"])
def test_non_quality_release_failures_are_not_hidden_by_completed(failure):
    value = observation()
    if failure == "empty":
        value = observation(0, 0, 0)
    elif failure == "partial":
        value["result"]["pipeline"]["extraction_outcome"] = dict(
            status="partial", failed_sources=[dict(source_id="failed")]
        )
    elif failure == "unsettled":
        value["unsettled_costs"] = 1
    else:
        value["result"]["hold_reasons"] = ["SOURCE_ATTESTATION_REPLAY_MISMATCH"]
    assert gate.compare(value, BASELINE)["status"] == "failed"


def body(identity, quote="literal claim", replica=1, span="a" * 64):
    return dict(
        model="gpt-6-luna",
        messages=[
            dict(role="system", content="Exact system prompt"),
            dict(
                role="user",
                content=json.dumps(
                    dict(
                        claim_id=identity,
                        replicate_id=replica,
                        untrusted_document_data=dict(
                            quote=quote,
                            span_id=span,
                            bbox=[1, 2, 3, 4],
                            source_refs=[dict(source_id=identity, char_start=3)],
                        ),
                    )
                ),
            ),
        ],
    )


def test_identity_bijection_preserves_literal_schema_replica_and_geometry():
    first = body("11111111-1111-4111-8111-111111111111")
    second = body("22222222-2222-4222-8222-222222222222", span="b" * 64)
    key, old = replies.normalized_wire(first, 1)
    new_key, new = replies.normalized_wire(second, 1)
    assert key == new_key
    assert json.loads(replies.remap_response(json.dumps(dict(span_id="a" * 64)), old, new)) == (
        dict(span_id="b" * 64)
    )
    for altered in [
        body("22222222-2222-4222-8222-222222222222", quote="changed claim"),
        body("22222222-2222-4222-8222-222222222222", replica=2),
    ]:
        assert replies.normalized_wire(altered, 1)[0] != key
    first["messages"][0]["content"] = "new prompt"
    assert replies.normalized_wire(first, 1)[0] != key
    assert replies.normalized_wire(second, 2)[0] != key
    assert replies.remap_response("{invalid", old, new) == "{invalid"


def test_no_positive_baseline_cannot_make_a_zero_claim_smoke_pass():
    cases = [
        dict(
            kind=k,
            recorded_states=["state"],
            pages=list(range(1, 14)),
            claim_pages=[1],
            baseline=BASELINE.copy(),
        )
        for k in ["lg13", "kakao", "table"]
    ]
    gate.validate_manifest(dict(cases=cases))
    cases[0]["baseline"]["verified"] = 0
    with pytest.raises(ValueError, match="Positive baseline"):
        gate.validate_manifest(dict(cases=cases))


def test_same_extraction_context_permutation_matches_but_changed_evidence_does_not():
    original = body("11111111-1111-4111-8111-111111111111")
    user = json.loads(original["messages"][1]["content"])
    data = user["untrusted_document_data"]
    data["source_sentences"] = [dict(sentence_id="c0", text="literal claim")]
    data["context_blocks"] = [
        dict(context_index=i, text=text, bbox=[i, 2, 3, 4])
        for i, text in enumerate(["same nearby A", "same nearby B"])
    ]
    original["messages"][1]["content"] = json.dumps(user)
    key, _ = replies.normalized_wire(original, 0)
    records = {key: [dict(content='{"sentence_ids":["c0"]}')]}
    data["context_blocks"] = [
        context | dict(context_index=i)
        for i, context in enumerate(reversed(data["context_blocks"]))
    ]
    changed = original | dict(
        messages=[original["messages"][0], dict(role="user", content=json.dumps(user))]
    )
    assert replies.lookup_reply(changed, 0, records)[2] is True
    data["context_blocks"][0]["bbox"] = [999, 2, 3, 4]
    changed["messages"][1]["content"] = json.dumps(user)
    assert replies.lookup_reply(changed, 0, records) is None
    assert replies.lookup_reply(original, 1, records) is None


@pytest.mark.parametrize(
    "args,values,expected",
    [
        ([], {}, "WORKER_CPUS=6.0 WORKER_MEMORY=12g"),
        ([], dict(WORKER_CPUS="4", WORKER_MEMORY="8g"), "WORKER_CPUS=4 WORKER_MEMORY=8g"),
        (
            ["--worker-cpus", "6.0", "--worker-memory", "12g"],
            dict(WORKER_CPUS="4", WORKER_MEMORY="8g"),
            "WORKER_CPUS=6.0 WORKER_MEMORY=12g",
        ),
    ],
)
def test_worker_resources_default_env_and_argument_precedence(tmp_path, args, values, expected):
    env = dict(PATH="/usr/bin:/bin", STATE_DIR=str(tmp_path), **values)
    result = subprocess.run(
        ["bash", str(ROOT / "deploy/ec2/deploy.sh"), *args], env=env, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "args,values",
    [
        (["--worker-cpus", "0"], {}),
        (["--worker-cpus", "NaN"], {}),
        (["--worker-memory", "12g\nIMAGE=injected"], {}),
        (["--worker-memory"], {}),
        ([], dict(WORKER_MEMORY="0g")),
        ([], dict(WORKER_CPUS="$(touch /tmp/injected)")),
    ],
)
def test_invalid_resources_are_rejected_before_any_deployment(args, values):
    result = subprocess.run(
        ["bash", str(ROOT / "deploy/ec2/deploy.sh"), *args],
        env=dict(PATH="/usr/bin:/bin", **values),
        capture_output=True,
    )
    assert result.returncode == 2


def test_gate_uses_production_entrypoint_and_none_network():
    source = " ".join((ROOT / "scripts/predeploy_gate.py").read_text().split())
    assert '"scripts/hosted_control.py", "worker", "--once"' in source
    assert '"--network", "none"' in source
    assert "analysis=analyze" not in source
    runtime = (ROOT / "scripts/predeploy_runtime.py").read_text()
    assert "publication_fd=publication_fd" in runtime
    assert "publish_analysis(" not in runtime


def test_compose_env_replacement_retains_worker_limits(tmp_path):
    target = tmp_path / "compose.env"
    target.write_text("WORKER_CPUS=1.5\nWORKER_MEMORY=2560m\n")
    result = subprocess.run(
        [
            "bash",
            "-c",
            'COMMON=$1 TARGET=$2; set --; source "$COMMON"; write_compose_env "$TARGET"',
            "p5-test",
            str(ROOT / "deploy/ec2/common.sh"),
            str(target),
        ],
        env=dict(
            PATH="/usr/bin:/bin",
            STATIC_IP="127.0.0.1",
            ACME_EMAIL="offline@example.com",
            WORKER_CPUS="6.0",
            WORKER_MEMORY="12g",
        ),
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    values = dict(line.split("=", 1) for line in target.read_text().splitlines())
    assert values["WORKER_CPUS"] == "6.0" and values["WORKER_MEMORY"] == "12g"
    assert "write_compose_env" in (ROOT / "deploy/ec2/deploy.sh").read_text()
