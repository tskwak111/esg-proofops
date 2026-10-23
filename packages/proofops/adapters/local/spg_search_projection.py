"""Batch only disposable search records during a locked publication read."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from proofops.adapters.local.claim_store import LocalClaimStore
    from proofops.adapters.local.job_store import LocalSQLiteJobStore
    from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
import json
from dataclasses import asdict

from proofops.domain.provenance import canonical_hash


class Projection:
    def __init__(
        self,
        claims: LocalClaimStore,
        tenant: str,
        run_id: str,
        graph: CanonicalDocumentGraph,
        snapshot: dict[str, Any],
    ) -> None:
        self.claims, self.tenant, self.run_id = claims, tenant, run_id
        self.graph, self.snapshot = graph, snapshot
        self.graph_hash = canonical_hash(asdict(graph))
        self.document: dict[str, Any] | None = None
        self.pending: dict[tuple[str, str], bytes] = {}
        with claims.store.jobs._transaction() as db:
            self.records: dict[tuple[str, str], bytes] = {
                (kind, key): value
                for kind, key, value in db.execute(
                    "SELECT kind,record_id,value FROM job_records WHERE tenant_id=? AND run_id=? "
                    "AND kind IN ('document_evidence_search','element_evidence_search')",
                    (tenant, run_id),
                )
            }

    def raw(self, kind: str, key: str) -> bytes | None:
        return self.records.get((kind, key))

    def put(self, kind: str, key: str, value: dict[str, Any]) -> None:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        prior = self.records.get((kind, key))
        if prior is not None and canonical_hash(json.loads(prior)) != canonical_hash(value):
            raise ValueError("element search artifact mismatch")
        if prior is None:
            self.records[kind, key] = encoded
            self.pending[kind, key] = encoded

    def finish(self) -> None:
        if self.snapshot != self.claims.store.snapshot(self.tenant, self.run_id):
            raise ValueError("SPG_PROJECTION_SNAPSHOT_CHANGED")
        if self.graph_hash != canonical_hash(asdict(self.graph)):
            raise ValueError("SPG_PROJECTION_GRAPH_CHANGED")
        jobs = self.claims.store.jobs
        with jobs._transaction() as db:
            for (kind, key), encoded in self.pending.items():
                prior = jobs._raw(db, self.tenant, self.run_id, kind, key)
                if prior is None:
                    jobs._put(db, self.tenant, self.run_id, kind, key, encoded, immutable=True)
                elif canonical_hash(json.loads(prior)) != canonical_hash(json.loads(encoded)):
                    raise ValueError("element search artifact mismatch")
        self.pending.clear()


def begin(
    claims: LocalClaimStore, tenant: str, run_id: str, graph: CanonicalDocumentGraph
) -> Projection | None:
    from proofops.application.spg_publication import enabled

    snapshot = claims.store.snapshot(tenant, run_id)
    # Untyped dependency is outside S_ADB ownership.
    if not enabled(snapshot.get("analysis_profile_policy", {})):  # type: ignore[no-untyped-call]
        return None
    projection = Projection(claims, tenant, run_id, graph, snapshot)
    setattr(claims, "_spg_projection", projection)
    return projection


def raw(
    jobs: LocalSQLiteJobStore,
    tenant: str,
    run_id: str,
    kind: str,
    key: str,
    projection: Projection | None,
) -> bytes | None:
    if projection is not None:
        return projection.raw(kind, key)
    with jobs._transaction() as db:
        return jobs._raw(db, tenant, run_id, kind, key)


def put(
    jobs: LocalSQLiteJobStore,
    tenant: str,
    run_id: str,
    kind: str,
    key: str,
    value: dict[str, Any],
    projection: Projection | None,
) -> None:
    if projection is not None:
        projection.put(kind, key, value)
        return
    with jobs._transaction() as db:
        prior = jobs._raw(db, tenant, run_id, kind, key)
        if prior is None:
            jobs._put(db, tenant, run_id, kind, key, value, immutable=True)
        elif kind == "element_evidence_search" and canonical_hash(
            json.loads(prior)
        ) != canonical_hash(value):
            raise ValueError("element search artifact mismatch")
