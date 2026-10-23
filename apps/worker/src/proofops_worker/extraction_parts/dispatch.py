"""Provider fencing and ordered concurrent dispatch; accounting stays attempt-owned."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import Future
from typing import TYPE_CHECKING, Any

from proofops.application.claims import ExtractionProfile
from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
from proofops.application.ports.jobs import JobLease

if TYPE_CHECKING:
    from proofops_worker import extract_runner as runtime

PacketResult = dict[str, Any] | Exception


def fence_provider_call(
    runner: runtime.LocalExtractRunner, lease: JobLease, usage: dict[str, Any]
) -> None:
    """One atomic owner/cancellation check plus renewal for the PA2 policy.

    heartbeat uses the same _owned guard as can_call, inside its own writer
    transaction. Cost reservations and settlement still happen per attempt.
    """
    from proofops_worker import extract_runner as runtime

    if not runtime.fresh_execution_enabled() and not runner.store.jobs.can_call(
        lease, now=int(runner.clock())
    ):
        raise runtime.StageFailure("LEASE_LOST", usage=usage)
    try:
        runner.store.jobs.heartbeat(lease, now=int(runner.clock()), lease_seconds=300)
    except runtime.LeaseLost:
        raise runtime.StageFailure("LEASE_LOST", usage=usage) from None


def fxg_dispatch_guard(
    runner: runtime.LocalExtractRunner,
    lease: JobLease,
    usage: dict[str, Any],
    snapshot: dict[str, Any],
    graph: CanonicalDocumentGraph,
    profile: ExtractionProfile,
    limit: int,
) -> Callable[[], None] | None:
    """Additional FXG requests retain the original per-attempt authority and caps."""
    from proofops_worker import extract_runner as runtime

    if not getattr(runner.extractor, "_fxg_split", False):
        return None
    remaining, lock = limit, runtime.Lock()

    def guard() -> None:
        nonlocal remaining
        with lock:
            if remaining <= 0:
                raise ValueError("BUDGET_EXHAUSTED")
            runtime.fence_provider_call(runner, lease, usage)
            runtime.authorize_attempt(
                runner,
                snapshot,
                graph,
                profile,
                tenant_id=graph.tenant_id,
                run_id=snapshot["run_id"],
                check_binding=runtime.check_local_upstage_binding,
            )
            remaining -= 1

    return guard


def prefetch_packets(
    packets: Sequence[dict[str, Any]],
    invoke: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    max_workers: int = 16,
    on_page: Callable[[int, dict[str, PacketResult]], None] | None = None,
    prepare_pages: Callable[[list[dict[str, Any]]], None] | None = None,
) -> dict[str, PacketResult]:
    """Run paid packets concurrently; replay their outcomes in source order."""
    from proofops_worker import extract_runner as runtime

    def settle(packet: dict[str, Any]) -> PacketResult:
        try:
            return invoke(packet)
        except Exception as error:
            return error

    with runtime.ThreadPoolExecutor(max_workers=max_workers) as pool:
        pending: dict[Future[PacketResult], dict[str, Any]] | None
        if prepare_pages is not None:
            pages: dict[int, list[dict[str, Any]]] = {}
            for packet in packets:
                pages.setdefault(packet["untrusted_document_data"]["page_num"], []).append(packet)
            # Start a prepared page's calls while the next page's CPU preparation
            # proceeds. Discovery still consumes source order, and v2 tagging
            # still waits for the complete, source-attested extraction snapshot.
            pending = {}
            groups = list(pages.values())
            # Read the first page, then prepare the remaining pages together so
            # the existing process pool starts at most twice per batch.
            groups = groups[:1] + (
                [[packet for page in groups[1:] for packet in page]] if len(groups) > 1 else []
            )
            for page_packets in groups:
                prepare_pages(page_packets)
                for packet in page_packets:
                    pending[pool.submit(settle, packet)] = packet
            if on_page is None:
                paid = {
                    packet["untrusted_document_data"]["source_id"]: future.result()
                    for future, packet in pending.items()
                }
                return {
                    p["untrusted_document_data"]["source_id"]: paid[
                        p["untrusted_document_data"]["source_id"]
                    ]
                    for p in packets
                }
        else:
            pending = None
        if on_page is None:
            return dict(
                zip(
                    (p["untrusted_document_data"]["source_id"] for p in packets),
                    pool.map(settle, packets),
                    strict=True,
                )
            )
        if pending is None:
            pending = {pool.submit(settle, packet): packet for packet in packets}
        by_page: dict[int, dict[str, PacketResult]] = {}
        paid = {}
        counts: dict[int, int] = {}
        for packet in packets:
            page = packet["untrusted_document_data"]["page_num"]
            counts[page] = counts.get(page, 0) + 1
        for future in runtime.as_completed(pending):
            data = pending[future]["untrusted_document_data"]
            page, sid = data["page_num"], data["source_id"]
            paid[sid] = future.result()
            by_page.setdefault(page, {})[sid] = paid[sid]
            if len(by_page[page]) == counts[page]:
                on_page(page, by_page[page])
        return paid
