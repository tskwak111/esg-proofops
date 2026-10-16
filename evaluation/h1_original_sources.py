"""Reverify A's exact original 88 spans under H1; no claim/tag/grade changes."""

import socket
from dataclasses import asdict, replace

from proofops.adapters.local import upstage_ocr_profile_v12 as native
from proofops.adapters.local.claim_source_verification import discovery_refs
from proofops_api.hosted_ocr import ReplayOCRStore, reader_scope

from evaluation.h1_holdout import CASES, OUT, A, load_a_scorer, read, write
from evaluation.pa9_source_gate import fixture


def main():
    _, audit_sources = load_a_scorer()
    old = read(A / "predictions.json")
    rows, audits, output = [], [], OUT / "original-source-replay"
    for company, cases in CASES.items():
        for case in cases:
            state = A / "states" / case
            graph, source, discovery, snapshot, parse = fixture(state)
            discovery = replace(
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
            with reader_scope(ReplayOCRStore(state / "ocr-attestation.sqlite3")):
                reader = native.for_run(snapshot["run_id"])
                table = reader.attest_tables(graph, source, tenant_id=graph.tenant_id)
                graph = reader.replay_tables(table, graph, source, tenant_id=graph.tenant_id)
                proof = reader.attest_native_sources(
                    graph,
                    source,
                    tenant_id=graph.tenant_id,
                    geometry_mode=parse["native_paragraph_attestation"]["geometry_mode"],
                )
                graph = reader.replay_native_sources(
                    proof, graph, source, tenant_id=graph.tenant_id
                )
                receipt = reader.attest_claim_spans(
                    graph, source, discovery_refs(discovery), tenant_id=graph.tenant_id
                )
                discovery, _ = native.replay_claim_spans(
                    receipt, graph, source, discovery, tenant_id=graph.tenant_id
                )
                write(output / case / "attestation.json", receipt)

                def key(ref):
                    return ref["source_id"], ref["char_start"], ref["char_end"]

                records = {key(r["ref"]): r for r in receipt["records"]}
                predictions = []
                for claim in discovery.claims:
                    before = next(p for p in old[company] if p["id"] == claim.claim_id)
                    verified = claim.source_quality == "verified"
                    rows.append(
                        dict(
                            id=claim.claim_id,
                            company=company,
                            page=claim.source_refs[0].page_num,
                            quote=claim.quote,
                            before_verified=before["source_verified"],
                            after_verified=verified,
                            reasons=[
                                records[key(asdict(r))].get("reason") for r in claim.source_refs
                            ],
                        )
                    )
                    predictions.append(
                        dict(
                            id=claim.claim_id,
                            company=company,
                            page=claim.source_refs[0].page_num,
                            quote=claim.quote,
                            source_verified=verified,
                            raw=asdict(claim),
                        )
                    )
                audits.extend(
                    audit_sources(predictions, graph, read(state / "pilot.json")["source_path"])
                )
    result = dict(
        before_verified=sum(r["before_verified"] for r in rows),
        after_verified=sum(r["after_verified"] for r in rows),
        denominator=len(rows),
        newly_verified=sum(not r["before_verified"] and r["after_verified"] for r in rows),
        regressed=sum(r["before_verified"] and not r["after_verified"] for r in rows),
        false_verified=sum(a["native_audit_mismatch"] for a in audits),
        uncheckable=sum(a["uncheckable"] for a in audits),
        model_calls=0,
        paid_usd="0",
        rows=rows,
    )
    write(output / "source-audit.json", audits)
    write(output / "comparison.json", result)
    print({k: v for k, v in result.items() if k != "rows"}, flush=True)


if __name__ == "__main__":

    def deny(*args, **kwargs):
        raise AssertionError("H1_SOURCE_REPLAY_NETWORK_FORBIDDEN")

    setattr(socket.socket, "connect", deny)
    setattr(socket.socket, "connect_ex", deny)
    socket.create_connection = deny
    main()
