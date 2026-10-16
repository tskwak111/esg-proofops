"""R8 bounded activation: immutable originals, explicit final API, local lifecycle."""

import argparse
import json
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from time import monotonic

from proofops.adapters.local.c3_publication import LocalC3Publication
from proofops.application.authorization import AuthContext
from proofops.application.exports import REVISION_RECORDS_V2, decode_revision_record
from proofops.application.reviews import ReviewRejected
from proofops.application.tagging.fact_assembly_c3 import POLICY, PROFILE, assemble
from proofops.domain.provenance import canonical_hash
from proofops_api.hosted_results import read_result

from evaluation import c2_pilot

ROOT = c2_pilot.ROOT
OUT = ROOT / "outputs/agent-results/R108-redesign/lab/fix/C3"
C2 = c2_pilot.OUT


def write(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def case():
    # Preserve all C2 artifacts, including its original source/approval receipts.
    c2_pilot.write = lambda name, value: write("origin-" + name, value)
    return c2_pilot.load_case("lg")


def requests():
    data = case()
    original = json.loads((C2 / "requests.json").read_text())["requests"]
    selected = []
    for value in original:
        if value["company"] != "lg":
            continue
        value = deepcopy(value)
        value["id"] = value["id"].replace("C2-", "C3-")
        value["system"] += (
            "\n인증 부합/예정/미취득/철회는 인증 보유가 아니다. M3는 해당 환경경영시스템이 "
            "직접 명명된 전체 인증 문장을 인용하라. 15/17을 전 사업장으로 확대하지 말라. "
            "보고연도는 인증 유효기간이 아니다. 다른 법인/제품/인접 활동에 전용하지 말라."
        )
        policy = (
            POLICY | dict(model_response_policy=c2_pilot.MODEL_RESPONSE_POLICY)
            if hasattr(c2_pilot, "MODEL_RESPONSE_POLICY")
            else None
        )
        if policy is None:
            from proofops.application.analysis_profile import MODEL_RESPONSE_POLICY

            policy = POLICY | dict(model_response_policy=MODEL_RESPONSE_POLICY)
        value["snapshot"]["analysis_profile_policy"] = policy
        value["snapshot"]["analysis_profile_policy_sha256"] = canonical_hash(policy)
        selected.append(value)
    write("requests.json", dict(requests=selected))
    write(
        "source-identity.json",
        dict(claim=asdict(data["context"].claim), packet_sha256=data["packet"].packet_sha256),
    )


def api():
    from proofops.adapters.local.decisions import load_key
    from proofops.adapters.local.openai import OpenAIProbe

    from scripts.finals_demo import FinalsBudget

    ledgers = {p: ROOT / f".local/{p}/budget.sqlite3" for p in ("openrouter", "upstage")}
    ledgers["historical-openai"] = ROOT / ".local/openai/budget.sqlite3"
    ledgers["C2-openai"] = C2 / "api-budget.sqlite3"
    ledgers["openai"] = OUT / "api-budget.sqlite3"
    # USD .50 is stricter than the task's .60 authorization; cumulative fence stays intact.
    fence = FinalsBudget(
        ROOT / "outputs/agent-results/R108-redesign/lab/sprint3/E2E/r108-spend.json",
        ledgers,
        OUT / "paid-calls.jsonl",
        task="C3",
        limit_usd="0.50",
    )
    probe = OpenAIProbe(load_key("openai", ROOT), ledgers["openai"])
    guarded = fence.guarded(OpenAIProbe.complete, "openai", lambda *args: Decimal("0.02"))
    with (OUT / "api-results.jsonl").open("x") as stream:
        for request in json.loads((OUT / "requests.json").read_text())["requests"]:
            probe.configure_response_policy(request["snapshot"], role="elements")
            start = monotonic()
            with probe.response_context(role="elements", replica=request["replica"]):
                response = guarded(
                    probe,
                    request["system"],
                    request["user_json"],
                    request_id=request["id"] + "-" + canonical_hash(request)[:16],
                    max_tokens=request["max_tokens"],
                    json_mode=True,
                    schema_json=request["schema_json"],
                )
            stream.write(
                json.dumps(
                    dict(id=request["id"], result=response, seconds=monotonic() - start),
                    ensure_ascii=False,
                )
                + "\n"
            )
            stream.flush()
            print(
                json.dumps(
                    dict(
                        id=request["id"],
                        schema_valid=response["schema_valid"],
                        cost_usd=response["cost_with_vat_reserve_usd"],
                    )
                ),
                flush=True,
            )
    with fence.transaction() as (_, entry):
        entry["status"] = "completed"
        write("task-budget.json", entry)


def assess(*, historical=False):
    data = case()
    if historical:
        votes = json.loads((C2 / "lg-openai-assembly.json").read_text())["raw_receipts"]
        for row in [
            json.loads(line) for line in (C2 / "api-results.jsonl").read_text().splitlines()
        ]:
            c2_pilot.verify_provider_receipt(row["result"], C2 / "api-budget.sqlite3")
    else:
        reference = json.loads((C2 / "lg-openai-assembly.json").read_text())["identity"]
        results = {
            row["id"]: row["result"]
            for row in map(json.loads, (OUT / "api-results.jsonl").read_text().splitlines())
        }
        votes = []
        for request in json.loads((OUT / "requests.json").read_text())["requests"]:
            response = results[request["id"]]
            c2_pilot.verify_provider_receipt(response, OUT / "api-budget.sqlite3")
            raw = json.loads(response["content"])
            value = dict(
                identity=reference,
                replicate_id=request["replica"],
                request_id=request["id"],
                request_sha256=canonical_hash(request),
                provider_request_id=response["provider_request_id"],
                cache_identity=response["response_request"],
                response_sha256=canonical_hash(response),
                provider="openai",
                simulated=False,
                model_sha256=response["model_binding_sha256"],
                prompt_sha256=canonical_hash(
                    dict(system=request["system"], schema=c2_pilot.output_schema())
                ),
                raw=raw,
                raw_sha256=canonical_hash(raw),
            )
            votes.append(value | dict(vote_sha256=canonical_hash(value)))
    inputs = {k: data[k] for k in ("context", "graph", "packet", "rulepack")}
    receipt = assemble(votes, **inputs)
    write(
        "historical-active-assembly.json" if historical else "lg-active-assembly.json",
        receipt.to_dict(),
    )
    if not receipt.to_dict()["public_auto_confirmed"]:
        raise ValueError("C3_FINAL_NOT_ELIGIBLE:" + str(receipt.to_dict()["unresolved"]))
    path = OUT / ("historical-lifecycle" if historical else "publication")
    path.mkdir(exist_ok=True)
    publication = LocalC3Publication(path)
    pdf = next(
        row["path"]
        for row in json.loads((c2_pilot.E02 / "source-inventory.json").read_text())
        if row["company"] == "lg"
    )
    review = publication.initialize(
        data,
        receipt,
        source=Path(pdf).read_bytes(),
        parser_artifact=json.loads((C2 / "lg-pilot-graph.json").read_text()),
    )
    claim = data["context"].claim
    run = data["packet"].to_dict()["run_id"]
    (path / "pilot.json").write_text(
        json.dumps(
            dict(
                tenant_id=claim.tenant_id,
                run_id=run,
                claim_id=claim.claim_id,
                publication_profile=PROFILE,
            )
        )
    )
    (path / "outcome.json").write_text(json.dumps(dict(status="completed", reason=None)))
    before = publication.store.history(claim.tenant_id, run, claim.claim_id)
    old = canonical_hash(before)
    assert (
        publication.service.publish(publication.load_inputs(claim.tenant_id, run, claim.claim_id))
        == review
    )
    reopened = LocalC3Publication(path)
    loaded = reopened.load_inputs(claim.tenant_id, run, claim.claim_id)
    result = read_result(path, claim.tenant_id, [36])
    assert result["claims"][0]["confirmed_grade"] == "E3"
    assert result["claims"][0]["decision"]["semantic_hash"] == loaded.decision.semantic_hash
    export = reopened.export(claim.tenant_id, run, claim.claim_id)
    decoded = decode_revision_record(export, encoding=REVISION_RECORDS_V2)
    assert decoded["decision"]["decision"]["semantic_hash"] == loaded.decision.semantic_hash
    actor = AuthContext(
        "c3-local-reviewer", claim.tenant_id, "reviewer", frozenset({"viewer", "reviewer"}), "test"
    )
    body = dict(
        base_tag_revision=1,
        track="management",
        reason="C3 원문 태깅 유지",
        elements=[asdict(e) for e in loaded.consensus.candidate_elements],
    )
    try:
        reopened.service.resolve_review(
            actor,
            review["review_id"],
            body,
            if_match='"2"',
            idempotency_key="c3-stale-revision-request",
        )
    except ReviewRejected as exc:
        assert exc.status == 412
    else:
        raise AssertionError("If-Match did not reject stale revision")
    assert canonical_hash(reopened.store.history(claim.tenant_id, run, claim.claim_id)) == old
    write("historical-result.json" if historical else "result.json", result)
    write("historical-export.json" if historical else "export.json", export)
    # A real human tag edit creates revision 2 without rewriting revision 1/export.
    resolved = reopened.service.resolve_review(
        actor,
        review["review_id"],
        body,
        if_match='"1"',
        idempotency_key="c3-current-revision-request",
    )
    after = reopened.store.history(claim.tenant_id, run, claim.claim_id)
    assert after["tags"][0] == before["tags"][0] and after["decisions"][0] == before["decisions"][0]
    export_name = "historical-export.json" if historical else "export.json"
    assert canonical_hash(json.loads((OUT / export_name).read_text())) == canonical_hash(export)
    assert resolved["new_tag_revision"] == 2
    write(
        "historical-lifecycle.json" if historical else "lifecycle.json",
        dict(
            public_auto_confirmed=1,
            stored_resumed_reloaded=True,
            api_export_same_semantic_hash=True,
            stale_if_match_status=412,
            human_new_tag_revision=resolved["new_tag_revision"],
            old_revision_hash=old,
            old_revision_preserved=True,
            source_sha256=sha256(Path(pdf).read_bytes()).hexdigest(),
            receipt_sha256=receipt.receipt_sha256,
        ),
    )
    print(
        json.dumps(
            dict(public_auto_confirmed=1, receipt_sha256=receipt.receipt_sha256), ensure_ascii=False
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["requests", "api", "assess", "historical"])
    args = parser.parse_args()
    if args.stage == "requests":
        requests()
    elif args.stage == "api":
        api()
    else:
        assess(historical=args.stage == "historical")
