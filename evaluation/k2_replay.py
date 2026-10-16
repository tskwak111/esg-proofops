"""I1 saved-response K2 evaluation; network denied, no production writes.

Rehydrate the byte-hashed historical graph from its stored attestations. This is
an evaluation input, NOT a replacement for the runtime's fresh OCR reader gates.
Scalar citations are additionally checked against original native bbox text.
"""

import argparse
import io
import json
import socket
import tempfile
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from time import monotonic

import pdfplumber
from proofops.adapters.aws.usage import LocalSQLiteUsageStore
from proofops.adapters.cache.aws import ImmutableResponseCache, InMemoryImmutableCacheClient
from proofops.adapters.local.glyph_display_text import GlyphDisplayCatalog
from proofops.adapters.local.tag_store import tagging_settings
from proofops.application.analysis_profile import FINALS_K2_POLICY
from proofops.application.budget import BudgetLimits, RoleLimit
from proofops.application.evidence.binding import ClaimContext
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.evidence.span_citations import span_verified_graph, verify_source_ref
from proofops.application.tagging.k2_recovery import POLICY
from proofops.application.tagging.quality import hold_projection
from proofops.application.tagging.service import RawTagResponse, tag_replicates
from proofops.application.tagging.tracks import TrackCandidate
from proofops.application.tagging.unattended import provisional_result
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.rules.engine import RuleContext
from proofops.domain.values import SourceRef
from proofops_worker.live_tagging import LiveTaggingRuntime

from evaluation.pa9_source_gate import fixture
from evaluation.pt1_replay import decode_runs


def read(path):
    return json.loads(path.read_bytes())


def historical_graph(graph, parse, extract):
    """Restore exactly the recorded graph identity; never newly attest a block."""
    for receipt in (
        parse["native_paragraph_attestation"],
        parse["evidence_source_attestation"],
        extract["claim_source_attestation"],
    ):
        assert receipt["artifact_sha256"] == canonical_hash(
            {k: v for k, v in receipt.items() if k != "artifact_sha256"}
        )
        assert (
            receipt["tenant_id"],
            receipt["document_version_id"],
            receipt["parse_manifest_id"],
            receipt["source_sha256"],
        ) == (
            graph.tenant_id,
            graph.document_version_id,
            graph.parse_manifest_id,
            graph.source_sha256,
        )
    native = parse["native_paragraph_attestation"]
    assert native["input_graph_sha256"] == canonical_hash(asdict(graph))
    verified = {r["source_id"] for r in native["records"] if r["status"] == "verified"}
    graph = replace(
        graph,
        blocks=tuple(
            replace(b, quality="verified") if b.source_id in verified else b for b in graph.blocks
        ),
    )
    ev = parse["evidence_source_attestation"]
    members = {sid for t in ev["tables"] if t["status"] == "verified" for sid in t["member_ids"]}
    tables = {t["table_id"] for t in ev["tables"] if t["status"] == "verified"}
    graph = replace(
        graph,
        blocks=tuple(
            replace(b, quality="verified") if b.source_id in members else b for b in graph.blocks
        ),
        issues=tuple(
            replace(
                i, state="resolved", reason="EV1 native/rendered grid checked; binding undetermined"
            )
            if i.kind == "table_vision_not_run" and i.source_ids and set(i.source_ids) <= tables
            else i
            for i in graph.issues
        ),
    )
    refs = tuple(
        replace(SourceRef(**r["ref"]), verification_state="verified")
        for r in ev["records"]
        if r["kind"] == "paragraph" and r["status"] == "verified"
    )
    # The OCR wrapper adds collection provenance AFTER the base EV1 replay.
    # Preserve the base receipt digest used in the original graph identity.
    base_ev = {
        k: v
        for k, v in ev.items()
        if k not in {"artifact_sha256", "run_id", "page_collections", "rendered_reader_profile"}
    }
    graph = span_verified_graph(graph, refs, canonical_hash(base_ev))
    receipt = extract["claim_source_attestation"]
    assert receipt["graph_sha256"] == canonical_hash(asdict(graph))
    newly = tuple(
        replace(SourceRef(**r["ref"]), verification_state="verified")
        for r in receipt["records"]
        if r["status"] == "verified"
    )
    cells = tuple(
        replace(SourceRef(**c["source_ref"]), verification_state="verified")
        for p in receipt["pb1_cell_proofs"]
        if p["status"] == "verified"
        for c in p["cell_proofs"]
        if not c.get("recovered_selection")
    )
    seen = {(r.source_id, r.char_start, r.char_end) for r in refs}
    return span_verified_graph(
        graph,
        refs
        + tuple(r for r in (*newly, *cells) if (r.source_id, r.char_start, r.char_end) not in seen),
        receipt["artifact_sha256"],
    )


def projection(result):
    return {
        k: result.get(k)
        for k in ("evidence_grade", "display_type", "hold_reasons", "unresolved_elements")
    } | dict(states={e["element_id"]: e["state"] for e in result.get("elements", [])})


def main(*, integration_policy=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    start = monotonic()
    selected_policy = integration_policy or FINALS_K2_POLICY

    def deny(*a, **kw):
        raise AssertionError("K2_OFFLINE_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    lab = args.root / "outputs/agent-results/R108-redesign/lab"
    inputs = lab / "perf/I1/stage-B-compact"
    hashes = {str(p): sha256(p.read_bytes()).hexdigest() for p in inputs.rglob("*") if p.is_file()}
    review_path = lab / "review/R1/cases.json"
    hashes[str(review_path)] = sha256(review_path.read_bytes()).hexdigest()
    review = {c["case_id"]: c for c in read(review_path)["cases"]}
    cases, failures, false_verified, preserved = [], [], [], []
    with tempfile.TemporaryDirectory(prefix="proofops-k2-replay-") as directory:
        for name in ("naver", "kia"):
            state = inputs / name
            graph, source, discovery, snapshot, parse = fixture(state)
            extract, checkpoint = (
                read(state / "extract-checkpoint.json"),
                read(state / "tag-checkpoint.json"),
            )
            graph = historical_graph(graph, parse, extract)
            assert all(
                c["frozen_packet"]["graph_sha256"] == canonical_hash(asdict(graph))
                for c in checkpoint["claims"]
                if c.get("frozen_packet")
            )
            claims = {c.claim_id: c for c in discovery.claims}
            pack = RulePackSnapshot(**snapshot["rulepack"])
            responses = [read(p) for p in (state / "live-luna.sqlite3.responses").glob("*.json")]
            catalog = GlyphDisplayCatalog(graph, source)
            with pdfplumber.open(io.BytesIO(source)) as pdf:
                for index, item in enumerate(checkpoint["claims"]):
                    cid = name.upper() + f"-{index:02}"
                    claim = claims[item["claim_id"]]
                    assert review[cid]["claim_id"] == claim.claim_id
                    before = projection(item["provisional_grade"])
                    if not item.get("frozen_packet"):
                        # Exercise the actual runtime's validation callback on each
                        # recorded provider response. Do not invent missing votes.
                        runtime = object.__new__(LiveTaggingRuntime)
                        runtime.snapshot, runtime.graph = snapshot, graph
                        runtime.preliminary_settings = tagging_settings(snapshot, preliminary=True)
                        runtime.preliminary_records, runtime.display_catalog = {}, catalog
                        runtime.auth = type("Auth", (), dict(tenant_id=graph.tenant_id))()
                        runtime.attribution_policy = snapshot["relation_attribution_policy"]
                        runtime.preliminary_transport = type(
                            "Transport", (), dict(bound_context=lambda self, p: p)
                        )()
                        validated, diagnostics = [], []

                        def replay_preliminary(
                            prefix, current, packet, settings, transport, records, validate, **kw
                        ):
                            for record in item["preliminary_records"]:
                                for saved in responses:
                                    if saved["request_id"] != record["request_id"]:
                                        continue
                                    raw = json.loads(
                                        saved["provider_response"]["choices"][0]["message"][
                                            "content"
                                        ]
                                    )
                                    try:
                                        result, values = validate(raw)
                                        validated.append(result)
                                        diagnostics.append(
                                            dict(values=values, replicate_id=record["replicate_id"])
                                        )
                                    except ValueError as error:
                                        diagnostics.append(dict(error=str(error)))
                            records[current.claim_id] = diagnostics
                            return None  # Fewer than three recorded votes: no new consensus.

                        runtime._source_replicas = replay_preliminary
                        try:
                            runtime.preliminary(claim, graph)
                            baseline_ok = bool(validated)
                        except ValueError:
                            baseline_ok = False
                        validated.clear()
                        diagnostics.clear()

                        runtime.snapshot = snapshot | dict(analysis_profile_policy=selected_policy)
                        runtime.preliminary(claim, graph)
                        assert not baseline_ok and validated, cid
                        after = projection(hold_projection(item, profile="k2-v1"))
                        cases.append(
                            dict(
                                case_id=cid,
                                before=before,
                                after=after,
                                preliminary_validation_before=False,
                                preliminary_validation_after=True,
                                recorded_header_votes=len(validated),
                                dimension_restore_errors=[
                                    d["values"].get("dimension_restore_errors", {})
                                    for d in diagnostics
                                ],
                                status="saved-header-validation-only;missing-replicas-not-run",
                            )
                        )
                        continue
                    data = item["frozen_packet"]
                    runs = decode_runs(item["tag_runs"])
                    # Restore the trusted original claim view, without granting a
                    # source status that was not present in its stored packet.
                    checked_refs = tuple(
                        verify_source_ref(r, graph, tenant_id=graph.tenant_id)
                        for r in claim.source_refs
                    )
                    quality = (
                        "verified"
                        if all(r.verification_state == "verified" for r in checked_refs)
                        and item["source_status"]["status"] == "verified"
                        else claim.source_quality
                    )
                    claim = replace(claim, source_refs=checked_refs, source_quality=quality)
                    prelim = [
                        r["values"]
                        for r in item["preliminary_records"]
                        if r.get("status") == "validated_candidate"
                    ]
                    keys = set().union(*(p["dimensions"] for p in prelim))
                    dims = {}
                    for key in keys:
                        choices = [p["dimensions"].get(key) for p in prelim]
                        value = choices[0] if all(c == choices[0] for c in choices) else None
                        dims[key] = SourceRef(**value) if value else None
                    context = ClaimContext(claim, dims)
                    # The exact runtime relation maps are available on some
                    # records; otherwise this is its local scoped relation map.
                    from proofops.application.evidence.binding import local_relation_tags

                    relations = local_relation_tags(context)
                    if item.get("review_inputs"):
                        relations = {
                            k: {role: SourceRef(**v) if v else None for role, v in roles.items()}
                            for k, roles in item["review_inputs"]["relation_tags"].items()
                        }
                    results = {}
                    for phase in ("before", "after"):
                        semantic_policy = (
                            selected_policy["semantic_admission"]
                            if phase == "after"
                            else snapshot["analysis_profile_policy"]["semantic_admission"]
                        )
                        payload = {k: v for k, v in data.items() if k != "packet_sha256"}
                        if phase == "after":
                            payload["local_element_recovery_policy"] = POLICY
                        packet = freeze_packet(payload)
                        store = LocalSQLiteUsageStore(Path(directory) / f"{cid}-{phase}.sqlite3")
                        store.create_budget(
                            graph.tenant_id,
                            data["run_id"],
                            graph.document_version_id,
                            BudgetLimits(
                                1000000, 1000000, (RoleLimit("tagger", 3, 100000, 100000, 200000),)
                            ),
                        )

                        def invoke(request):
                            recorded = next(
                                r for r in runs if r.replicate_id == request["replicate_id"]
                            )
                            raw = recorded.raw_response_json
                            if raw is not None:
                                decoded = json.loads(raw)
                                decoded["packet_sha256"] = packet.packet_sha256
                                raw = json.dumps(decoded, ensure_ascii=False)
                            return RawTagResponse(
                                raw,
                                recorded.usage,
                                recorded.synthetic,
                                recorded.provider_response_json,
                            )

                        guarded = tag_replicates(
                            packet,
                            context=context,
                            track=TrackCandidate(
                                claim, data["track"], data.get("safe_harbor_category")
                            ),
                            original=graph,
                            relation_tags=relations,
                            rulepack=pack,
                            settings=tagging_settings(snapshot),
                            cache=ImmutableResponseCache(InMemoryImmutableCacheClient()),
                            usage_store=store,
                            invoke=invoke,
                            tenant_id=graph.tenant_id,
                            ensemble_id=data["run_id"],
                            consent_profile="offline-saved-response-evaluation",
                            token_counter=lambda s: 1,
                            count_input_tokens=lambda r: 10000,
                            now=lambda: 1,
                            pipeline_profile=data["pipeline_profile"],
                            semantic_policy=semantic_policy,
                        )
                        result = provisional_result(
                            guarded,
                            packet,
                            pack,
                            RuleContext(
                                graph.tenant_id,
                                graph.document_version_id,
                                claim.claim_id,
                                packet.packet_sha256,
                            ),
                            range_profile=True,
                            profile="dec24-v1" if phase == "before" else "k2-v1",
                            semantic_policy=semantic_policy,
                            original=graph,
                        )
                        results[phase] = hold_projection(
                            item | dict(provisional_grade=result),
                            profile="dec24-v1" if phase == "before" else "k2-v1",
                        )
                        if phase == "after":
                            for run in guarded:
                                for element in run.guarded.elements if run.guarded else ():
                                    if element.state != "present":
                                        continue
                                    for ref in element.evidence_refs:
                                        native = (
                                            pdf.pages[ref.page_num - 1]
                                            .crop(tuple(ref.bbox))
                                            .extract_text(x_tolerance=2, y_tolerance=3)
                                            or ""
                                        )
                                        if "".join(ref.quote.split()) not in "".join(
                                            native.split()
                                        ) and cid in {
                                            "NAVER-11",
                                            "NAVER-13",
                                            "NAVER-15",
                                            "NAVER-17",
                                            "NAVER-22",
                                            "KIA-00",
                                        }:
                                            false_verified.append(
                                                dict(
                                                    case_id=cid,
                                                    element=element.element_id,
                                                    quote=ref.quote,
                                                )
                                            )
                    replayed_before, after = (
                        projection(results["before"]),
                        projection(results["after"]),
                    )
                    if (replayed_before["states"], replayed_before["evidence_grade"]) != (
                        before["states"],
                        before["evidence_grade"],
                    ):
                        failures.append(
                            dict(case_id=cid, baseline_replay=replayed_before, saved=before)
                        )
                    for eid, value in before["states"].items():
                        if value == "present":
                            if after["states"].get(eid) != "present":
                                if integration_policy is None or any(
                                    e["element_id"] == eid and e["review"] == "원문 직접 지지"
                                    for e in review[cid]["elements"]
                                ):
                                    failures.append(dict(case_id=cid, lost_element=eid))
                            else:
                                preserved.append([cid, eid])
                    cases.append(
                        dict(
                            case_id=cid,
                            before=before,
                            after=after,
                            changed_elements=[
                                eid
                                for eid in before["states"]
                                if before["states"][eid] != after["states"].get(eid)
                            ],
                            status="saved-element-replicas-revalidated",
                        )
                    )
            print(name, "replayed", len(checkpoint["claims"]), flush=True)
    assert all(sha256(Path(p).read_bytes()).hexdigest() == h for p, h in hashes.items())
    record = dict(
        schema="k2-saved-response-replay-v1",
        cases=cases,
        failures=failures,
        false_verified=false_verified,
        false_verified_scope=(
            "newly recovered K2 local present citations; native bbox literal cross-check"
        ),
        preserved_present=preserved,
        policy_sha256=canonical_hash(selected_policy),
        input_sha256=hashes,
        inputs_unchanged=True,
        model_calls=0,
        paid_usd="0",
        seconds=monotonic() - start,
        source_replay="historical-graph-identity-and-receipt-integrity;fresh-OCR-not-run",
    )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "comparison.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {k: record[k] for k in ("failures", "false_verified", "seconds")}, ensure_ascii=False
        )
    )
    assert not failures and not false_verified


if __name__ == "__main__":
    main()
