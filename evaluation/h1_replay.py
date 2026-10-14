"""H1 deterministic fixes over the measured v3 selections; no new model votes."""

import argparse
import json
import socket
from argparse import Namespace
from dataclasses import asdict, replace
from hashlib import sha256
from time import monotonic

from proofops.adapters.local import upstage_ocr_profile_v12 as native
from proofops.adapters.local.claim_source_verification import discovery_refs
from proofops.adapters.local.h1_native_title import NativeTitleCatalog
from proofops.application.analysis_profile import FINALS_H1_POLICY, apply_pilot_profile
from proofops.application.claims import discover_atomic_claims
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import UpstageClaimExtractor
from proofops_api.hosted_ocr import ReplayOCRStore, reader_scope

from evaluation.h1_holdout import CASES, OUT, A, load_a_scorer, read, write
from evaluation.pa9_source_gate import discovery_from_record, fixture
from evaluation.w7_sentence_replay import NoTransport


def flags(policy=FINALS_H1_POLICY):
    args = Namespace(
        analysis_profile="finals-unattended-v2",
        analysis_policy_sha256=canonical_hash(policy),
    )
    apply_pilot_profile(args)
    names = (
        "source_ids",
        "assertion_prompt",
        "context",
        "table_context",
        "table_rows",
        "pb1",
        "pb1_context_guard",
        "linewrap_join",
        "fragment_guard",
        "w9",
        "j3",
        "j7",
        "j8",
        "i3_wire",
        "k1",
        "k3",
        "sentence_prefix",
        "table_footnotes",
        "located_table_context",
        "h1",
        "i4_identity",
        "i5_tables",
        "k6",
        "q1",
    )
    return {"extraction_" + n: getattr(args, "extraction_" + n, False) for n in names} | dict(
        position_order=False, display_text_profile="glyph-joined-display-v1"
    )


def measure(company, *, label="h1-final", policy=FINALS_H1_POLICY, output_root=None):
    scorer, audit_sources = load_a_scorer()
    golds = [g for g in read(A / "v1-gold-atoms.json") if g["company"] == company]
    predictions, audits, changes, sources, stages, hashes = [], [], [], {}, [], {}
    output = (output_root or OUT) / label / company
    for case in CASES[company]:
        started = monotonic()
        state = A / "states" / case
        graph, source, _, snapshot, parse = fixture(state)
        retained_dir = OUT / "v3-measured" / company / case
        retained = discovery_from_record(read(retained_dir / "discovery.json"))
        settings = flags(policy)
        # Raw historical selections use UUID IDs. Replay their literal spans
        # through the unchanged postprocessor, never admit them as new cN votes.
        settings["extraction_i4_identity"] = False
        new = UpstageClaimExtractor(NoTransport(), output / case / "resolver", **settings)
        original_receipts = {r.source_id: r for r in retained.receipts}
        raw = {}
        for path in (retained_dir / "extraction-receipts").glob("*/packet.json"):
            response = path.parent / "raw_response.json"
            if response.exists():
                packet = read(path)
                raw[packet["untrusted_document_data"]["source_id"]] = (
                    packet,
                    json.loads(read(response)["content"]),
                )
                for p in [path, response]:
                    hashes[str(p)] = sha256(p.read_bytes()).hexdigest()
        with reader_scope(ReplayOCRStore(state / "ocr-attestation.sqlite3")):
            reader = native.for_run(snapshot["run_id"])
            table = reader.attest_tables(graph, source, tenant_id=graph.tenant_id)
            graph = reader.replay_tables(table, graph, source, tenant_id=graph.tenant_id)
            native_proof = reader.attest_native_sources(
                graph,
                source,
                tenant_id=graph.tenant_id,
                geometry_mode=parse["native_paragraph_attestation"]["geometry_mode"],
            )
            graph = reader.replay_native_sources(
                native_proof, graph, source, tenant_id=graph.tenant_id
            )

            # Mirror the new parser's explicit context marker over retained raw candidates.
            def marked(c):
                return (
                    replace(c, context=(*c.context, "h1-origin-context-v1"))
                    if "pb1-w9-v1" in c.context
                    else c
                )

            graph = replace(
                graph,
                candidates=tuple(
                    replace(b, blocks=tuple(marked(c) for c in b.blocks)) for b in graph.candidates
                ),
                blocks=tuple(
                    replace(b, candidates=tuple(marked(c) for c in b.candidates))
                    for b in graph.blocks
                ),
            )

            titles = NativeTitleCatalog(graph, source)

            class Replay:
                profile = new.profile

                def extract(self, packet):
                    sid = packet["untrusted_document_data"]["source_id"]
                    previous = json.loads(original_receipts[sid].raw_response_json)
                    if sid not in raw:
                        return previous
                    saved, payload = raw[sid]
                    assert saved["untrusted_document_data"] == packet["untrusted_document_data"]
                    saved = saved | {"h1_native_title": titles.proof(sid)}
                    spans, diagnostics = new._resolve_payload(
                        payload,
                        packet["untrusted_document_data"]["text"],
                        sid,
                        packet=saved,
                        context_graph=graph,
                    )
                    result = dict(
                        spans=[asdict(s) | dict(topic_ids=list(s.topic_ids)) for s in spans]
                    )
                    if result != previous:
                        changes.append(
                            dict(
                                case=case,
                                source_id=sid,
                                before=previous,
                                after=result,
                                diagnostics=diagnostics,
                            )
                        )
                    return result

            discovered = discover_atomic_claims(graph, retained.scope, extractor=Replay())
            receipt = reader.attest_claim_spans(
                graph, source, discovery_refs(discovered), tenant_id=graph.tenant_id
            )
            discovered, _ = native.replay_claim_spans(
                receipt, graph, source, discovered, tenant_id=graph.tenant_id
            )
            write(output / case / "discovery.json", asdict(discovered))
            write(output / case / "attestation.json", receipt)
            pp = [
                dict(
                    id=c.claim_id,
                    company=company,
                    page=c.source_refs[0].page_num,
                    quote=c.quote,
                    source_verified=c.source_quality == "verified",
                    raw=asdict(c),
                )
                for c in discovered.claims
            ]
            predictions.extend(pp)
            audits.extend(audit_sources(pp, graph, read(state / "pilot.json")["source_path"]))
            sources[case] = dict(
                graph_sha256=canonical_hash(asdict(graph)), source_sha256=graph.source_sha256
            )
            stages.append(dict(case=case, seconds=round(monotonic() - started, 3), claims=len(pp)))
    assert all(
        sha256(__import__("pathlib").Path(p).read_bytes()).hexdigest() == h
        for p, h in hashes.items()
    )
    result = dict(
        strict=scorer.evaluate(golds, predictions),
        policy=policy,
        policy_sha256=canonical_hash(policy),
        extraction_profile=asdict(new.profile),
        source_policy=native.claim_source_policy(),
        source_details=sources,
        stages=stages,
        native_mismatches=sum(a["native_audit_mismatch"] for a in audits),
        uncheckable=sum(a["uncheckable"] for a in audits),
        input_hashes=hashes,
        model_calls=0,
        paid_usd="0",
        original_selection="same v3 raw responses; no new votes",
        selection_wire_projection=(
            "historical literal selections only; fresh cN wire tested separately"
        ),
    )
    write(output / "predictions.json", predictions)
    write(output / "source-audit.json", audits)
    write(output / "changes.json", changes)
    write(output / "measurement.json", result)
    print(
        company,
        {
            k: result["strict"][k]
            for k in ("matches", "predictions", "recall", "precision", "verified_predictions")
        },
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", choices=CASES, required=True)
    parser.add_argument("--label", default="h1-final")
    args = parser.parse_args()

    def deny(*args, **kwargs):
        raise AssertionError("H1_REPLAY_NETWORK_FORBIDDEN")

    setattr(socket.socket, "connect", deny)
    setattr(socket.socket, "connect_ex", deny)
    socket.create_connection = deny
    measure(args.company, label=args.label)
