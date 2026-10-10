"""Retag QA1's exact saved evidence/track inputs; no parsing or preliminary calls."""

import json
import os
import time
from collections import Counter
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

from evaluation.qi1_live import OUT, ROOT, budget, install_guards


def prepare(company):
    from proofops.adapters.local.claim_store import LocalClaimStore
    from proofops.adapters.local.run_store import LocalSQLiteRunStore
    from proofops.adapters.local.tag_store import tag_pins
    from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
    from proofops.application.ports.jobs import JobMessage
    from proofops.application.registry import Registry
    from proofops.application.uploads import UploadService

    state = ROOT / f"outputs/agent-results/R108-redesign/lab/parse/MP1/states/{company}"
    pilot = json.loads((state / "pilot.json").read_text())
    database = state / "state.sqlite3"
    before = sha256(database.read_bytes()).hexdigest()
    registry = Registry.sqlite(database)
    uploads = UploadService(database, state / "objects", registry)
    store = LocalSQLiteRunStore(database)
    parser = OpenDataLoaderParser(state / "parser-prepared")
    claims = LocalClaimStore(store, uploads, parser)
    extract, discovery, graph = claims.load_evidence(pilot["tenant_id"], pilot["run_id"])
    snapshot = store.snapshot(pilot["tenant_id"], pilot["run_id"])
    run = store.jobs.get_run(pilot["tenant_id"], pilot["run_id"])
    raw_tags = store.jobs.read_checkpoint(JobMessage(**run["tag_job"]))
    assert sha256(raw_tags).hexdigest() == run["tag_snapshot_sha256"]
    tagged = json.loads(raw_tags)
    assert all(
        tagged.get(key) == value
        for key, value in tag_pins(snapshot, extract, run["claim_snapshot_sha256"]).items()
    )
    source = uploads.read_original(pilot["tenant_id"], graph.document_version_id)
    uploads.close()
    registry.close()
    assert before == sha256(database.read_bytes()).hexdigest(), "original state changed"
    return (
        snapshot,
        graph,
        source,
        {c.claim_id: c for c in discovery.claims},
        {r["claim_id"]: r for r in tagged["claims"]},
        before,
    )


def restored_inputs(record, claim):
    from proofops.application.evidence.binding import ClaimContext, local_relation_tags
    from proofops.application.tagging.tracks import TrackCandidate
    from proofops.domain.provenance import canonical_hash
    from proofops.domain.values import SourceRef

    values = [
        r["values"] for r in record["preliminary_records"] if r["status"] == "validated_candidate"
    ]
    headers = [
        (v["track"]["track"] if v["track"] else None, v["safe_harbor_category"]) for v in values
    ]
    header, count = Counter(headers).most_common(1)[0]
    assert count >= 2 and header[0] is not None
    winners = [v for v, h in zip(values, headers, strict=True) if h == header]
    dimensions = {}
    for key in set().union(*(v["dimensions"] for v in winners)):
        choices = [v["dimensions"].get(key) for v in winners]
        selected = choices[0] if all(v == choices[0] for v in choices) else None
        dimensions[key] = SourceRef(**selected) if selected else None
    context = ClaimContext(claim, dimensions)
    relation = {}
    external = [
        r["values"]
        for r in record.get("relation_records", [])
        if r["status"] == "validated_candidate"
    ]
    if len(external) == 3 and len({canonical_hash(r) for r in external}) == 1:
        relation = {
            sid: {k: SourceRef(**v) if v else None for k, v in dims.items()}
            for sid, dims in external[0].items()
        }
    relation.update(local_relation_tags(context))
    return TrackCandidate(claim, *header), context, relation


def main(prepared=None):
    from proofops.adapters.aws.usage import LocalSQLiteUsageStore
    from proofops.adapters.cache.aws import ImmutableResponseCache, InMemoryImmutableCacheClient
    from proofops.adapters.local.glyph_display_text import GlyphDisplayCatalog
    from proofops.adapters.local.openai import OpenAIProbe, validate_capacity_policy
    from proofops.adapters.local.tag_store import tagging_settings
    from proofops.application.analysis_profile import V2_POLICY
    from proofops.application.authorization import AuthContext
    from proofops.application.budget import BudgetLimits, RoleLimit
    from proofops.application.evidence.retrieval import freeze_packet, unattended_packet
    from proofops.application.ports.models import ModelBinding
    from proofops.application.preflight import check_local_upstage_tagger
    from proofops.application.registry import Registry, artifact_sha256
    from proofops.application.tagging.quality import ELEMENT_DEFINITIONS, hold_projection
    from proofops.application.tagging.service import tag_replicates
    from proofops.application.tagging.unattended import provisional_result
    from proofops.domain.provenance import canonical_hash
    from proofops.domain.rulepacks import RulePackSnapshot
    from proofops.domain.rules.engine import RuleContext
    from proofops_agent.upstage_tagging import UpstageTaggingTransport
    from proofops_worker.live_tagging import LiveTaggingRuntime

    os.environ["PROOFOPS_RECEIPT_READ_PROFILE"] = "receipt-env-drift-v1"
    selected = json.loads(
        (ROOT / "outputs/agent-results/R108-redesign/lab/qa/QA1/sample-review.json").read_text()
    )["samples"]
    assert len(selected) == 20
    if prepared is None:
        prepared = {company: prepare(company) for company in ("samsung", "kepco")}
    fence = budget()
    with fence.transaction() as (_, entry):
        if entry.get("samples_started"):
            import sqlite3

            assert not list(OUT.glob("*-retag.json"))
            assert not list((OUT / "sample-receipts").rglob("request.json"))
            with sqlite3.connect(OUT / "sample-usage.sqlite3") as db:
                assert db.execute("select count(*) from usage_attempts").fetchone()[0] == 0
            entry.setdefault("sample_startup_failures", []).append(
                dict(phase="runtime_registry_metadata", paid_calls=0)
            )
        entry["samples_started"] = True
        before = entry["delta_usd"]
    install_guards(fence)
    key = next(
        line.split("=", 1)[1].strip().strip('"').strip("'")
        for line in (ROOT / ".env.openai.local").read_text().splitlines()
        if line.startswith("OPENAI_API_KEY=")
    )
    probe = OpenAIProbe(key, ROOT / ".local/openai/budget.sqlite3")
    usage = LocalSQLiteUsageStore(OUT / "sample-usage.sqlite3")
    results = []
    for company in ("samsung", "kepco"):
        snapshot, graph, source, claims, records, original_hash = prepared[company]
        old = tagging_settings(snapshot)
        settings = replace(
            old,
            binding=ModelBinding(str(uuid4()), "tagger", False),
            system_prompt=old.system_prompt + "\n" + ELEMENT_DEFINITIONS,
        )
        now = datetime.now(UTC)
        runtime = snapshot["tagging_runtime"] | dict(
            version="qi1-v1",
            runtime_binding_id=settings.binding.binding_id,
            tagging_settings_sha256=canonical_hash(asdict(settings)),
            approved_at=now.isoformat(),
            approved_by="QI1 authorized user task",
            approval_origin="quality-QI1 task",
            expires_at=(now + timedelta(hours=24)).isoformat(),
        )
        registry = Registry.empty().with_option(
            graph.tenant_id,
            "runtime",
            settings.binding.binding_id,
            "QI1 new element prompt",
            status="approved",
            version="qi1-v1",
            sha256=artifact_sha256(runtime),
            artifact=runtime,
            approved_by=runtime["approved_by"],
            approved_at=runtime["approved_at"],
        )
        auth = AuthContext(
            "QI1 authorized local operator", graph.tenant_id, "admin", frozenset(), str(uuid4())
        )

        def authorize(config, request):
            bound = registry.resolve_profile(auth, "runtime", config.binding.binding_id)
            return check_local_upstage_tagger(
                binding=bound,
                consent=snapshot["consent"],
                auth=auth,
                checked_at=datetime.now(UTC).isoformat(),
                source_sha256=graph.source_sha256,
                document_rights=snapshot["document"]["metadata"]["rights_profile_id"],
                settings=config,
            )

        transport = UpstageTaggingTransport(
            probe,
            OUT / "sample-receipts" / company,
            settings=settings,
            tenant_id=graph.tenant_id,
            authorize=authorize,
            display_catalog=GlyphDisplayCatalog(graph, source),
        )
        usage.create_budget(
            graph.tenant_id,
            snapshot["run_id"],
            graph.document_version_id,
            BudgetLimits(4_000_000, 400_000, (RoleLimit("tagger", 60, 32768, 4096, 36864),)),
        )
        pack = RulePackSnapshot(**snapshot["rulepack"])
        for sample in (s for s in selected if s["company"] == company):
            claim = claims[sample["claim_id"]]
            record = records[claim.claim_id]
            assert claim.quote == sample["claim"] and claim.source_quality == "verified"
            track, context, relations = restored_inputs(record, claim)
            raw = record["frozen_packet"].copy()
            raw.pop("packet_sha256")
            packet = unattended_packet(freeze_packet(raw), profile="finals-unattended-v2")
            old_evidence_hash = canonical_hash(record["frozen_packet"]["evidence_candidates"])
            assert canonical_hash(packet.to_dict()["evidence_candidates"]) == old_evidence_hash
            started = time.monotonic()
            runs = tag_replicates(
                packet,
                context=context,
                track=track,
                original=graph,
                relation_tags=relations,
                rulepack=pack,
                settings=settings,
                cache=ImmutableResponseCache(InMemoryImmutableCacheClient()),
                usage_store=usage,
                invoke=transport.invoke,
                tenant_id=graph.tenant_id,
                ensemble_id=str(uuid4()),
                consent_profile=snapshot["consent"]["consent_profile_id"],
                token_counter=LiveTaggingRuntime.token_counter,
                count_input_tokens=lambda request: transport.count_input_tokens(
                    request,
                    counter=lambda *a: validate_capacity_policy(
                        snapshot["input_reservation_policy"], model_id=settings.model_id
                    ),
                ),
                now=lambda: int(time.time()),
                pipeline_profile="finals-unattended-v2",
            )
            rule_context = RuleContext(
                graph.tenant_id,
                graph.document_version_id,
                claim.claim_id,
                packet.packet_sha256,
                mode=snapshot["mode"],
            )
            result = provisional_result(runs, packet, pack, rule_context, range_profile=True)
            result = hold_projection(
                dict(
                    provisional_grade=result,
                    source_status=dict(status="verified"),
                    frozen_packet=packet.to_dict(),
                )
            )
            item = dict(
                sample_id=sample["sample_id"],
                company=company,
                claim_id=claim.claim_id,
                quote=claim.quote,
                track=track.track,
                seconds=time.monotonic() - started,
                old_grade=record["provisional_grade"],
                provisional_grade=result,
                frozen_packet=packet.to_dict(),
                tag_runs=[asdict(r) for r in runs],
                same_evidence_candidates_sha256=old_evidence_hash,
                original_database_sha256=original_hash,
                prompt_sha256=settings.prompt_sha256,
                analysis_profile_policy_sha256=canonical_hash(V2_POLICY),
                runtime=runtime,
            )
            results.append(item)
            (OUT / (sample["sample_id"] + "-retag.json")).write_text(
                json.dumps(item, ensure_ascii=False, indent=2) + "\n"
            )
            print(
                sample["sample_id"],
                result.get("evidence_grade"),
                [r.status for r in runs],
                flush=True,
            )
    with fence.transaction() as (_, entry):
        from decimal import Decimal

        spend = str(Decimal(entry["delta_usd"]) - Decimal(before))
    (OUT / "samples-retag.json").write_text(
        json.dumps(dict(samples=results, cost_usd=spend), ensure_ascii=False, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
