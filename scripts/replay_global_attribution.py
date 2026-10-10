"""SY2 read-only saved-attestation binding replay; no new source approval or model."""

import argparse
import json
import socket
import sqlite3
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from proofops.application.claims import Claim, ExtractionProfile, ExtractionReceipt
from proofops.application.evidence.binding import (
    ClaimContext,
    local_relation_tags,
)
from proofops.application.evidence.relation_attribution import (
    LEGACY_POLICY,
    POLICY,
    filter_dimensions,
    filter_evidence_dimensions,
)
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.evidence.span_citations import span_verified_graph, verify_source_ref
from proofops.application.ingest.graph_fusion import (
    QualityIssue,
    candidates_from_snapshot,
    fuse_candidates,
)
from proofops.application.ports.models import ModelBinding
from proofops.application.tagging.service import TaggingSettings, tag_replicates
from proofops.application.tagging.tracks import TrackCandidate
from proofops.application.tagging.unattended import provisional_result
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import RulePackSnapshot, pack_content_hash, snapshot_from_validated
from proofops.domain.rules.engine import RuleContext
from proofops.domain.values import _source_ref_from_dict
from replay_relation_attribution import artifacts, digest, read, reviewed_replay


def deny(*args, **kwargs):
    raise RuntimeError("SY2_NETWORK_FORBIDDEN")


def refs_map(values):
    return {key: _source_ref_from_dict(value) if value else None for key, value in values.items()}


def preliminary_dimensions(records, claim, graph, track, category, guarded):
    values = [r["values"] for r in records if r["status"] == "validated_candidate"]
    if len(values) != 3:
        return None
    winners = [
        v
        for v in values
        if v.get("track") and (v["track"]["track"], v["safe_harbor_category"]) == (track, category)
    ]
    if len(winners) < 2:
        return None
    dimensions = [refs_map(v["dimensions"]) for v in winners]
    if guarded:
        dimensions = [
            filter_dimensions(claim, d, graph, tenant_id=graph.tenant_id)[0] for d in dimensions
        ]
    return {
        k: dimensions[0].get(k)
        if all(d.get(k) == dimensions[0].get(k) for d in dimensions)
        else None
        for k in set().union(*dimensions)
    }


def relation_consensus(records, transform):
    values = [
        r["values"] for r in records if r["status"] == "validated_candidate" and "values" in r
    ]
    if len(values) != 3:
        return {}
    values = [{sid: transform(sid, refs_map(v)) for sid, v in rows.items()} for rows in values]
    return {
        sid: values[0][sid]
        if all(v.get(sid) == values[0][sid] for v in values)
        else dict.fromkeys(set().union(*(v.get(sid, {}) for v in values)))
        for sid in values[0]
    }


def saved_graph(state, rows):
    """Restore only hash-pinned saved approvals, never recompute OCR/attestation."""
    parser = next(
        r for _, _, r in rows if r.get("schema", "").startswith("local_parser_checkpoint")
    )
    extraction = [
        r for _, _, r in rows if r.get("schema", "").startswith("local_extract_checkpoint")
    ][-1]
    manifest_path = next((state / "parser-prepared").rglob("manifest.json"))
    manifest = read(manifest_path)
    for name, expected in manifest["artifacts"].items():
        assert digest(manifest_path.with_name(name)) == expected, name
    batches = candidates_from_snapshot(read(manifest_path.with_name("candidates.json")))
    graph = fuse_candidates(
        batches,
        tenant_id=parser["tenant_id"],
        fusion_version=manifest.get("fusion_version", 1),
        mixed_parser=manifest["parser_profile"].get("parser_mode") == "mixed-v1",
    )
    assert graph.to_dict() == read(manifest_path.with_name("graph.json"))
    graph = replace(
        graph,
        issues=tuple(
            QualityIssue(**(v | {"source_ids": tuple(v["source_ids"])}))
            for v in read(manifest_path.with_name("quality.json"))
        ),
    )
    receipts = [
        parser["native_paragraph_attestation"],
        parser["evidence_source_attestation"],
        extraction["claim_source_attestation"],
    ]
    for receipt in receipts:
        assert (
            canonical_hash({k: v for k, v in receipt.items() if k != "artifact_sha256"})
            == receipt["artifact_sha256"]
        )
        assert all(
            receipt[k] == getattr(graph, k)
            for k in ("tenant_id", "document_version_id", "parse_manifest_id", "source_sha256")
        )
    native, evidence, claims = receipts
    assert canonical_hash(asdict(graph)) == native["input_graph_sha256"]
    ids = {r["source_id"] for r in native["records"] if r["status"] == "verified"}
    graph = replace(
        graph,
        blocks=tuple(
            replace(b, quality="verified") if b.source_id in ids else b for b in graph.blocks
        ),
    )
    assert canonical_hash(asdict(graph)) == evidence["input_graph_sha256"]
    tables = [t for t in evidence["tables"] if t["status"] == "verified"]
    ids = {sid for t in tables for sid in t["member_ids"]}
    table_ids = {t["table_id"] for t in tables}
    graph = replace(
        graph,
        blocks=tuple(
            replace(b, quality="verified") if b.source_id in ids else b for b in graph.blocks
        ),
        issues=tuple(
            replace(
                i, state="resolved", reason="EV1 native/rendered grid checked; binding undetermined"
            )
            if i.kind == "table_vision_not_run" and i.source_ids and set(i.source_ids) <= table_ids
            else i
            for i in graph.issues
        ),
    )
    spans = tuple(
        replace(_source_ref_from_dict(r["ref"]), verification_state="verified")
        for r in evidence["records"]
        if r["kind"] == "paragraph" and r["status"] == "verified"
    )
    base_evidence = {
        k: v
        for k, v in evidence.items()
        if k not in {"run_id", "page_collections", "rendered_reader_profile", "artifact_sha256"}
    }
    graph = span_verified_graph(graph, spans, canonical_hash(base_evidence))
    assert canonical_hash(asdict(graph)) == parser["graph_sha256"]
    spans += tuple(
        replace(_source_ref_from_dict(r["ref"]), verification_state="verified")
        for r in claims["records"]
        if r["status"] == "verified"
    )
    graph = span_verified_graph(graph, spans, claims["artifact_sha256"])
    result = {}
    for raw in extraction["discovery"]["claims"]:
        receipt = raw["receipt"]
        claim = Claim(
            **(
                raw
                | {
                    "source_refs": tuple(_source_ref_from_dict(r) for r in raw["source_refs"]),
                    "topic_ids": tuple(raw["topic_ids"]),
                    "receipt": ExtractionReceipt(
                        **(receipt | {"profile": ExtractionProfile(**receipt["profile"])})
                    ),
                }
            )
        )
        checked = tuple(
            verify_source_ref(r, graph, tenant_id=graph.tenant_id) for r in claim.source_refs
        )
        if (
            claim.source_quality == "unverified"
            and checked
            and all(r.verification_state == "verified" for r in checked)
        ):
            claim = replace(claim, source_quality="verified", source_refs=checked)
        result[claim.claim_id] = claim
    return (
        graph,
        result,
        [
            dict(path=str(manifest_path), sha256=digest(manifest_path)),
            *[dict(schema=r["schema"], sha256=r["artifact_sha256"]) for r in receipts],
        ],
    )


def dec23_pack(pack):
    manifest = {k: v for k, v in asdict(pack).items() if k != "content"}
    files = {p: pack.file_content(p) for p in pack.files}
    next(e for e in files["rubric/elements.yaml"]["elements"] if e["id"] == "M2")[
        "binding_policy"
    ] = "ACTIVITY_SCOPE_V2"
    manifest.update(
        version=pack.version + "-sy2-dec23",
        status="draft",
        approved_by=None,
        approved_at=None,
        rule_pack_id=str(uuid5(NAMESPACE_URL, pack.sha256 + "sy2-dec23")),
    )
    for value in files.values():
        if "version" in value:
            value["version"] = manifest["version"]
    manifest["sha256"] = pack_content_hash(manifest, files)
    return snapshot_from_validated(manifest, files)


class SavedResponses:
    """Ephemeral projection cache; always return saved responses, never invoke."""

    def __init__(self, runs, packet, graph, pack, settings, track):
        self.runs = {r["request"]["replicate_id"]: r for r in runs}
        self.packet, self.graph, self.pack, self.settings, self.track = (
            packet,
            graph,
            pack,
            settings,
            track,
        )

    def get_raw(self, request, **kwargs):
        data, settings = self.packet.to_dict(), self.settings
        run = self.runs[request.replicate_id]
        raw = json.loads(run["raw_response_json"]) if run.get("raw_response_json") else None
        if raw is not None:
            raw["packet_sha256"] = self.packet.packet_sha256
        identity = dict(
            request=asdict(request),
            tenant_id=data["tenant_id"],
            run_id=data["run_id"],
            claim_id=data["claim_id"],
            packet_sha256=self.packet.packet_sha256,
            graph_sha256=data["graph_sha256"],
            rule_sha256=self.pack.sha256,
            model_sha256=settings.model_sha256,
            prompt_sha256=canonical_hash(
                settings.system_for_track(self.track.track, self.track.safe_harbor_category)
            ),
        )
        return json.dumps(
            dict(
                identity=identity,
                raw_response_json=json.dumps(raw) if raw else None,
                usage=run["usage"],
                synthetic=run["synthetic"],
                provider_response_json=run.get("provider_response_json"),
            )
        ).encode()

    def put_guarded(self, *args, **kwargs):
        pass


def replay(path):
    rows, before = artifacts(path)
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        snapshot = json.loads(db.execute("SELECT payload FROM run_snapshots").fetchone()[0])
    assert (
        canonical_hash({k: v for k, v in snapshot.items() if k != "input_hash"})
        == snapshot["input_hash"]
    )
    original = (
        path.parent
        / "objects/original"
        / snapshot["tenant_id"]
        / (snapshot["document"]["version_id"] + ".pdf")
    )
    assert digest(original) == snapshot["document"]["sha256"]
    graph, claims, pins = saved_graph(path.parent, rows)
    pins.append(dict(path=str(original), sha256=digest(original)))
    pack = dec23_pack(RulePackSnapshot(**snapshot["rulepack"]))
    settings = TaggingSettings(
        **(
            snapshot["tagging_settings"]
            | {"binding": ModelBinding(**snapshot["tagging_settings"]["binding"])}
        )
    )
    checkpoint_key, checkpoint_bytes, checkpoint = [
        (k, raw, r) for k, raw, r in rows if r.get("schema") == "local_tag_checkpoint_v1"
    ][-1]
    from hashlib import sha256

    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        metadata = json.loads(
            db.execute(
                "SELECT value FROM job_records WHERE kind='run' AND record_id='META'"
            ).fetchone()[0]
        )
    assert sha256(checkpoint_bytes).hexdigest() == metadata["tag_snapshot_sha256"]
    pins.append(dict(record_id=checkpoint_key, sha256=metadata["tag_snapshot_sha256"]))
    out, counts, projections = [], Counter(), []
    for item in checkpoint["claims"]:
        if not item.get("tag_runs") or not item.get("frozen_packet"):
            counts["claims_without_saved_tags"] += 1
            continue
        claim = claims[item["claim_id"]]
        data = item["frozen_packet"]
        dimensions = preliminary_dimensions(
            item["preliminary_records"],
            claim,
            graph,
            data["track"],
            data.get("safe_harbor_category"),
            False,
        )
        guarded = preliminary_dimensions(
            item["preliminary_records"],
            claim,
            graph,
            data["track"],
            data.get("safe_harbor_category"),
            True,
        )
        if dimensions is None or guarded is None:
            counts["preliminary_unresolved"] += 1
            continue
        contexts = {
            "off": ClaimContext(claim, dimensions),
            "sy1": ClaimContext(claim, guarded),
            "sy2": ClaimContext(claim, guarded),
        }
        data = item["frozen_packet"]
        assert data["graph_sha256"] == canonical_hash(asdict(graph))
        assert (
            canonical_hash({k: v for k, v in data.items() if k != "packet_sha256"})
            == data["packet_sha256"]
        )
        packet = freeze_packet(
            {k: v for k, v in data.items() if k != "packet_sha256"} | {"rule_sha256": pack.sha256}
        )
        track = TrackCandidate(claim, data["track"], data.get("safe_harbor_category"))
        globals_by_source = {
            r["source_id"]: c["allowed_elements"]
            for c in data["evidence_candidates"]
            if c["source_scope"] == "global_bound"
            for r in c["source_refs"]
        }
        candidates = {
            r["source_id"]: _source_ref_from_dict(r)
            for c in data["evidence_candidates"]
            for r in c["source_refs"]
        }
        modes = {}
        for mode, context in contexts.items():

            def transform(sid, roles):
                if mode == "off":
                    return roles
                return filter_evidence_dimensions(
                    claim,
                    candidates[sid],
                    roles,
                    graph,
                    tenant_id=graph.tenant_id,
                    policy=LEGACY_POLICY if mode == "sy1" else POLICY,
                    global_elements=globals_by_source.get(sid, ()),
                    rulepack=pack,
                )[0]

            external = relation_consensus(item["relation_records"], transform)
            relations = {**external, **local_relation_tags(context)}
            runs = tag_replicates(
                packet,
                context=context,
                track=track,
                original=graph,
                relation_tags=relations,
                rulepack=pack,
                settings=settings,
                cache=SavedResponses(item["tag_runs"], packet, graph, pack, settings, track),
                usage_store=None,
                invoke=deny,
                tenant_id=graph.tenant_id,
                ensemble_id=str(uuid5(NAMESPACE_URL, claim.claim_id + "sy2-offline")),
                consent_profile=snapshot["consent"]["consent_profile_id"],
                token_counter=lambda text: 0,
                count_input_tokens=deny,
                now=lambda: 0,
                pipeline_profile=snapshot.get("pipeline_profile"),
            )
            result = provisional_result(
                runs,
                packet,
                pack,
                RuleContext(
                    graph.tenant_id,
                    graph.document_version_id,
                    claim.claim_id,
                    packet.packet_sha256,
                    local_synthetic=True,
                ),
                range_profile=True,
            )
            modes[mode] = dict(
                replicas=[
                    dict(
                        replicate_id=r.replicate_id,
                        status=r.status,
                        errors=r.errors,
                        elements=[asdict(e) for e in r.guarded.elements] if r.guarded else [],
                    )
                    for r in runs
                ],
                projection=result,
            )
        projections.append(
            dict(
                claim_id=claim.claim_id,
                saved_packet_sha256=data["packet_sha256"],
                replay_packet_sha256=packet.packet_sha256,
                modes=modes,
            )
        )
        for off, sy1, sy2 in zip(
            modes["off"]["replicas"],
            modes["sy1"]["replicas"],
            modes["sy2"]["replicas"],
            strict=True,
        ):
            for a, b, c in zip(off["elements"], sy1["elements"], sy2["elements"], strict=True):
                eid = a["element_id"]
                for mode, value in (("off", a), ("sy1", b), ("sy2", c)):
                    counts[f"{eid}:{mode}:{value['state']}"] += 1
                if a["state"] != b["state"] or b["state"] != c["state"]:
                    out.append(
                        dict(
                            claim_id=claim.claim_id,
                            claim_pages=[r.page_num for r in claim.source_refs],
                            claim_quote=claim.quote,
                            replicate_id=off["replicate_id"],
                            element_id=eid,
                            before=a["state"],
                            sy1=b["state"],
                            sy2=c["state"],
                            evidence_refs=a["evidence_refs"],
                        )
                    )
    assert digest(path) == before
    return dict(
        path=str(path),
        database_sha256=before,
        originals_unchanged=True,
        source_pins=pins,
        historical_rulepack_sha256=snapshot["rulepack"]["sha256"],
        replay_rulepack_sha256=pack.sha256,
        counts=dict(counts),
        changes=out,
        projections=projections,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ad", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    worktree = Path(__file__).resolve().parents[1]
    states = {
        f"{arm}/{p.parent.name}": p.resolve()
        for arm in ("rb3", "rb4")
        for p in (worktree / f".local/{arm}").rglob("state.sqlite3")
    }
    states.update(
        {
            f"qi2/{c}": args.ad / f"lab/quality/QI2/states/{c}/state.sqlite3"
            for c in ("samsung", "kepco")
        }
    )
    result = dict(
        policies={"off": None, "sy1": LEGACY_POLICY, "sy2": POLICY},
        policy_hashes={"sy1": canonical_hash(LEGACY_POLICY), "sy2": canonical_hash(POLICY)},
        model_calls=0,
        paid_usd=0,
        method=(
            "Read-only hash-pinned saved attestation reconstruction; identical saved model votes "
            "through real tag_replicates/binding/guard/provisional rules for off/SY1/SY2 "
            "with DEC-23 M2. Ephemeral packet identities; no source re-attestation "
            "or stored revisions rewritten."
        ),
        limitations=[
            "No new PDF attestation: historical verifier unavailable for these policies.",
            "States counted per replica; model output accuracy is not measured.",
            "Projected DEC-23 pack is draft; rules use explicit local_synthetic context, "
            "never domain approval.",
        ],
        states={},
    )
    for name, path in states.items():
        result["states"][name] = replay(path)
        print(name, len(result["states"][name]["changes"]), flush=True)
    result["reviewed_27"] = reviewed_replay(args.ad)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
