"""W7 offline raw-selection replay and fresh Linux source attestation.

Input mounts and SQLite connections are read-only; all artifacts are new. No
tagging, grade calculation, reservation, provider transport or historical write.
"""

import argparse
import json
import socket
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from time import monotonic

from proofops.adapters.local.claim_source_verification import discovery_refs
from proofops.application.claims import ExtractionOutputError, discover_atomic_claims
from proofops.application.ingest.sentence_prefix import POLICY
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import UpstageClaimExtractor

from evaluation.pa9_source_gate import fixture


def read(path):
    return json.loads(path.read_text())


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def cleared(discovery):
    return replace(
        discovery,
        claims=tuple(
            replace(
                c,
                source_quality="unverified",
                source_refs=tuple(
                    replace(r, verification_state="candidate") for r in c.source_refs
                ),
            )
            for c in discovery.claims
        ),
    )


class NoTransport:
    model = "gpt-6-luna"
    wire_policy_version = 2

    def complete(self, *args, **kwargs):
        raise AssertionError("W7_NO_MODEL_CALLS")


def main():
    from proofops.adapters.local import evidence_source_ocr_v1 as evidence
    from proofops.adapters.local import upstage_ocr_profile_v6 as v6
    from proofops.adapters.local import upstage_ocr_profile_v10 as v10
    from proofops_api.hosted_ocr import ReplayOCRStore, reader_scope

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)

    def deny(*args, **kwargs):
        raise AssertionError("W7_OFFLINE_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    tracked = sorted(p for p in args.input.rglob("*") if p.is_file())
    hashes = {str(p.relative_to(args.input)): sha256(p.read_bytes()).hexdigest() for p in tracked}
    graph, source, before, snapshot, parse = fixture(args.input)
    settings = read(args.input / "settings.json")
    flags = {k: v for k, v in settings.items() if k.startswith("extraction_") and type(v) is bool}
    flags["position_order"] = "position_context_order" in settings
    flags["display_text_profile"] = settings.get("display_text_policy", {}).get("profile")
    old = UpstageClaimExtractor(NoTransport(), args.output / "old-resolver", **flags)
    new = UpstageClaimExtractor(
        NoTransport(), args.output / "new-resolver", **flags, extraction_sentence_prefix=True
    )
    assert asdict(old.profile) == snapshot["extraction_profile"], "W7_OLD_PROFILE_CHANGED"
    assert old.profile.prompt_sha256 == new.profile.prompt_sha256
    assert old.profile.rule_sha256 != new.profile.rule_sha256
    saved = {r.source_id: r for r in before.receipts}
    raw = {}
    for p in (args.input / "extraction-receipts").glob("*/packet.json"):
        packet = read(p)
        if packet["parse_manifest_id"] != graph.parse_manifest_id:
            continue
        if packet["untrusted_document_data"]["kind"] != "paragraph":
            continue
        response = p.parent / "raw_response.json"
        if response.exists():
            sid = packet["untrusted_document_data"]["source_id"]
            item = dict(packet=packet, payload=json.loads(read(response)["content"]))
            if sid in raw:
                assert raw[sid] == item
            raw[sid] = item
    changes = []

    class Replay:
        profile = new.profile

        def extract(self, packet):
            data = packet["untrusted_document_data"]
            receipt = saved[data["source_id"]]
            if receipt.status == "failed":
                raise ExtractionOutputError("retained_failure")
            original = json.loads(receipt.raw_response_json)
            if data["source_id"] not in raw:
                return original
            retained = raw[data["source_id"]]
            assert retained["packet"]["untrusted_document_data"] == data
            previous, _ = old._resolve_payload(
                retained["payload"],
                data["text"],
                data["source_id"],
                packet=retained["packet"],
                context_graph=graph,
            )
            assert [asdict(s) | dict(topic_ids=list(s.topic_ids)) for s in previous] == original[
                "spans"
            ], "W7_RETAINED_RAW_RESOLUTION_CHANGED"
            current, diagnostics = new._resolve_payload(
                retained["payload"],
                data["text"],
                data["source_id"],
                packet=retained["packet"],
                context_graph=graph,
            )
            changes.append(
                dict(
                    source_id=data["source_id"],
                    page=data["page_num"],
                    before=[asdict(s) for s in previous],
                    after=[asdict(s) for s in current],
                    **diagnostics,
                )
            )
            return dict(spans=[asdict(s) | dict(topic_ids=list(s.topic_ids)) for s in current])

    started = monotonic()
    stages = {}
    with reader_scope(ReplayOCRStore(args.input / "upstage.sqlite3")):
        # Rebuild all source approvals from immutable candidates. Old approvals
        # never carry over to the experiment's new quote/offset identity.
        reader = v6.for_run(snapshot["run_id"])
        phase = monotonic()
        table = reader.attest_tables(graph, source, tenant_id=graph.tenant_id)
        graph = reader.replay_tables(table, graph, source, tenant_id=graph.tenant_id)
        native = reader.attest_native_sources(
            graph,
            source,
            tenant_id=graph.tenant_id,
            geometry_mode=parse["native_paragraph_attestation"]["geometry_mode"],
        )
        graph = reader.replay_native_sources(native, graph, source, tenant_id=graph.tenant_id)
        if "evidence_source_attestation" in parse:
            proof = evidence.attest_evidence_sources(
                graph,
                source,
                tenant_id=graph.tenant_id,
                run_id=snapshot["run_id"],
                physical_pages=parse["evidence_source_attestation"]["physical_pages"],
            )
            graph = evidence.replay_evidence_sources(
                proof, graph, source, tenant_id=graph.tenant_id
            )
        stages["prepare_seconds"] = monotonic() - phase
        phase = monotonic()
        after = discover_atomic_claims(graph, before.scope, extractor=Replay())
        stages["selection_seconds"] = monotonic() - phase
        summaries = {}
        for name, discovery in (("before", before), ("after", after)):
            phase = monotonic()
            discovery = cleared(discovery)
            receipt = v10.for_run(snapshot["run_id"]).attest_claim_spans(
                graph, source, discovery_refs(discovery), tenant_id=graph.tenant_id
            )
            verified, _ = v10.replay_claim_spans(
                receipt, graph, source, discovery, tenant_id=graph.tenant_id
            )
            write(args.output / (name + "-claims.json"), [asdict(c) for c in verified.claims])
            write(args.output / (name + "-attestation.json"), receipt)
            summaries[name] = dict(
                claims=len(verified.claims),
                source_verified=sum(c.source_quality == "verified" for c in verified.claims),
            )
            stages[name + "_source_seconds"] = monotonic() - phase
            print(name, summaries[name], flush=True)
    assert hashes == {
        str(p.relative_to(args.input)): sha256(p.read_bytes()).hexdigest() for p in tracked
    }, "W7_INPUT_MUTATED"
    write(args.output / "changes.json", changes)
    write(
        args.output / "measurement.json",
        dict(
            schema="w7-sentence-replay-v1",
            input_hashes=hashes,
            input_unchanged=True,
            source_sha256=sha256(source).hexdigest(),
            policy=POLICY,
            policy_sha256=canonical_hash(POLICY),
            old_profile=asdict(old.profile),
            new_profile=asdict(new.profile),
            comparison=summaries,
            stages=stages,
            total_seconds=monotonic() - started,
            provider_calls=0,
            paid_usd="0",
            retained_raw_paragraph_responses=len(raw),
            replayed_paragraph_responses=len(changes),
            caveat="fresh source verification; no new tagging/grades; old snapshots untouched",
        ),
    )


if __name__ == "__main__":
    main()
