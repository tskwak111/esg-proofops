"""Real ledger/fake HTTP: no paid calls or real source-quality approval."""

import json
from dataclasses import asdict, replace
from uuid import UUID

import pytest
from proofops.adapters.local.upstage import MODEL_PRO4, UpstageProbe
from proofops.application.ports.models import ModelBinding
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_tagging import MODEL_PROFILE, UpstageTaggingTransport

from tests.acceptance.test_tagging import setup


def configured(tmp_path, monkeypatch):
    inputs = setup(tmp_path)
    settings = replace(
        inputs["settings"],
        binding=ModelBinding("local-test-tagger", "tagger", False),
        model_id=MODEL_PRO4,
        model_profile=MODEL_PROFILE,
        region="provider-managed-unverified",
    )
    probe = UpstageProbe("test-not-a-key", tmp_path / "budget.sqlite3", model=MODEL_PRO4)
    calls = []

    def post(body):
        calls.append(body)
        return dict(
            id="fixture-provider",
            model=MODEL_PRO4,
            usage=dict(prompt_tokens=20, completion_tokens=10),
            choices=[dict(finish_reason="stop", message=dict(content="{}"))],
        )

    monkeypatch.setattr(probe, "_post", post)
    adapter = UpstageTaggingTransport(
        probe, tmp_path / "receipts", settings=settings, tenant_id=inputs["tenant_id"]
    )
    request = dict(
        tenant_id=inputs["tenant_id"],
        claim_id=inputs["context"].claim.claim_id,
        packet_sha256=inputs["packet"].packet_sha256,
        replicate_id=1,
        request_id=str(UUID(int=987)),
        request_signature=canonical_hash("fixture"),
        binding=asdict(settings.binding),
        model_id=settings.model_id,
        model_profile=settings.model_profile,
        region=settings.region,
        system_prompt=settings.rendered_system
        + "\nValidated classification; tag only its elements: "
        + '{"track":"performance","safe_harbor_category":null}',
        temperature=0,
        max_tokens=100,
    )
    request["user_json"] = json.dumps(
        dict(
            claim_id=request["claim_id"],
            packet_sha256=request["packet_sha256"],
            replicate_id=1,
            untrusted_document_data=dict(allowed_elements=[f"P{i}" for i in range(1, 7)]),
        )
    )
    return adapter, probe, calls, request


def test_receipt_single_reservation_and_duplicate_stop(tmp_path, monkeypatch):
    adapter, probe, calls, request = configured(tmp_path, monkeypatch)
    result = adapter.invoke(request)
    assert result.raw_response_json == "{}" and result.synthetic is False
    assert result.usage.input_tokens == 20
    assert probe.summary()["calls"] == 1 and probe.summary()["unsettled_calls"] == 0
    assert (tmp_path / "receipts" / request["request_id"] / "response.json").exists()
    with pytest.raises(ValueError, match="TAGGING_RECEIPT_EXISTS"):
        adapter.invoke(request)
    assert len(calls) == 1


def test_unknown_transport_stops_siblings_and_retains_reservation(tmp_path, monkeypatch):
    adapter, probe, calls, request = configured(tmp_path, monkeypatch)

    def fail(body):
        calls.append(body)
        raise RuntimeError("secret provider detail")

    monkeypatch.setattr(probe, "_post", fail)
    first = adapter.invoke(request)
    second = adapter.invoke({**request, "request_id": str(UUID(int=988))})
    assert first.usage.status == second.usage.status == "failed"
    assert "secret" not in first.provider_response_json
    assert len(calls) == 1 and probe.summary()["unsettled_calls"] == 1
    assert probe.summary()["committed_usd"] == "1.00"


@pytest.mark.parametrize(
    "change",
    [
        dict(tenant_id=str(UUID(int=777))),
        dict(model_id="other"),
        dict(binding=dict(binding_id="other", role="tagger", synthetic=False)),
        dict(temperature=1),
        dict(replicate_id=True),
        dict(max_tokens=101),
    ],
)
def test_identity_rejected_before_spend(tmp_path, monkeypatch, change):
    adapter, probe, calls, request = configured(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        adapter.invoke({**request, **change})
    assert not calls and probe.summary()["calls"] == 0


def test_compact_references_preserve_source_without_model_copying(tmp_path, monkeypatch):
    adapter, probe, calls, request = configured(tmp_path, monkeypatch)
    original = setup(tmp_path)["packet"].to_dict()["evidence_candidates"][0]["source_refs"][0]
    user = json.loads(request["user_json"])
    user["untrusted_document_data"]["evidence_candidates"] = [dict(source_refs=[original])]
    request["user_json"] = json.dumps(user)

    def post(body):
        calls.append(body)
        assert "\\u" not in body["messages"][1]["content"]
        sent = json.loads(body["messages"][1]["content"])
        assert sent["untrusted_document_data"]["evidence_candidates"][0]["source_refs"] == ["e0"]
        assert (
            sent["untrusted_document_data"]["evidence_catalog"]["e0"]["quote"] == original["quote"]
        )
        return dict(
            id="fixture-provider",
            model=MODEL_PRO4,
            usage=dict(prompt_tokens=20, completion_tokens=10),
            choices=[
                dict(
                    finish_reason="stop",
                    message=dict(
                        content=json.dumps(
                            dict(
                                elements=[
                                    dict(element_id="P1", state="present", evidence_refs=["e0"])
                                ]
                            )
                        )
                    ),
                )
            ],
        )

    monkeypatch.setattr(probe, "_post", post)
    response = adapter.invoke(request)
    assert json.loads(response.raw_response_json)["elements"][0]["evidence_refs"] == [original]
    assert json.loads(response.provider_response_json)["content"] != response.raw_response_json


def test_invented_compact_id_is_unknown_without_refund_or_retry(tmp_path, monkeypatch):
    adapter, probe, calls, request = configured(tmp_path, monkeypatch)

    def post(body):
        calls.append(body)
        return dict(
            id="fixture-provider",
            model=MODEL_PRO4,
            usage=dict(prompt_tokens=20, completion_tokens=10),
            choices=[
                dict(
                    finish_reason="stop",
                    message=dict(content='{"elements":[{"evidence_refs":["outside-packet"]}]}'),
                )
            ],
        )

    monkeypatch.setattr(probe, "_post", post)
    response = adapter.invoke(request)
    assert response.raw_response_json is None and response.usage.status == "succeeded"
    assert probe.summary()["unsettled_calls"] == 0
    assert not (tmp_path / "receipts" / "transport-stop.json").exists()


def test_existing_tagging_guards_and_cache_with_single_monetary_ledger(tmp_path, monkeypatch):
    from proofops.application.budget import cost_summary

    from tests.acceptance.test_tagging import execute

    adapter, probe, calls, _ = configured(tmp_path, monkeypatch)
    inputs = setup(tmp_path)
    inputs.update(settings=adapter._settings, invoke=adapter.invoke, pricing=None)
    counted = []

    def count_messages(system, user):
        # Synthetic token value; verifies wire identity, never model-token accuracy.
        counted.append([dict(role="system", content=system), dict(role="user", content=user)])
        return 20

    inputs["count_input_tokens"] = lambda request: adapter.count_input_tokens(
        request, counter=count_messages
    )

    def post(body):
        calls.append(body)
        user = json.loads(body["messages"][1]["content"])
        wire_schema = json.loads(
            body["messages"][0]["content"]
            .split("\nOutput JSON schema:\n")[1]
            .split("\nValidated classification;")[0]
        )
        assert wire_schema["properties"]["track"] == {"const": "performance"}
        assert wire_schema["$defs"]["Element"]["properties"]["element_id"] == {
            "enum": [f"P{i}" for i in range(1, 7)]
        }
        tags = dict(
            claim_id=user["claim_id"],
            packet_sha256=user["packet_sha256"],
            replicate_id=user["replicate_id"],
            track="performance",
            safe_harbor_category=None,
            elements=[
                dict(
                    element_id=f"P{i}",
                    state="unknown",
                    evidence_refs=[],
                    normalized_value=None,
                    credited_from=None,
                    reason_code="fixture-unresolved",
                )
                for i in range(1, 7)
            ],
            superlative_quote=None,
            warnings=[],
        )
        return dict(
            id="fixture-" + str(user["replicate_id"]),
            model=MODEL_PRO4,
            usage=dict(prompt_tokens=20, completion_tokens=10),
            choices=[dict(finish_reason="stop", message=dict(content=json.dumps(tags)))],
        )

    monkeypatch.setattr(probe, "_post", post)
    runs = execute(inputs)
    assert len(calls) == 3 and [r.replicate_id for r in runs] == [1, 2, 3]
    assert all(r.guarded is not None and r.synthetic for r in runs)
    assert all(r.guarded.elements[0].state == "unknown" for r in runs)
    assert probe.summary()["calls"] == 3 and probe.summary()["unsettled_calls"] == 0
    assert counted == [body["messages"] for body in calls]
    rows = inputs["usage_store"].cost_data(inputs["tenant_id"], runs[0].run_id)
    assert len(rows) == 3
    assert all(row["reservation"]["input_tokens"] == 20 for row in rows)
    costs = cost_summary(inputs["usage_store"], inputs["tenant_id"], runs[0].run_id)
    assert costs["amount"] is None
    recovered = execute(inputs)
    assert len(calls) == 3 and all(r.recovered for r in recovered)
    assert len(counted) == 3  # Recovery neither counts nor dispatches again.


def test_real_tagging_requires_request_counter_before_spend(tmp_path, monkeypatch):
    from tests.acceptance.test_tagging import execute

    adapter, probe, calls, _ = configured(tmp_path, monkeypatch)
    inputs = setup(tmp_path)
    inputs.update(settings=adapter._settings, invoke=adapter.invoke)
    with pytest.raises(ValueError, match="TAGGING_INPUT_COUNTER_REQUIRED"):
        execute(inputs)
    assert not calls and probe.summary()["calls"] == 0
    assert not inputs["usage_store"].cost_data(
        inputs["tenant_id"], inputs["packet"].to_dict()["run_id"]
    )


def test_wire_input_over_budget_never_reaches_provider(tmp_path, monkeypatch):
    from tests.acceptance.test_tagging import execute

    adapter, probe, calls, _ = configured(tmp_path, monkeypatch)
    inputs = setup(tmp_path)
    inputs.update(
        settings=adapter._settings,
        invoke=adapter.invoke,
        count_input_tokens=lambda request: adapter.count_input_tokens(
            request, counter=lambda system, user: 10001
        ),
    )
    runs = execute(inputs)
    assert len(runs) == 3 and all(run.status == "budget_exhausted" for run in runs)
    assert not calls and probe.summary()["calls"] == 0
    assert not list((tmp_path / "receipts").iterdir())


@pytest.mark.parametrize("value", [True, -1, "20", None])
def test_invalid_input_count_is_not_a_cache_failure(tmp_path, monkeypatch, value):
    from tests.acceptance.test_tagging import execute

    adapter, probe, calls, _ = configured(tmp_path, monkeypatch)
    inputs = setup(tmp_path)

    def counter(request):
        if value is None:
            raise ValueError("private tokenizer failure")
        return value

    inputs.update(settings=adapter._settings, invoke=adapter.invoke, count_input_tokens=counter)
    runs = execute(inputs)
    assert all(run.status == "invalid_request" for run in runs)
    assert all(run.errors == ("TAGGING_INPUT_COUNT_INVALID",) for run in runs)
    assert not calls and probe.summary()["calls"] == 0


def test_incomplete_receipt_blocks_new_paid_replica_after_restart(tmp_path, monkeypatch):
    adapter, probe, calls, request = configured(tmp_path, monkeypatch)
    interrupted = tmp_path / "receipts" / str(UUID(int=123456))
    interrupted.mkdir()
    (interrupted / "request.json").write_text("{}")
    response = adapter.invoke(request)
    assert response.usage.status == "failed" and not calls
    assert probe.summary()["calls"] == 0


def test_busy_operation_does_not_dispatch(tmp_path, monkeypatch):
    import fcntl

    adapter, probe, calls, request = configured(tmp_path, monkeypatch)
    with (tmp_path / "receipts" / ".operation.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert adapter.invoke(request).usage.status == "failed"
    assert not calls and probe.summary()["calls"] == 0


def test_unfrozen_classification_is_rejected_before_paid_tagging(tmp_path, monkeypatch):
    adapter, probe, calls, request = configured(tmp_path, monkeypatch)
    request["system_prompt"] = adapter._settings.rendered_system
    with pytest.raises(ValueError, match="CLASSIFICATION_REQUIRED"):
        adapter.invoke(request)
    assert not calls


def test_transport_transform_profile_is_part_of_cache_identity(tmp_path, monkeypatch):
    adapter, probe, _, _ = configured(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="BINDING_INVALID"):
        UpstageTaggingTransport(
            probe,
            tmp_path / "other-receipts",
            settings=replace(adapter._settings, model_profile="unpinned-wire-transform"),
            tenant_id=adapter._tenant,
        )
    assert probe.summary()["calls"] == 0
