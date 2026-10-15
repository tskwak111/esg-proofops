"""Bounded SC1 request execution; the existing pure planner/assembler owns evidence.

Exactly three distinct requests per chunk are retained. The caller's existing
budget, lease, authorization, scheduler and response receipts wrap each invoke.
After a stop, already admitted work settles; new windows are never dispatched.
"""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

from proofops.application.tagging.element_inventory import (
    assemble_inventory,
    inventory_request,
    plan_inventory,
)


def build_inventory(graph, selection, *, model_sha256, invoke, max_workers, stopped=lambda: False):
    if type(max_workers) is not int or not 1 <= max_workers <= 24:
        raise ValueError("S5_INVENTORY_WORKERS_INVALID")
    plan = plan_inventory(graph, selection)
    responses = {}

    def run(chunk):
        values = {}
        # Preserve SC1's max_replica_workers=1: parallelism is across chunks,
        # while every chunk still obtains its three distinct votes in order.
        for replica in (1, 2, 3):
            request = inventory_request(chunk, replica, model_sha256)
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
    return assemble_inventory(plan, responses, graph=graph, model_sha256=model_sha256)
