"""Bounded E21 table probe: fresh element votes, unchanged historical source authority.

Only after-arm headers get a fresh local native-PDF read. Frozen extraction and
preliminary classifications are shared; no saved element votes enter the model.
The full runtime handles wire formatting, restoration, admission and DEC-125/127.
"""

import argparse
import json
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from jsonschema import Draft202012Validator
from proofops.adapters.aws.usage import LocalSQLiteUsageStore
from proofops.adapters.cache.aws import ImmutableResponseCache, InMemoryImmutableCacheClient
from proofops.adapters.local.openai import OpenAIProbe
from proofops.adapters.local.tb1_claim_source import attest_headers
from proofops.adapters.local.verified_read_cache import _project_owned_cells
from proofops.application.analysis_profile import FINALS_I29B_POLICY, TB1_POLICY
from proofops.application.budget import BudgetLimits, RoleLimit, TokenUsage
from proofops.application.claims import Claim, ExtractionProfile, ExtractionReceipt
from proofops.application.evidence.binding import ClaimContext, local_relation_tags
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.ports.models import ModelBinding
from proofops.application.tagging.cf6_confirmation import confirmation_result
from proofops.application.tagging.service import RawTagResponse, TaggingSettings, tag_replicates
from proofops.application.tagging.tracks import TrackCandidate
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.engine import RuleContext
from proofops.domain.values import SourceRef
from proofops_agent.upstage_tagging import UpstageTaggingTransport
from proofops_worker.live_tagging import LiveTaggingRuntime

from evaluation.tb1_retained_graph import _EmptyDiscovery, restore
from tests.acceptance.test_rules import pack

POLICIES = dict(before=FINALS_I29B_POLICY, after=TB1_POLICY)


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def context_for(item, graph):
    data = item["frozen_packet"]
    receipt = data["extraction_provenance"]
    claim = Claim(
        data["claim_id"],
        graph.tenant_id,
        graph.document_version_id,
        graph.parse_manifest_id,
        graph.source_sha256,
        data["atomic_quote"],
        tuple(SourceRef(**r) for r in data["claim_source_refs"]),
        "verified"
        if all(r["verification_state"] == "verified" for r in data["claim_source_refs"])
        else "unverified",
        (),
        ExtractionReceipt(**(receipt | dict(profile=ExtractionProfile(**receipt["profile"])))),
        data["claim_revision"],
    )
    return ClaimContext(
        claim,
        {
            k: SourceRef(**v["replicate_values"][0])
            if v["state"] == "agreed" and v["replicate_values"][0]
            else None
            for k, v in item["preliminary_agreement"]["dimensions"].items()
        },
    )


def cases(stored, sources, output):
    for company in ("lg", "kakao"):
        directory = stored / company
        artifact_path = directory / "job-artifacts.json"
        artifacts = [r["value"] for r in json.loads(artifact_path.read_text())]
        graph, tagging, _ = restore(directory, artifacts)
        source_path = next(
            p
            for p in (sources / company).glob("*.pdf")
            if sha256(p.read_bytes()).hexdigest() == graph.source_sha256
        )
        all_refs = tuple(
            SourceRef(**r)
            for item in tagging["claims"]
            if item.get("frozen_packet")
            for r in item["frozen_packet"]["claim_source_refs"]
        )
        proofs = attest_headers(
            graph, source_path.read_bytes(), all_refs, tenant_id=graph.tenant_id
        )
        body = dict(
            records=[{k: p[k] for k in ("ref", "status", "reason")} for p in proofs],
            pb1_cell_proofs=proofs,
        )
        body["artifact_sha256"] = canonical_hash(body)
        _, after = _project_owned_cells(
            body, graph, _EmptyDiscovery(), graph.tenant_id, failed_state="candidate"
        )
        write(output / f"{company}.headers.json", body)
        write(
            output / f"{company}.source-provenance.json",
            dict(
                stored_artifacts_sha256=sha256(artifact_path.read_bytes()).hexdigest(),
                source_path=str(source_path),
                source_sha256=graph.source_sha256,
                before_graph_sha256=canonical_hash(asdict(graph)),
                after_graph_sha256=canonical_hash(asdict(after)),
                preserved_authority="exact-hash-restored-E21-receipts",
                new_authority="fresh-native-PDF-header-rows-only",
            ),
        )
        # Selection depends only on literal table contents, not past votes/grades.
        tables = {b.source_id for b in graph.blocks if b.kind == "table"}
        pool = [
            i
            for i in tagging["claims"]
            if i.get("frozen_packet")
            and i["frozen_packet"]["claim_source_refs"][0]["source_id"] in tables
        ]
        if company == "lg":
            numeric = sorted(
                [i for i in pool if i["frozen_packet"].get("qt1_table_tuples")],
                key=lambda i: i["claim_id"],
            )[:6]
            controls = [
                i
                for i in pool
                if i["frozen_packet"]["track"] == "goal"
                or "4.8" in i["frozen_packet"]["atomic_quote"]
            ]
            selected = numeric + controls
        else:
            selected = [
                i
                for i in pool
                if any(
                    s in i["frozen_packet"]["atomic_quote"]
                    for s in ("0.027", "13.4", "78.0", "10.0%", "253 tCO", "524 tCO")
                )
            ]
        for item in selected:
            for arm, original in (("before", graph), ("after", after)):
                yield company, item, tagging, arm, original


def relation_roles(item, graph, context, packet, tagging, variant, exchange):
    runtime = object.__new__(LiveTaggingRuntime)
    runtime.graph = graph
    runtime.auth = SimpleNamespace(tenant_id=graph.tenant_id)
    runtime.snapshot = dict(
        run_id=packet.to_dict()["run_id"],
        analysis_profile_policy=POLICIES[variant],
        rulepack=asdict(replace(pack(), tenant_id=graph.tenant_id)),
    )
    runtime.attribution_policy = tagging["relation_attribution_policy"]
    raw = tagging["relation_settings"]
    runtime.relation_settings = TaggingSettings(
        **(raw | dict(binding=ModelBinding(**raw["binding"])))
    )
    runtime.relation_records = {}
    runtime.preliminary_records = {context.claim.claim_id: item.get("preliminary_records", [])}

    def replicas(prefix, claim, envelope, settings, transport, records, validate, **kwargs):
        answers = []
        for replica in (1, 2, 3):
            unknown = dict(
                relations=[
                    dict(
                        source_index=s["source_index"],
                        dimensions=dict(entity=None, metric=None, reporting_period=None),
                    )
                    for s in envelope["untrusted_document_data"]["sources"]
                ]
            )
            raw = exchange(
                "relations",
                replica,
                settings.system_prompt,
                envelope,
                json.loads(settings.schema_json),
                unknown,
            )
            try:
                roles, values = validate(raw)
                answers.append(roles)
            except ValueError:
                return None
        return answers

    runtime._source_replicas = replicas
    runtime.relation_transport = None
    result = runtime.relations(context.claim, packet)
    stops = [
        r
        for r in runtime.relation_records.get(context.claim.claim_id, [])
        if r.get("stable_reason", {}).get("category") == "local_stop"
    ]
    if stops:
        raise ValueError("EV1_RELATION_LOCAL_STOP:" + str(stops))
    return result or {}


def execute(item, tagging, variant, graph, output, exchange):
    context = context_for(item, graph)
    data = deepcopy(item["frozen_packet"])
    data.pop("packet_sha256")
    data.pop("display_text", None)
    if data.get("qt1_baseline_receipt"):
        if data["qt1_baseline_receipt"]["links"]:
            raise ValueError("TB1_BASELINE_RECEIPT_OUTSIDE_SAMPLE")
        # No maintenance baseline is offered in this table sample, in either arm.
        # Its old inventory identity cannot be transplanted to the new header graph.
        data.pop("qt1_baseline_receipt")
    data["graph_sha256"] = canonical_hash(asdict(graph))
    data["cf6_analysis_policy_sha256"] = canonical_hash(POLICIES[variant])
    packet = freeze_packet(data)
    if variant == "after":
        runtime = object.__new__(LiveTaggingRuntime)
        runtime.graph = graph
        runtime.auth = SimpleNamespace(tenant_id=graph.tenant_id)
        runtime.snapshot = dict(analysis_profile_policy=POLICIES[variant])
        packet = runtime.display_packet(packet, claim=context.claim)
    data = packet.to_dict()
    roles = relation_roles(item, graph, context, packet, tagging, variant, exchange)
    roles.update(local_relation_tags(context))
    settings = TaggingSettings(
        **(
            tagging["tagging_settings"]
            | dict(binding=ModelBinding("tb1-blind-sim", "tagger", True))
        )
    )
    rules = replace(pack(), tenant_id=graph.tenant_id)
    assert rules.sha256 == data["rule_sha256"]
    budget = LocalSQLiteUsageStore(output / (str(uuid4()) + ".sqlite3"))
    budget.create_budget(
        graph.tenant_id,
        data["run_id"],
        graph.document_version_id,
        BudgetLimits(1000000, 1000000, (RoleLimit("tagger", 3, 100000, 100000, 1000000),)),
    )
    transport = object.__new__(UpstageTaggingTransport)
    transport._settings = settings
    transport._authorize_request = lambda request: None
    transport._probe = OpenAIProbe(
        "offline-simulation", output / "wire.sqlite3", wire_policy_version=2
    )
    transport._probe.configure_response_policy(
        dict(
            analysis_profile_policy=POLICIES[variant],
            analysis_profile_policy_sha256=canonical_hash(POLICIES[variant]),
            tenant_id=graph.tenant_id,
            document=dict(sha256=graph.source_sha256),
        ),
        role="elements",
    )
    transport._probe._post = lambda *_: (_ for _ in ()).throw(AssertionError("TB1_NO_API"))

    def invoke(request):
        system, user, refs, _, schema = transport._wire_request(request)
        unknown = dict(
            track=data["track"],
            safe_harbor_category=data.get("safe_harbor_category"),
            superlative_quote=None,
            warnings=[],
            elements=[
                dict(
                    element_id=e,
                    state="unknown",
                    evidence_refs=[],
                    normalized_value=None,
                    credited_from=None,
                    reason_code=None,
                )
                for e in data["allowed_elements"]
            ],
        )
        payload = exchange(
            "elements",
            request["replicate_id"],
            system,
            json.loads(user),
            json.loads(schema),
            unknown,
        )
        Draft202012Validator(json.loads(schema)).validate(payload)
        payload = transport.restore_payload(
            deepcopy(payload), refs, policy=data.get("citation_restore_policy")
        )
        payload.update({k: request[k] for k in ("claim_id", "packet_sha256", "replicate_id")})
        return RawTagResponse(
            json.dumps(payload, ensure_ascii=False),
            TokenUsage(1, 1, 0, 0, 1, "succeeded", f"tb1-fresh-{uuid4()}"),
            True,
        )

    runs = tag_replicates(
        packet,
        context=context,
        track=TrackCandidate(context.claim, data["track"], data.get("safe_harbor_category")),
        original=graph,
        relation_tags=roles,
        rulepack=rules,
        settings=settings,
        cache=ImmutableResponseCache(InMemoryImmutableCacheClient()),
        usage_store=budget,
        invoke=invoke,
        tenant_id=graph.tenant_id,
        ensemble_id=str(uuid4()),
        consent_profile="tb1-sim",
        token_counter=lambda _: 1,
        now=lambda: 1,
        semantic_policy=POLICIES[variant]["semantic_admission"],
        pipeline_profile="finals-unattended-v2",
        allow_edge_whitespace=True,
    )
    if len(runs) != 3 or any(r.status == "model_failed" or r.guarded is None for r in runs):
        raise ValueError("TB1_THREE_COMPLETED_REPLICAS_REQUIRED")
    result = confirmation_result(
        runs,
        packet,
        rules,
        RuleContext(
            graph.tenant_id,
            graph.document_version_id,
            context.claim.claim_id,
            packet.packet_sha256,
            local_synthetic=True,
        ),
        claim=context.claim,
        graph=graph,
        analysis_policy=POLICIES[variant],
        prior_projection=item.get("provisional_grade") or {},
    )
    return dict(
        claim_id=context.claim.claim_id,
        quote=context.claim.quote,
        variant=variant,
        packet=packet.to_dict(),
        runs=[asdict(r) for r in runs],
        confirmation=result,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "score"])
    parser.add_argument("--stored", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    directory = args.output / "sim"
    directory.mkdir(exist_ok=True)
    requests, results, failures = {}, [], []
    provenance = (
        json.loads((directory / "response-provenance.json").read_text())["valid"]
        if args.mode == "score"
        else {}
    )
    for company, item, tagging, variant, graph in cases(args.stored, args.sources, args.output):
        key = sha256(f"{company}/{item['claim_id']}/{variant}".encode()).hexdigest()[:24]

        def exchange(role, replica, system, user, schema, unknown):
            if role == "elements":
                # The CLI's outer replica identity is authoritative. Requests
                # share one semantic payload; normalize only the redundant wire
                # replica label, then restore the actual ID on every response.
                assert user["replicate_id"] == replica
                user = user | dict(replicate_id=1)
            request_key = key + "-" + role
            request = dict(key=request_key, role=role, system=system, user=user, schema=schema)
            if args.mode == "prepare":
                if request_key in requests:
                    assert requests[request_key] == request
                requests[request_key] = request
                return unknown
            path = directory / "responses" / f"{request_key}-{replica}.json"
            receipt = provenance.get(f"{request_key}-{replica}")
            if (
                receipt is None
                or sha256(path.read_bytes()).hexdigest() != receipt["response_sha256"]
            ):
                raise ValueError("TB1_FRESH_RESPONSE_MISMATCH")
            # Prevent scoring responses against a subsequently changed packet/prompt.
            planned = json.loads((directory / "requests.json").read_text())
            assert request == next(r for r in planned if r["key"] == request_key)
            return json.loads(path.read_text())

        try:
            result = execute(item, tagging, variant, graph, directory, exchange)
            results.append(result | dict(company=company, key=key))
        except Exception as error:
            failures.append(
                dict(
                    company=company,
                    claim_id=item["claim_id"],
                    variant=variant,
                    error=type(error).__name__,
                    detail=str(error),
                )
            )
        print(args.mode, company, item["claim_id"], variant, len(failures), flush=True)
    write(directory / f"{args.mode}-failures.json", failures)
    if args.mode == "prepare":
        write(directory / "requests.json", list(requests.values()))
        write(
            directory / "selection.json",
            [
                {k: r[k] for k in ("company", "claim_id", "key", "quote", "variant")}
                for r in results
            ],
        )
        write(directory / "prepared.json", results)
    else:
        write(directory / "results.json", results)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
