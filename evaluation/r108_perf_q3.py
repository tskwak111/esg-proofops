"""Q3 archived preliminary audit and explicitly bounded classification-only trial."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import tempfile
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from proofops.adapters.local.claim_store import LocalClaimStore
from proofops.adapters.local.glyph_display_text import GlyphDisplayCatalog
from proofops.adapters.local.openrouter import OpenRouterProbe
from proofops.adapters.local.run_store import LocalSQLiteRunStore
from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
from proofops.application.registry import Registry
from proofops.application.tagging.preliminary import (
    SENTENCE_CONTEXT_SYSTEM_PROMPT,
    _sources,
    preliminary_table_request,
    sentence_context_ready,
    validate_preliminary_table_sources,
)
from proofops.application.tagging.table_sources import table_structural_sources
from proofops.application.uploads import UploadService
from proofops.domain.provenance import canonical_hash

ROOT = Path("/path/to/ESG_ProofOps")
LAB = ROOT / "outputs/agent-results/R108-redesign/lab"
OUT = LAB / "perf"
HASHES = {}


def read(path):
    raw = path.read_bytes()
    HASHES[str(path)] = hashlib.sha256(raw).hexdigest()
    return json.loads(raw)


def records(path):
    HASHES[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        return [
            json.loads(v)
            for (v,) in db.execute("select value from job_records where kind='artifact'")
        ]


def roots():
    for company in ("sk", "hyundai", "posco", "samsung", "naver", "kia"):
        yield company, LAB / f"sprint5/E2E3/states/{company}-attempt3"
    yield "F8", ROOT / ".local/r108-finals.INGDai/live"
    yield "RP-3", ROOT / ".local/r108-finals.1SnAjL/live"


def inventory():
    cases = []
    for company, root in roots():
        artifacts = records(root / "state.sqlite3")
        tagging = [a for a in artifacts if "preliminary_settings" in a and "claims" in a]
        for artifact in tagging:
            run_id = artifact["run_id"]
            for item in artifact["claims"]:
                rr = item.get("preliminary_records", [])
                agreement = item.get("preliminary_agreement") or {}
                conflicts = [
                    k
                    for section in ("fields", "dimensions")
                    for k, v in agreement.get(section, {}).items()
                    if v.get("state") != "agreed"
                ]
                if item.get("reason") != "PRELIMINARY_TAGS_UNRESOLVED" and not conflicts:
                    continue
                responses, packets = [], []
                for r in rr:
                    directory = root / "tagging-receipts" / run_id / "preliminary" / r["request_id"]
                    req = directory / "request.json"
                    res = directory / "response.json"
                    if req.is_file():
                        record = read(req)
                        packets.append(json.loads(record["request"]["user_json"]))
                    if res.is_file():
                        raw = read(res)
                        responses.append(
                            dict(
                                request_id=r["request_id"],
                                raw=raw["raw_response_json"],
                                output=json.loads(raw["raw_response_json"])
                                if raw["raw_response_json"]
                                else {},
                            )
                        )
                packet = packets[0] if packets else None
                outputs = [r["output"] for r in responses]
                tracks = [o.get("track") for o in outputs]
                axes = sorted({k for o in outputs for k in o.get("dimensions", {})})
                dims = {
                    a: [o.get("dimensions", {}).get(a, "<missing>") for o in outputs] for a in axes
                }
                types = []
                if len(responses) < 3:
                    types.append("replica_unavailable")
                if len(set(tracks)) > 1 or any(t is None for t in tracks):
                    types.append("track_mismatch_or_null")
                if any(any(v is None or v == "<missing>" for v in vals) for vals in dims.values()):
                    types.append("axis_null")
                data = packet["untrusted_document_data"] if packet else {}
                if not any(b["role"] == "parent_paragraph" for b in data.get("context_blocks", [])):
                    types.append("context_missing")
                if (
                    packet
                    and packet.get("table_policy", {}).get("focal_table_native_id")
                    and not any(s.get("table_role") == "column_header" for s in data["sources"])
                ):
                    types.append("table_header_missing")
                cases.append(
                    dict(
                        company=company,
                        root=str(root),
                        run_id=run_id,
                        claim_id=item["claim_id"],
                        reason=item.get("reason"),
                        conflicts=conflicts,
                        types=types,
                        three_raw_responses=responses,
                        missing_replica_response_count=3 - len(responses),
                        dimensions=dims,
                        tracks=tracks,
                        packet=packet,
                        records=rr,
                    )
                )
    return cases


def load_evidence(root, run_id, tenant, temp):
    target = temp / root.parent.name / root.name
    target.mkdir(parents=True, exist_ok=True)
    db = target / "state.sqlite3"
    # SQLite backup makes a consistent private copy, including WAL state.
    with (
        sqlite3.connect((root / "state.sqlite3").as_uri() + "?mode=ro", uri=True) as src,
        sqlite3.connect(db) as dest,
    ):
        src.backup(dest)
    shutil.copytree(root / "objects", target / "objects", dirs_exist_ok=True)
    store = LocalSQLiteRunStore(db)
    uploads = UploadService(db, target / "objects", Registry.sqlite(db))
    parser = OpenDataLoaderParser(root / "parser-prepared")
    return (
        LocalClaimStore(store, uploads, parser).load_evidence(tenant, run_id),
        uploads,
        store.snapshot(tenant, run_id),
    )


def values(result):
    return dict(
        track=asdict(result.track) if result.track else None,
        dimensions={k: asdict(v) if v else None for k, v in result.context.dimensions.items()},
        safe_harbor_category=result.safe_harbor_category,
    )


def consensus(results, provider_ids):
    return (
        len(results) == 3
        and len(set(provider_ids)) == 3
        and len({canonical_hash(v) for v in results}) == 1
    )


def matcher():
    spec = importlib.util.spec_from_file_location("q3_matcher", LAB / "sprint4/SC/score_r108.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def score_admission(cases):
    """No calls: apply final complete-context eligibility to saved diagnostic trials."""
    from types import SimpleNamespace

    from proofops.domain.values import _source_ref_from_dict

    measured = read(OUT / "Q3-measurements.json")
    discoveries = {}
    for company, root in roots():
        for artifact in records(root / "state.sqlite3"):
            if "discovery" in artifact:
                for claim in artifact["discovery"]["claims"]:
                    discoveries[claim["claim_id"]] = claim
    rows = []
    for row in measured["measurements"]:
        item = dict(row)
        eligible = False
        if row.get("trials"):
            request = read(OUT / f"Q3-{row['trials'][0]['request_id']}-request.json")
            packet = json.loads(request["user_json"])
            original = discoveries[row["claim_id"]]
            claim = SimpleNamespace(
                source_refs=tuple(_source_ref_from_dict(r) for r in original["source_refs"])
            )
            eligible = sentence_context_ready(claim, packet)
            data = packet["untrusted_document_data"]
            item["context_contains_new_source_text"] = any(
                b["role"] == "parent_paragraph"
                and not any(b["text"] == source["text"] for source in data["sources"])
                for b in data.get("context_blocks", [])
            )
        item.update(
            context_eligible=eligible,
            raw_model_enters=bool(row.get("enters")),
            enters=bool(row.get("enters") and eligible),
        )
        rows.append(item)
    entries = [r for r in rows if r["enters"]]
    result = dict(
        method=(
            "Saved exact-wire diagnostic model outputs plus final deterministic "
            "complete-context admission; no new model calls and no old response "
            "is relabeled as a new input."
        ),
        cases=len(cases),
        measured=measured["measured"],
        context_eligible=sum(r["context_eligible"] for r in rows),
        raw_agreed=measured["agreed"],
        raw_entries=measured["entries"],
        raw_wrong_entries=measured["wrong_entries"],
        entries=len(entries),
        track_evaluable=sum(r.get("track_match") is not None for r in entries),
        track_matched=sum(r.get("track_match") is True for r in entries),
        wrong_entries=sum(r.get("track_match") is False for r in entries),
        unscored_entries=sum(r.get("track_match") is None for r in entries),
        agreement_rate_all_cases=len(entries) / len(cases),
        context_new_text_cases=sum(r.get("context_contains_new_source_text", False) for r in rows),
        cost_usd=measured["cost_usd"],
        source_hashes_unchanged=measured["source_hashes_unchanged"],
        measurements=rows,
    )
    (OUT / "Q3-admission.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "measurements"}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paid", action="store_true")
    parser.add_argument("--score-only", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    run_lock = (OUT / "Q3-run.lock").open("a")
    fcntl.flock(run_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    cases = inventory()
    if args.score_only:
        score_admission(cases)
        return
    summary = dict(
        cases=len(cases),
        blocked=sum(c["reason"] == "PRELIMINARY_TAGS_UNRESOLVED" for c in cases),
        types=dict(Counter(t for c in cases for t in c["types"])),
        companies=dict(Counter(c["company"] for c in cases)),
        raw_response_count=sum(len(c["three_raw_responses"]) for c in cases),
        complete_three_response_cases=sum(len(c["three_raw_responses"]) == 3 for c in cases),
        missing_response_count=sum(c["missing_replica_response_count"] for c in cases),
    )
    (OUT / "Q3-audit.json").write_text(
        json.dumps(
            dict(summary=summary, cases=cases, input_hashes=HASHES), ensure_ascii=False, indent=2
        )
        + "\n"
    )
    print(json.dumps(summary), flush=True)
    if not args.paid:
        return
    from scripts import finals_demo

    finals_demo.TASK = "perf-Q3"

    class Q3Budget(finals_demo.FinalsBudget):
        def reserve(self, bound):
            if not bound.is_finite() or bound <= 0:
                raise ValueError("Q3_INVALID_RESERVATION")
            with self.transaction() as (data, entry):
                entry["limit_usd"] = "0.30"
                pending = Decimal(entry["reserved_usd"])
                if Decimal(entry["delta_usd"]) + pending + bound > Decimal("0.30"):
                    raise ValueError("Q3_BUDGET_EXHAUSTED")
                other = sum(
                    (
                        Decimal(e.get("reserved_usd", "0"))
                        for e in data["executions"]
                        if e is not entry
                    ),
                    Decimal(0),
                )
                if Decimal(
                    data["cumulative_usd"]
                ) + self.unsettled() + other + pending + bound > Decimal(data["limit_usd"]):
                    raise ValueError("Q3_CUMULATIVE_BUDGET_EXHAUSTED")
                entry["reserved_usd"] = str(pending + bound)
                entry["status"] = "running"

    spend = LAB / "sprint3/E2E/r108-spend.json"
    ledger = ROOT / ".local/openrouter/budget.sqlite3"
    budget = Q3Budget(
        spend,
        {p: ROOT / f".local/{p}/budget.sqlite3" for p in ("openrouter", "upstage")},
        OUT / "Q3-paid-calls.jsonl",
    )
    key = next(
        line.split("=", 1)[1].strip().strip('"').strip("'")
        for line in (ROOT / ".env.openrouter.local").read_text().splitlines()
        if line.startswith("OPENROUTER_API_KEY=")
    )
    probe = OpenRouterProbe(key, ledger, wire_policy_version=2)
    original = OpenRouterProbe.complete
    call = budget.guarded(original, "openrouter", lambda a, k: Decimal("0.02"))
    os.environ["PROOFOPS_RECEIPT_READ_PROFILE"] = "receipt-env-drift-v1"
    m = matcher()
    gold, _ = m.normalize_gold(read(LAB / "gold-v1/draft.json"))
    reference = {c["claim_id"]: c["track"] for c in read(OUT / "Q3-ai-reference.json")["claims"]}
    measurements, load_errors = [], []
    with tempfile.TemporaryDirectory(prefix="q3-replay-") as directory:
        temp = Path(directory)
        for company, root in roots():
            subset = [
                c
                for c in cases
                if c["company"] == company
                and c["reason"] == "PRELIMINARY_TAGS_UNRESOLVED"
                and c["packet"]
            ]
            if not subset:
                continue
            run_id = subset[0]["run_id"]
            tenant = subset[0]["packet"]["tenant_id"]
            try:
                (_, discovery, graph), uploads, snapshot = load_evidence(root, run_id, tenant, temp)
            except Exception as exc:
                load_errors.append(
                    dict(
                        company=company,
                        error=type(exc).__name__,
                        code=str(exc) if len(str(exc)) < 100 else "REPLAY_FAILED",
                    )
                )
                print("load_failed", company, type(exc).__name__, flush=True)
                continue
            claims = {c.claim_id: c for c in discovery.claims}
            source = uploads.read_original(tenant, graph.document_version_id)
            catalog = GlyphDisplayCatalog(graph, source)
            # Match all saved claims jointly, retaining the official one-to-one .82 policy.
            normalized = m.normalize_run(
                dict(
                    claims=[
                        dict(
                            company_id=company,
                            page_num=c.source_refs[0].page_num,
                            quote=c.quote,
                            claim_id=c.claim_id,
                        )
                        for c in discovery.claims
                    ]
                )
            )["claims"]
            cg = [g for g in gold if g["company_id"] == company]
            alignment, _ = m.align(cg, normalized)
            expected = {
                normalized[ri]["claim_id"]: {
                    "G": "goal",
                    "P": "performance",
                    "M": "management",
                }.get(cg[gi]["_track"])
                for gi, (ri, _) in alignment.items()
            }
            for case in subset:
                with budget.transaction() as (_, entry):
                    remaining = (
                        Decimal("0.30")
                        - Decimal(entry["delta_usd"])
                        - Decimal(entry["reserved_usd"])
                    )
                if remaining < Decimal("0.06"):
                    print("budget cannot guarantee three replicas", flush=True)
                    break
                claim = claims[case["claim_id"]]
                row = dict(
                    company=company,
                    claim_id=claim.claim_id,
                    expected_track=expected.get(claim.claim_id, reference.get(claim.claim_id)),
                    reference_kind="R108_GOLD"
                    if claim.claim_id in expected
                    else "Q3_AI_PROVISIONAL_SUPPLEMENT",
                    before_tracks=case["tracks"],
                )
                try:
                    packet = preliminary_table_request(
                        claim, graph, tenant_id=tenant, sentence_context=True
                    )
                    refs = _sources(claim, graph, tenant)
                    table = table_structural_sources(graph, refs, tenant_id=tenant)
                    # Use the real transport's context bounding and wire validation.
                    from proofops.application.authorization import AuthContext
                    from proofops.application.ports.models import ModelBinding
                    from proofops.application.preflight import check_local_upstage_tagger
                    from proofops.application.tagging.preliminary import SENTENCE_CONTEXT_PROFILE
                    from proofops.application.tagging.service import TaggingSettings
                    from proofops_agent.upstage_preliminary import UpstagePreliminaryTransport

                    settings = TaggingSettings(
                        ModelBinding(str(uuid4()), "tagger", False),
                        probe.model,
                        SENTENCE_CONTEXT_PROFILE,
                        "provider-managed-unverified",
                        SENTENCE_CONTEXT_SYSTEM_PROMPT,
                        snapshot["preliminary_settings"]["schema_json"],
                        max_tokens=1024,
                        wire_policy_version=2,
                    )
                    # The authorized task is a standalone paid evaluation; use recorded
                    # source rights/consent, not publication or historical runtime grants.
                    now = datetime.now(UTC)
                    expires = (now + timedelta(days=1)).isoformat()
                    # This task explicitly authorizes this new bounded local test.
                    # Fresh grants exist only in the evaluation, never in old runs.
                    consent = snapshot["consent"] | dict(
                        approved_at=now.isoformat(), expires_at=expires
                    )
                    grant = snapshot["preliminary_runtime"] | dict(
                        runtime_binding_id=settings.binding.binding_id,
                        tagging_settings_sha256=canonical_hash(asdict(settings)),
                        approved_at=now.isoformat(),
                        expires_at=expires,
                    )

                    def authorize(selected, request):
                        return check_local_upstage_tagger(
                            binding=grant,
                            consent=consent,
                            auth=AuthContext(
                                "authorized-Q3-evaluation", tenant, "viewer", frozenset(), run_id
                            ),
                            checked_at=datetime.now(UTC).isoformat(),
                            source_sha256=graph.source_sha256,
                            document_rights=snapshot["document"]["metadata"]["rights_profile_id"],
                            settings=selected,
                        )

                    authorization = authorize(settings, None)
                    if not authorization.ready:
                        raise ValueError("Q3_AUTHORIZATION_BLOCKED")
                    (OUT / f"Q3-{claim.claim_id}-authorization.json").write_text(
                        json.dumps(
                            dict(
                                task_path=str(
                                    ROOT / "outputs/agent-results/R108-redesign/tasks/perf-Q3.md"
                                ),
                                task_sha256=hashlib.sha256(
                                    (
                                        ROOT
                                        / "outputs/agent-results/R108-redesign/tasks/perf-Q3.md"
                                    ).read_bytes()
                                ).hexdigest(),
                                grant=grant,
                                consent=consent,
                                checks=authorization.to_dict(),
                            ),
                            indent=2,
                        )
                        + "\n"
                    )
                    transport = UpstagePreliminaryTransport(
                        probe,
                        OUT / "Q3-trial-receipts",
                        settings=settings,
                        tenant_id=tenant,
                        authorize=authorize,
                        display_catalog=catalog,
                    )
                    packet = transport.bound_context(packet)
                    packet["display_text"] = catalog.preliminary_pins(
                        packet, (*refs, *(i.ref for i in table.verified))
                    )
                    if not sentence_context_ready(claim, packet):
                        row.update(
                            agreed=False,
                            enters=False,
                            code="VERIFIED_COMPLETE_CONTEXT_REQUIRED",
                            complete_contexts=len(
                                packet["untrusted_document_data"]["context_blocks"]
                            ),
                        )
                        measurements.append(row)
                        continue
                    print(
                        "prepared",
                        company,
                        claim.claim_id[:8],
                        "verified_contexts",
                        len(packet["untrusted_document_data"]["context_blocks"]),
                        flush=True,
                    )
                    results, ids, trials = [], [], []
                    for replica in (1, 2, 3):
                        request_id = str(uuid4())
                        request = dict(
                            tenant_id=tenant,
                            claim_id=claim.claim_id,
                            packet_sha256=canonical_hash(packet),
                            replicate_id=replica,
                            request_id=request_id,
                            request_signature=canonical_hash([packet, replica, request_id]),
                            binding=asdict(settings.binding),
                            model_id=settings.model_id,
                            model_profile=settings.model_profile,
                            region=settings.region,
                            system_prompt=settings.rendered_system,
                            temperature=0,
                            max_tokens=settings.max_tokens,
                            user_json=json.dumps(packet, ensure_ascii=False),
                        )
                        system, wire, _, _, _ = transport._wire_request(request)
                        (OUT / f"Q3-{request_id}-request.json").write_text(
                            json.dumps(request, ensure_ascii=False, indent=2) + "\n"
                        )
                        result = call(
                            probe,
                            system,
                            wire,
                            request_id=request_id,
                            max_tokens=1024,
                            json_mode=True,
                            schema_json=settings.schema_json,
                        )
                        (OUT / f"Q3-{request_id}-response.json").write_text(
                            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
                        )
                        trial = dict(
                            replicate_id=replica,
                            request_id=request_id,
                            output=json.loads(result["content"]),
                            provider_request_id=result["provider_request_id"],
                        )
                        try:
                            restored = catalog.restore_preliminary(trial["output"], packet)
                            validated = validate_preliminary_table_sources(
                                claim, graph, restored, tenant_id=tenant
                            )
                            v = values(validated)
                            results.append(v)
                            ids.append(result["provider_request_id"])
                            trial["validated_values"] = v
                        except Exception as exc:
                            trial["validation_error"] = type(exc).__name__
                        trials.append(trial)
                    agreed = consensus(results, ids)
                    track = results[0]["track"]["track"] if agreed and results[0]["track"] else None
                    row.update(
                        trials=trials,
                        agreed=agreed,
                        enters=bool(agreed and track),
                        track=track,
                        track_match=(track == row["expected_track"])
                        if track and row["expected_track"] is not None
                        else None,
                        complete_contexts=len(packet["untrusted_document_data"]["context_blocks"]),
                        packet_sha256=canonical_hash(packet),
                    )
                except Exception as exc:
                    row.update(
                        error=type(exc).__name__,
                        code=str(exc) if len(str(exc)) < 100 else "TRIAL_FAILED",
                        agreed=False,
                        enters=False,
                    )
                measurements.append(row)
                print(
                    company,
                    claim.claim_id[:8],
                    row.get("agreed"),
                    row.get("enters"),
                    row.get("track_match"),
                    row.get("code"),
                    flush=True,
                )
                (OUT / "Q3-measurements.json").write_text(
                    json.dumps(
                        dict(measurements=measurements, load_errors=load_errors),
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n"
                )
    with budget.transaction() as (data, entry):
        entry["status"] = "complete"
        cost = entry["delta_usd"]
    measured = [r for r in measurements if "trials" in r]
    result = dict(
        measured=len(measured),
        agreed=sum(r["agreed"] for r in measured),
        entries=sum(r["enters"] for r in measured),
        track_matched=sum(r.get("track_match") is True for r in measured),
        track_evaluable=sum(r.get("track_match") is not None for r in measured),
        wrong_entries=sum(r.get("track_match") is False and r["enters"] for r in measured),
        cost_usd=cost,
        load_errors=load_errors,
        measurements=measurements,
        source_hashes_unchanged=all(
            hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in HASHES.items()
        ),
    )
    (OUT / "Q3-measurements.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps({k: v for k, v in result.items() if k not in ("measurements",)}), flush=True)


if __name__ == "__main__":
    main()
