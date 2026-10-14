"""Promotion fails on completed-but-regressed outputs and unknown replay inputs."""

import hashlib
import importlib.util
import json
import sqlite3
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
runtime = module("predeploy_runtime")
BASELINE = dict(claims=105, verified=105, tentative=85, max_seconds=361.957, evidence="E9/v12")
CAPTURED = ROOT / "tests/fixtures/predeploy"


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


def test_original_e12_lg13_api_response_fails_against_original_e9_baseline():
    path = CAPTURED / "E12-lg.result.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "767f820035333b8c73a68ad092cf12de564a7ec0f1beab50919e5f42a9d61c08"
    )
    measurement = json.loads((CAPTURED / "E9-lg.measurement.json").read_text())
    timing = json.loads((CAPTURED / "E12-lg.server-timing.json").read_text())
    baseline = {name: measurement[name] for name in ("claims", "verified", "tentative")}
    baseline.update(
        max_seconds=measurement["terminal_seconds"] + measurement["result_fetch_seconds"],
        evidence="perf/E9/lg.measurement.json (v12)",
    )
    result = gate.compare_captured(
        path, dict(kind="lg13", baseline=baseline), timing["server_to_snapshot_seconds"]
    )
    assert result["mode"] == "captured-result-only"
    assert result["status"] == "failed"
    assert result["metrics"] == dict(claims=62, verified=47, tentative=28, confirmed=0)
    assert result["failures"] == [
        "claims:62<105",
        "verified:47<105",
        "tentative:28<85",
        "pipeline_blocked",
        "extraction_partial",
        "time:905.467630147934>361.957",
    ]


def test_captured_result_cli_fails_without_docker(tmp_path):
    cases = [
        dict(
            kind=kind,
            pages=list(range(1, 14)),
            claim_pages=[1],
            recorded_states=["unused"],
            baseline=BASELINE,
        )
        for kind in ("lg13", "kakao", "table")
    ]
    manifest = tmp_path / "cases.json"
    manifest.write_text(json.dumps(dict(cases=cases)))
    output = tmp_path / "result"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/predeploy_gate.py"),
            "--manifest",
            str(manifest),
            "--output",
            str(output),
            "--captured-result",
            str(CAPTURED / "E12-lg.result.json"),
            "--case",
            "lg13",
            "--captured-seconds",
            "905.467630147934",
        ],
        env=dict(PATH=""),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, result.stderr
    captured = json.loads((output / "captured-comparison.json").read_text())
    assert captured["metrics"]["claims"] == 62
    assert captured["mode"] == "captured-result-only"


@pytest.mark.parametrize("seconds", [None, float("nan"), float("inf"), -1, True])
def test_invalid_elapsed_time_cannot_pass(seconds):
    assert gate.compare(observation(seconds=seconds), BASELINE)["status"] == "failed"


def test_positive_output_at_baseline_passes():
    assert gate.compare(observation(), BASELINE)["status"] == "passed"


def test_v19_successful_extraction_status_is_claims_with_ok_code():
    value = observation()
    extraction = dict(status="claims", code="OK", failed_sources=[], page_failures=[])
    value["result"]["pipeline"]["extraction_outcome"] = extraction
    assert gate.compare(value, BASELINE)["status"] == "passed"
    extraction["failed_sources"] = [dict(source_id="failed")]
    assert "extraction_partial" in gate.compare(value, BASELINE)["failures"]
    extraction["failed_sources"] = []
    extraction["code"] = "CLAIM_SOURCE_EXTRACTION_FAILURE"
    assert "extraction_partial" in gate.compare(value, BASELINE)["failures"]


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


def test_distinct_fresh_claims_do_not_exhaust_each_others_reply_attempts():
    first = body("11111111-1111-4111-8111-111111111111")
    second = body("22222222-2222-4222-8222-222222222222")
    key, _ = replies.normalized_wire(first, 1)
    assert replies.normalized_wire(second, 1)[0] == key
    uses = {}
    assert runtime.next_reply_attempt(uses, key, first) == 0
    assert runtime.next_reply_attempt(uses, key, second) == 0
    assert runtime.next_reply_attempt(uses, key, first) == 1
    assert runtime.next_reply_attempt(uses, key, second) == 1


def test_compiler_replays_retained_provider_wire_instead_of_internal_prompt(tmp_path):
    directory = tmp_path / "tagging-receipts/claim/track/request"
    directory.mkdir(parents=True)
    wire = body("11111111-1111-4111-8111-111111111111")
    request = dict(
        system_prompt="Internal prompt before transport adaptation",
        user_json=json.dumps(dict(internal=True)),
        replicate_id=1,
    )
    envelope = dict(
        request=request,
        wire_system=wire["messages"][0]["content"],
        wire_user_json=wire["messages"][1]["content"],
    )
    (directory / "request.json").write_text(json.dumps(envelope))
    (directory / "response.json").write_text(json.dumps(dict(content='{"track":"performance"}')))
    compiled = replies.compile_replies([tmp_path])
    actual = dict(
        model="gpt-6-luna",
        messages=wire["messages"],
        max_completion_tokens=1024,
        temperature=0,
        stream=False,
        reasoning_effort="none",
        store=False,
        service_tier="default",
        response_format=dict(type="json_object"),
        top_p=1,
    )
    assert replies.lookup_reply(actual, 1, compiled["llm"]) is not None
    actual["messages"][0]["content"] = request["system_prompt"]
    actual["messages"][1]["content"] = request["user_json"]
    assert replies.lookup_reply(actual, 1, compiled["llm"]) is None


@pytest.mark.parametrize("asynchronous", [False, True])
def test_parse_archive_uses_ledger_signature_not_request_id_hash(tmp_path, asynchronous):
    archive = tmp_path / "parse-responses"
    archive.mkdir()
    request_id = "11111111-1111-4111-8111-111111111111"
    signature = runtime.parse_request_key(
        b"exact PDF bytes",
        "standard",
        1,
        "document-parse-260128",
        asynchronous=asynchronous,
    )
    raw = dict(
        model="document-parse-260128",
        elements=[dict(text="실제 표")],
        usage=dict(pages=1, standard=[1]),
    )
    response = [raw] if asynchronous else raw
    suffix = "-async.json" if asynchronous else ".json"
    path = archive / (replies.digest(request_id) + suffix)
    path.write_text(json.dumps(response))
    with sqlite3.connect(tmp_path / "upstage.sqlite3") as db:
        db.execute("CREATE TABLE probe_calls (request_id TEXT,signature TEXT,receipt TEXT)")
        db.execute(
            "INSERT INTO probe_calls VALUES (?,?,?)",
            (
                request_id,
                signature,
                json.dumps(
                    dict(
                        mode="standard", response_sha256=replies.digest(response, ensure_ascii=True)
                    )
                ),
            ),
        )
    compiled = replies.compile_replies([tmp_path])
    assert compiled["parse"] == {
        signature: dict(
            asynchronous=asynchronous,
            mode="standard",
            response=response,
            response_sha256=replies.digest(response, ensure_ascii=True),
        )
    }
    for pdf, mode, pages, model, transport in [
        (b"different PDF", "standard", 1, "document-parse-260128", asynchronous),
        (b"exact PDF bytes", "enhanced", 1, "document-parse-260128", asynchronous),
        (b"exact PDF bytes", "standard", 2, "document-parse-260128", asynchronous),
        (b"exact PDF bytes", "standard", 1, "different model", asynchronous),
        (b"exact PDF bytes", "standard", 1, "document-parse-260128", not asynchronous),
    ]:
        assert (
            runtime.parse_request_key(pdf, mode, pages, model, asynchronous=transport) != signature
        )
    path.write_text(json.dumps(dict(model="changed")))
    with pytest.raises(ValueError, match="parse response hash mismatch"):
        replies.compile_replies([tmp_path])


def test_pdfium_transport_normalization_binds_all_page_bytes_and_only_clock_and_id():
    pdf = (
        b"%PDF-1.7\r\npage stream: /CreationDate(D:20261014211421+00'00')\r\n"
        b"3 0 obj\r\n<</CreationDate(D:20261014211421+00'00')"
        b"/Creator(PDFium)/Producer(PDFium)>>\r\nendobj\r\n"
        b"trailer\r\n<<\r\n/Root 1 0 R\r\n/Info 3 0 R\r\n/Size 4/ID[<"
        + b"A" * 32
        + b"><"
        + b"B" * 32
        + b">]>>\r\nstartxref\r\n0\r\n%%EOF\r\n"
    )

    def key(data, mode="standard", model="document-parse-260128", asynchronous=True):
        return replies.pdfium_transport_key(data, mode, model, asynchronous=asynchronous)

    modified = (
        pdf.replace(
            b"<</CreationDate(D:20261014211421+00'00')",
            b"<</CreationDate(D:20261015061421+09'00')",
        )
        .replace(b"A" * 32, b"C" * 32)
        .replace(b"B" * 32, b"D" * 32)
    )
    assert key(pdf) is not None and key(modified) == key(pdf)
    assert key(pdf.replace(b"page stream", b"edited page")) != key(pdf)
    assert key(
        pdf.replace(b"stream: /CreationDate(D:20261014", b"stream: /CreationDate(D:20261015")
    ) != key(pdf)
    assert key(pdf, mode="enhanced") != key(pdf)
    assert key(pdf, model="other-model") != key(pdf)
    assert key(pdf, asynchronous=False) != key(pdf)
    assert key(pdf.replace(b"/Creator(PDFium)", b"/Creator(changed)")) is None


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
    records[key][0]["content"] = '{"sentence_ids":[],"located_quotes":[{"context_index":0}]}'
    assert replies.lookup_reply(changed, 0, records) is None
    records[key][0]["content"] = '{"sentence_ids":["c0"]}'
    data["context_blocks"][0]["bbox"] = [999, 2, 3, 4]
    changed["messages"][1]["content"] = json.dumps(user)
    assert replies.lookup_reply(changed, 0, records) is None
    assert replies.lookup_reply(original, 1, records) is None


def test_ocr_miss_capture_uses_private_mode_and_exact_png_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "DATA", tmp_path)
    png = b"\x89PNG\r\n\x1a\nexact page bytes"
    key = "a" * 64
    name = runtime.capture_input_miss(key, png, kind="ocr")
    path = tmp_path / name
    assert name == "gate-miss-ocr-" + key + ".png"
    assert path.read_bytes() == png
    assert path.stat().st_mode & 0o777 == 0o600
    assert runtime.capture_input_miss(key, png, kind="ocr") == name
    with pytest.raises(ValueError, match="HASH_COLLISION"):
        runtime.capture_input_miss(key, b"changed PNG", kind="ocr")


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
    assert "--capture-misses" in source and "ls /data/gate-miss-*" in source
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
