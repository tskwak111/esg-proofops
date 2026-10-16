"""Restore exact E21 graph identities from retained source receipts, offline.

This reproduces saved authority; it is not a fresh PDF/source attestation.
Every projection must match the next stored graph hash. No receipt is repaired,
no source reader is invoked, and the original SC1 inventory is replay-validated.
"""

from dataclasses import asdict, dataclass, replace
from hashlib import sha256

from proofops.adapters.local.verified_read_cache import _project_owned_cells, _project_parse
from proofops.application.ingest.graph_fusion import (
    QualityIssue,
    candidates_from_snapshot,
    fuse_candidates,
)
from proofops.application.tagging.analysis_scope import InventoryIndex
from proofops.domain.provenance import canonical_hash

from evaluation.qt2_replay import read


@dataclass
class _EmptyDiscovery:
    claims: tuple = ()


def _identity(graph, expected):
    if canonical_hash(asdict(graph)) != expected:
        raise ValueError("EV1_RETAINED_GRAPH_IDENTITY_MISMATCH")


def _receipt(value):
    if (
        canonical_hash({k: v for k, v in value.items() if k != "artifact_sha256"})
        != value["artifact_sha256"]
    ):
        raise ValueError("EV1_RETAINED_RECEIPT_HASH_MISMATCH")


def restore(directory, artifacts):
    manifest = next((directory / "parser-prepared").rglob("manifest.json"))
    meta = read(manifest)
    for name in ("candidates.json", "quality.json"):
        if sha256(manifest.with_name(name).read_bytes()).hexdigest() != meta["artifacts"][name]:
            raise ValueError("EV1_RETAINED_PARSER_HASH_MISMATCH")
    graph = fuse_candidates(
        candidates_from_snapshot(read(manifest.with_name("candidates.json"))),
        tenant_id=meta["tenant_id"],
        fusion_version=meta["fusion_version"],
        mixed_parser=True,
    )
    graph = replace(
        graph,
        issues=tuple(
            QualityIssue(**(i | dict(source_ids=tuple(i["source_ids"]))))
            for i in read(manifest.with_name("quality.json"))
        ),
    )
    parse = next(a for a in artifacts if "native_paragraph_attestation" in a)
    if sha256(manifest.read_bytes()).hexdigest() != parse["manifest_sha256"]:
        raise ValueError("EV1_RETAINED_MANIFEST_HASH_MISMATCH")
    if parse["runtime_note_review_artifacts"]:
        raise ValueError("EV1_RETAINED_NOTE_PROJECTION_UNSUPPORTED")
    for key, native in (
        ("native_paragraph_attestation", True),
        ("evidence_source_attestation", False),
    ):
        receipt = parse[key]
        _receipt(receipt)
        _identity(graph, receipt["input_graph_sha256"])
        graph = _project_parse(receipt, graph, native=native)
    _identity(graph, parse["graph_sha256"])
    tagging = next(a for a in artifacts if "claims" in a)
    expected = tagging["sc1_inventory"]["selection"]["graph_sha256"]
    for extraction in artifacts:
        if "claim_source_attestation" not in extraction:
            continue
        receipt = extraction["claim_source_attestation"]
        _receipt(receipt)
        _identity(graph, receipt["input_graph_sha256"])
        _, scoped = _project_owned_cells(
            receipt, graph, _EmptyDiscovery(), graph.tenant_id, failed_state="candidate"
        )
        if canonical_hash(asdict(scoped)) != expected:
            continue  # Earlier extraction revisions remain historical evidence.
        if any(
            c["frozen_packet"]["graph_sha256"] != expected
            for c in tagging["claims"]
            if c.get("frozen_packet")
        ):
            raise ValueError("EV1_RETAINED_PACKET_GRAPH_MISMATCH")
        return scoped, tagging, InventoryIndex(tagging["sc1_inventory"], scoped)
    raise ValueError("EV1_RETAINED_INVENTORY_GRAPH_NOT_FOUND")
