"""Shared per-attempt authority and usage; selection and lease order stay caller-owned."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, cast

from proofops.application.claims import ClaimExtractorPort, ExtractionProfile
from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
from proofops.application.preflight import Preflight

if TYPE_CHECKING:
    from proofops_worker.extract_runner import LocalExtractRunner


from datetime import UTC, datetime
from threading import Lock

from proofops.application.authorization import AuthContext


def authorize_attempt(
    runner: LocalExtractRunner,
    snapshot: dict[str, Any],
    graph: CanonicalDocumentGraph,
    profile: ExtractionProfile,
    *,
    tenant_id: str,
    run_id: str,
    check_binding: Callable[..., Preflight],
) -> None:
    authorization = check_binding(
        binding=snapshot["runtime"],
        consent=snapshot["consent"],
        auth=AuthContext("local-worker", tenant_id, "viewer", frozenset(), run_id),
        checked_at=datetime.fromtimestamp(runner.clock(), UTC).isoformat(),
        source_sha256=graph.source_sha256,
        model_sha256=profile.model_sha256,
    )
    if not authorization.ready:
        raise ValueError("LOCAL_TEST_AUTHORIZATION_INVALID")


class PaidClaimExtractor(ClaimExtractorPort, Protocol):
    """Accounting capability required by the existing real-extraction path."""

    def usage_checkpoint(self) -> int: ...
    def cumulative_usage(
        self, *, since: int = 0, parse_manifest_id: str | None = None
    ) -> dict[str, Any]: ...


class ExtractionAttemptContext:
    def __init__(
        self,
        runner: LocalExtractRunner,
        snapshot: dict[str, Any],
        usage: dict[str, Any],
        *,
        is_real: bool = False,
        since: int = 0,
        manifest_id: str | None = None,
    ) -> None:
        self.runner = runner
        self.snapshot = snapshot
        self.usage = usage
        self.is_real = is_real
        self.since = since
        self.manifest_id = manifest_id
        self.lock = Lock()

    def sync_usage(self) -> None:
        if self.is_real:
            with self.lock:
                self.usage.update(
                    cast(PaidClaimExtractor, self.runner.extractor).cumulative_usage(
                        since=self.since, parse_manifest_id=self.manifest_id
                    )
                )

    def admit(
        self,
        graph: CanonicalDocumentGraph,
        profile: ExtractionProfile,
        *,
        tenant_id: str,
        run_id: str,
        admit: Callable[[LocalExtractRunner, dict[str, Any], str], bool],
        check_binding: Callable[..., Preflight],
    ) -> bool:
        if not admit(self.runner, self.snapshot, "extract"):
            return False
        if self.is_real:
            authorize_attempt(
                self.runner,
                self.snapshot,
                graph,
                profile,
                tenant_id=tenant_id,
                run_id=run_id,
                check_binding=check_binding,
            )
        return True
