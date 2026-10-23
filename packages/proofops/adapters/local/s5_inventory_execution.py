"""Bounded SC1 request execution; the existing pure planner/assembler owns evidence.

Exactly three distinct requests per chunk are retained. The caller's existing
budget, lease, authorization, scheduler and response receipts wrap each invoke.
After a stop, already admitted work settles; new windows are never dispatched.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

from proofops.application.tagging.element_inventory import (
    assemble_inventory,
    inventory_request,
    plan_inventory,
)


def build_inventory(
    graph: CanonicalDocumentGraph,
    selection: dict[str, Any],
    *,
    model_sha256: str,
    invoke: Callable[[dict[str, Any]], dict[str, Any] | None],
    max_workers: int,
    stopped: Callable[[], bool] = lambda: False,
) -> dict[str, Any]:
    if type(max_workers) is not int or not 1 <= max_workers <= 24:
        raise ValueError("S5_INVENTORY_WORKERS_INVALID")
    # Untyped dependency is outside S_ADB ownership.
    plan = plan_inventory(graph, selection)  # type: ignore[no-untyped-call]
    responses = {}

    def run(chunk: dict[str, Any]) -> dict[str, dict[str, Any] | None]:
        values = {}
        # Preserve SC1's max_replica_workers=1: parallelism is across chunks,
        # while every chunk still obtains its three distinct votes in order.
        for replica in (1, 2, 3):
            # Untyped dependency is outside S_ADB ownership.
            request = inventory_request(chunk, replica, model_sha256)  # type: ignore[no-untyped-call]
            value = None
            if not stopped():
                try:
                    value = invoke(request)
                except Exception:
                    pass  # Same failed-response representation as the serial builder.
            values[request["request_id"]] = value
        return values

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for offset in range(0, len(plan["chunks"]), max_workers):
            window = plan["chunks"][offset : offset + max_workers]
            pending = [pool.submit(copy_context().run, run, chunk) for chunk in window]
            for future in pending:
                responses.update(future.result())
    return cast(
        "dict[str, Any]",
        # Untyped dependency is outside S_ADB ownership.
        assemble_inventory(plan, responses, graph=graph, model_sha256=model_sha256),  # type: ignore[no-untyped-call]
    )
