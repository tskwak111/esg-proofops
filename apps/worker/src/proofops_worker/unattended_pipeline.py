"""Tag completed pages against a frozen full parse graph, before extraction ends.

All outputs remain provisional. Later source attestation changes the display
source status, never the already frozen packet, replicas or confirmed revisions.
The final checkpoint owns and hashes these records; nothing is published early.
"""

from __future__ import annotations

from concurrent.futures import Future
from typing import TYPE_CHECKING, Any, cast

from proofops.application.claims import ExtractionProfile
from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
from proofops.application.ports.jobs import JobLease

from proofops_worker.extraction_parts.dispatch import PacketResult

if TYPE_CHECKING:
    from proofops_worker.extract_runner import LocalExtractRunner
    from proofops_worker.tag_runner import LocalTagRunner


import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from hashlib import sha256

from proofops.adapters.local.claim_store import claim_scope, snapshot_pins
from proofops.application.claims import discover_atomic_claims
from proofops.domain.provenance import canonical_hash


class PageTagPipeline:
    def __init__(
        self,
        extractor_runner: LocalExtractRunner,
        snapshot: dict[str, Any],
        graph: CanonicalDocumentGraph,
        profile: ExtractionProfile,
        lease: JobLease,
        checkpoint: bytes,
    ) -> None:
        from proofops_worker.composition import build_composition

        bound_composition = getattr(extractor_runner, "tag_composition", None)
        self.runner = (
            bound_composition()
            if bound_composition
            else cast("LocalTagRunner", build_composition(stage="tag"))
        )
        self.snapshot, self.graph, self.profile = snapshot, graph, profile
        self.lease, self.checkpoint = lease, checkpoint
        self.scope = claim_scope(snapshot, graph)  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.pending: list[Future[dict[str, Any]]] = []
        self.started = time.monotonic()

    def ready(self, page: int, responses: dict[str, PacketResult]) -> None:
        # Make a private immutable copy; extraction threads can't change this input.
        self.pending.append(self.pool.submit(self._tag, page, dict(responses)))

    def _tag(self, page: int, responses: dict[str, PacketResult]) -> dict[str, Any]:
        profile = self.profile

        class CompletedExtractor:
            def __init__(self) -> None:
                self.profile = profile

            def extract(self, packet: dict[str, Any]) -> dict[str, Any]:
                value = responses.get(packet["untrusted_document_data"]["source_id"])
                if isinstance(value, Exception):
                    raise value
                if value is None:
                    text = packet["untrusted_document_data"]["text"]
                    return dict(
                        spans=[
                            dict(
                                char_start=0,
                                char_end=len(text),
                                quote=text,
                                kind="unknown",
                                reason="beyond_extraction_limit",
                                topic_ids=[],
                            )
                        ]
                    )
                return value

        discovery = discover_atomic_claims(
            self.graph,
            replace(self.scope, mode="declared_subset", selected_pages=(page,)),
            extractor=CompletedExtractor(),
        )
        if not discovery.claims:
            return dict(page=page, claims=[], started_seconds=time.monotonic() - self.started)
        payload = snapshot_pins(self.snapshot, self.graph, self.profile, self.checkpoint)  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
        payload["coverage"] = json.loads(self.checkpoint)["coverage"]
        payload["discovery"] = asdict(discovery)
        payload["synthetic"] = False
        usage: dict[str, Any] = dict(model_calls=0, synthetic_calls=0)
        started = time.monotonic() - self.started
        result = json.loads(
            self.runner._execute(
                self.lease, self.snapshot, usage, evidence=(payload, discovery, self.graph)
            )
        )
        return dict(
            page=page,
            claims=result["claims"],
            claim_hashes={c.claim_id: canonical_hash(asdict(c)) for c in discovery.claims},
            started_seconds=started,
            completed_seconds=time.monotonic() - self.started,
            graph_sha256=canonical_hash(asdict(self.graph)),
            usage=usage,
            parse_checkpoint_sha256=sha256(self.checkpoint).hexdigest(),
        )

    def finish(self) -> list[dict[str, Any]]:
        try:
            return [future.result() for future in self.pending]
        finally:
            self.pool.shutdown(wait=True)
            self.runner.uploads.close()
            self.runner.uploads.registry.close()
