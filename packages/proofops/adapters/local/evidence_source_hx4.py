"""HX4 permits an empty source scope without claiming evidence or absence."""

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import evidence_source_h7 as previous
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.application.ingest.gri import _validate_graph
from proofops.domain.provenance import canonical_hash

PROFILE = "evidence-source-hx4-v1"
SCHEMA = "evidence_source_hx4_attestation_v1"


def policy():
    return dict(
        previous.policy(),
        profile=PROFILE,
        previous_policy_sha256=canonical_hash(previous.policy()),
        wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        empty_scope="bound-empty-receipt; no-verification-or-absence",
    )


_wrapper = _exec_private(
    Path(__file__).parent, "evidence_source_h7.py", "proofops.adapters.local._hx4_evidence"
)
_wrapper.PROFILE, _wrapper.SCHEMA, _wrapper.policy = PROFILE, SCHEMA, policy


def attest_evidence_sources(graph, source, *, tenant_id, physical_pages=None, **kwargs):
    _validate_graph(graph, tenant_id)
    if (
        not isinstance(source, bytes)
        or not 0 < len(source) <= 100 * 1024 * 1024
        or (sha256(source).hexdigest() != graph.source_sha256)
    ):
        raise ValueError("EVIDENCE_SOURCE_MISMATCH")
    pages = (
        tuple(sorted({b.page_num for b in graph.blocks}))
        if physical_pages is None
        else tuple(physical_pages)
    )
    if pages:
        return _wrapper.attest_evidence_sources(
            graph, source, tenant_id=tenant_id, physical_pages=pages, **kwargs
        )
    result = dict(
        schema=SCHEMA,
        policy=policy(),
        tenant_id=tenant_id,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        source_sha256=graph.source_sha256,
        input_graph_sha256=canonical_hash(asdict(graph)),
        physical_pages=(),
        records=[],
        tables=[],
        semantic_binding="undetermined",
        scope="empty-selection; no-source-admission",
        run_id=kwargs.get("run_id"),
        paid_calls=0,
    )
    result["artifact_sha256"] = canonical_hash(result)
    return result


def replay_evidence_sources(receipt, graph, source, *, tenant_id):
    if receipt.get("physical_pages"):
        return _wrapper.replay_evidence_sources(receipt, graph, source, tenant_id=tenant_id)
    expected = attest_evidence_sources(
        graph, source, tenant_id=tenant_id, physical_pages=(), run_id=receipt.get("run_id")
    )
    if canonical_hash(receipt) != canonical_hash(expected):
        raise ValueError("EVIDENCE_SOURCE_RECEIPT_MISMATCH")
    return graph
