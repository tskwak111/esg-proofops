"""Pass attested facility headers as boundary candidates, never element votes."""

from dataclasses import asdict

from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.domain.values import SourceRef


def augment_packet(packet, dimensions, graph, *, tenant_id):
    data = packet.to_dict()
    facility = dimensions.get("facility", {})
    allowed = [e for e in data["allowed_elements"] if e in ("M2", "P3", "G4")]
    if not allowed or facility.get("state") != "source_verified":
        return packet
    refs = [
        verify_source_ref(SourceRef(**r), graph, tenant_id=tenant_id)
        for r in facility["source_refs"]
    ]
    if not refs or any(r.verification_state != "verified" for r in refs):
        return packet
    data.pop("packet_sha256")
    for ref in refs:
        candidate = next(
            (c for c in data["evidence_candidates"] if c["source_id"] == ref.source_id), None
        )
        if candidate is None:
            data["evidence_candidates"].append(
                dict(
                    source_id=ref.source_id,
                    source_scope="same_table",
                    allowed_elements=allowed,
                    source_refs=[asdict(ref)],
                )
            )
        else:
            candidate["allowed_elements"] = sorted(
                set(candidate["allowed_elements"]) | set(allowed)
            )
            if asdict(ref) not in candidate["source_refs"]:
                candidate["source_refs"].append(asdict(ref))
    return freeze_packet(data)
