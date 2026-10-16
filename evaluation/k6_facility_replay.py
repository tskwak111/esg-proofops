"""Measure K6 boundary-candidate delivery and deterministic graph reload."""

from dataclasses import asdict

from proofops.adapters.local.k6_facilities import facility_graph
from proofops.application.analysis_profile import FINALS_K6_POLICY
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.tagging.k6_facilities import augment_packet
from proofops.domain.provenance import canonical_hash

from evaluation.k2_replay import historical_graph
from evaluation.k6_holdout_replay import LAB, OUT, read, write
from evaluation.pa9_source_gate import fixture


def main():
    state = LAB / "perf/I4/native-final/stage-B/naver"
    base, source, discovery, _, parse = fixture(state)
    base = historical_graph(base, parse, read(state / "extract-checkpoint.json"))
    graph, dimensions = facility_graph(
        base, source, discovery.claims, tenant_id=base.tenant_id, policy=FINALS_K6_POLICY
    )
    reloaded, repeated = facility_graph(
        base, source, discovery.claims, tenant_id=base.tenant_id, policy=FINALS_K6_POLICY
    )
    assert canonical_hash(asdict(graph)) == canonical_hash(asdict(reloaded))
    assert dimensions == repeated
    saved = {c["claim_id"]: c for c in read(state / "tag-checkpoint.json")["claims"]}
    rows = []
    for claim in discovery.claims:
        if claim.claim_id not in dimensions:
            continue
        data = {
            k: v for k, v in saved[claim.claim_id]["frozen_packet"].items() if k != "packet_sha256"
        }
        data["graph_sha256"] = canonical_hash(asdict(graph))
        packet = freeze_packet(data)
        augmented = augment_packet(
            packet, dimensions[claim.claim_id], graph, tenant_id=graph.tenant_id
        )
        headers = dimensions[claim.claim_id]["facility"]["source_refs"]
        candidates = [
            c
            for c in augmented.to_dict()["evidence_candidates"]
            if any(
                canonical_hash(r) == canonical_hash(h) for r in c["source_refs"] for h in headers
            )
        ]
        assert candidates and any(
            set(c["allowed_elements"]) & {"M2", "P3", "G4"} for c in candidates
        )
        rows.append(
            dict(
                claim_id=claim.claim_id,
                quote=claim.quote,
                facility=dimensions[claim.claim_id]["facility"],
                before="display/review dimension only",
                after_candidates=candidates,
                model_vote_added=False,
                rule_credit=False,
            )
        )
    assert len(rows) == 20
    write(
        OUT / "facility-candidates.json",
        dict(
            rows=rows,
            delivered=20,
            graph_reload_identical=True,
            graph_sha256=canonical_hash(asdict(graph)),
            policy_sha256=canonical_hash(FINALS_K6_POLICY),
            automatic_credit=False,
            assurance_covered_added=False,
            provider_calls=0,
        ),
    )
    print("facility candidates20; reload identical; automatic credit0")


if __name__ == "__main__":
    main()
