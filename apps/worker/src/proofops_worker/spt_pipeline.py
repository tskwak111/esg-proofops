"""Bounded ready claims feeding the existing shared physical-attempt queue.

The runner already pipelines a claim's stages. Its legacy whole-claim worker
limit also counts local validation/persistence, leaving physical HTTP slots idle.
Two ready claims per HTTP slot overlap those gaps; only the provider scheduler
admits requests. Every claim still runs the original guarded path and serial
replica stop logic. Recovery and manual reprocessing retain the legacy executor.
"""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from proofops.application.tagging.spt_pipeline import POLICY, configured  # noqa: F401


def run_claims(process, claims, *, http_workers):
    from proofops.application.tagging.s2_budget import priority

    if type(http_workers) is not int or not 1 <= http_workers <= 24:
        raise ValueError("TAGGING_CONCURRENCY_INVALID")
    if not claims:
        return []

    def order(index):
        item = claims[index]
        base = priority(item)
        # Quote length is an input-only cost proxy, never a track/grade decision.
        # Preserve S2's verified/important classes before ordering the long tail.
        return (*base[:2], -len(item.quote), *base[2:])

    pending = iter(sorted(range(len(claims)), key=order))
    width = min(len(claims), http_workers * POLICY["ready_claims_per_http_slot"])
    results = [None] * len(claims)
    with ThreadPoolExecutor(max_workers=width, thread_name_prefix="spt-claim") as pool:
        active = {}

        def submit_next():
            index = next(pending, None)
            if index is not None:
                active[pool.submit(process, claims[index])] = index

        for _ in range(width):
            submit_next()
        try:
            while active:
                done, _ = wait(active, return_when=FIRST_COMPLETED)
                # Observe every completed exception before scheduling more work.
                completed = [(active.pop(future), future.result()) for future in done]
                for index, result in completed:
                    results[index] = result
                for _ in completed:
                    submit_next()
        except BaseException:
            for future in active:
                future.cancel()
            raise
    return results
