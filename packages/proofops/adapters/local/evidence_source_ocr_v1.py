"""EV1's unchanged literal/layout guards with the run's trusted raster reader."""

from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import evidence_source_verification_v1 as ev1
from proofops.adapters.local import upstage_ocr_profile_v4 as v4
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.adapters.local.local_raster_reader import (
    LocalRasterReader,
    interactive_catalog_requires_review,
)
from proofops.domain.provenance import canonical_hash

PROFILE = "evidence-source-ocr-v1"


def policy():
    return dict(
        schema="evidence_source_policy_v1",
        profile=PROFILE,
        base=ev1.policy(),
        reader_policy=v4.claim_source_policy(),
        wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


class Reader(v4.Reader):
    def _evidence_reader(self, graph, source, tenant_id, collections=None):
        modules, seen = self._modules(graph, source, tenant_id, collections)
        reader = _exec_private(
            Path(__file__).parent,
            "evidence_source_verification_v1.py",
            "proofops.adapters.local._ocr_v4_private.evidence",
        )
        raster = LocalRasterReader(source)
        reader._rendered_text = (
            raster.read
            if raster.policy["status"] == "ready"
            else modules["claim_source_verification"]._rendered_text
        )
        if interactive_catalog_requires_review(source):
            reader._rendered_text = lambda *a, **k: {
                "status": "unresolved",
                "reason": "interactive_visibility_requires_review",
            }
        reader.policy = policy
        return reader, seen

    def _finish_evidence(self, receipt, seen):
        receipt.update(
            run_id=self.run_id,
            page_collections=[seen[p] for p in sorted(seen)],
            rendered_reader_profile=v4.PROFILE,
        )
        receipt["artifact_sha256"] = canonical_hash(
            {k: v for k, v in receipt.items() if k != "artifact_sha256"}
        )
        return receipt

    def attest_evidence_sources(self, graph, source, *, tenant_id, physical_pages=None):
        reader, seen = self._evidence_reader(graph, source, tenant_id)
        return self._finish_evidence(
            reader.attest_evidence_sources(
                graph, source, tenant_id=tenant_id, physical_pages=physical_pages
            ),
            seen,
        )

    def replay_evidence_sources(self, receipt, graph, source, *, tenant_id):
        if receipt.get("policy") != policy() or receipt.get("run_id") != self.run_id:
            raise ValueError("EVIDENCE_SOURCE_POLICY_MISMATCH")
        reader, seen = self._evidence_reader(
            graph, source, tenant_id, receipt.get("page_collections", [])
        )
        base = reader.attest_evidence_sources(
            graph, source, tenant_id=tenant_id, physical_pages=receipt.get("physical_pages")
        )
        expected = self._finish_evidence(dict(base), seen)
        if canonical_hash(receipt) != canonical_hash(expected):
            raise ValueError("EVIDENCE_SOURCE_RECEIPT_MISMATCH")
        return reader.replay_evidence_sources(base, graph, source, tenant_id=tenant_id)


def attest_evidence_sources(graph, source, *, tenant_id, physical_pages=None, run_id=None):
    return Reader(v4.PageOCRStore.from_env(), run_id=run_id).attest_evidence_sources(
        graph, source, tenant_id=tenant_id, physical_pages=physical_pages
    )


def replay_evidence_sources(receipt, graph, source, *, tenant_id):
    return Reader(v4.PageOCRStore.from_env(), run_id=receipt["run_id"]).replay_evidence_sources(
        receipt, graph, source, tenant_id=tenant_id
    )
