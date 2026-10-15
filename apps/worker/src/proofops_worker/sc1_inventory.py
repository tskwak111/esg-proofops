"""One hosted inventory per final graph, using existing money/lease/receipt fences."""

import json
from contextlib import nullcontext
from decimal import Decimal
from functools import partial
from threading import Event

from proofops.adapters.local.sc1_inventory_store import SC1InventoryProvider
from proofops.application.budget import BudgetCall, BudgetExceeded, TokenUsage
from proofops.application.tagging.element_inventory import plan_inventory
from proofops.application.tagging.i24_inventory import POLICY, transport_request
from proofops.application.tagging.service import RawTagResponse, output_reservation_tokens
from proofops.domain.provenance import canonical_hash
from proofops_agent.sc1_inventory import SC1InventoryTransport


def load_inventory(live, graph, selection):
    policy = live.snapshot.get("analysis_profile_policy", {}).get("sc1_inventory_transport")
    if policy != POLICY or graph is not live.graph:
        raise ValueError("SC1_HOSTED_POLICY_OR_GRAPH_MISMATCH")
    if live.settings.model_id != "gpt-6-luna":
        raise ValueError("SC1_HOSTED_MODEL_UNSUPPORTED")
    from proofops.adapters.local.i27_inventory_execution import Failures, request_scope
    from proofops.application.i27_inventory import POLICY as I27_POLICY

    optional = live.snapshot.get("analysis_profile_policy", {}).get("i27_sc1_optional_transient")
    if optional is not None and optional != I27_POLICY:
        raise ValueError("I27_SC1_FAILURE_POLICY_MISMATCH")
    failures = getattr(live.probe, "i27_inventory_failures", None)
    if optional and failures is None:
        failures = Failures()
        live.probe.i27_inventory_failures = failures
    live._fence()
    plan = plan_inventory(graph, selection)
    calls = 3 * len(plan["chunks"])
    # Use the existing conservative capacity price, including two bounded outputs
    # and the most expensive input token category. This is a reservation, not spend.
    from proofops.adapters.local.openai import PRICE

    execution = selection.get("fxh_inventory_execution")
    output = min(
        live.settings.max_tokens,
        (execution["inventory_output_tokens"] if execution else POLICY["max_output_tokens"]),
    )
    reserve = (
        (
            Decimal(live._capacity(live.settings.model_id))
            * max(Decimal(v) for k, v in PRICE.items() if k != "output")
            + Decimal(
                output_reservation_tokens(
                    model_id=live.settings.model_id, max_tokens=output, synthetic=False
                )
            )
            * Decimal(PRICE["output"])
        )
        / Decimal(1_000_000)
        * Decimal("1.10")
    )
    estimated = reserve * calls * (1 + I27_POLICY["max_retries"] if optional else 1)
    live.usage["sc1_inventory_plan"] = dict(
        planned_calls=calls,
        max_calls=POLICY["max_calls"],
        reserved_usd_upper_bound=str(estimated),
        max_reserved_usd=POLICY["max_reserved_usd"],
    )
    if calls > POLICY["max_calls"] or estimated > Decimal(POLICY["max_reserved_usd"]):
        raise BudgetExceeded("SC1_INVENTORY_LIMIT_EXCEEDED")
    transport = SC1InventoryTransport(
        live.probe,
        live.receipts / "sc1-inventory",
        settings=live.settings,
        tenant_id=graph.tenant_id,
        authorize=live._authorize,
        resume=live.resume,
    )
    parallel = live.snapshot.get("analysis_profile_policy", {}).get("s5_inventory_execution")
    if parallel not in (None, "s5_bounded_parallel_chunks_v1"):
        raise ValueError("S5_INVENTORY_EXECUTION_MISMATCH")
    stopped = False
    stop_event = Event()

    def invoke(original):
        nonlocal stopped
        if stopped or (parallel and stop_event.is_set()):
            raise ValueError("SC1_INVENTORY_STOPPED")
        live._fence()
        from proofops.application.rb3_deadline import admit

        if not admit(live.runner, live.snapshot, "tag"):
            stopped = True
            raise ValueError("TIME_BUDGET")
        request = transport_request(original, live.settings)
        live.allow_packet(request["claim_id"], request["packet_sha256"])
        call = BudgetCall(
            graph.tenant_id,
            selection["run_id"],
            graph.document_version_id,
            request["request_id"],
            1,
            "tagger",
            live.settings.model_id,
            live.settings.region,
            live.settings.model_sha256,
            request["request_signature"],
            request["replicate_id"],
        )
        directory = live.receipts / "sc1-inventory" / request["request_id"]
        response = None
        try:
            capacity = transport.count_input_tokens(
                request, counter=lambda s, u: live._capacity(live.settings.model_id)
            )
            if directory.exists():
                stored = json.loads((directory / "request.json").read_text())
                if stored["request"] != request:
                    raise ValueError("SC1_RECEIPT_MISMATCH")
                raw = json.loads((directory / "response.json").read_text())
                response = RawTagResponse(**(raw | dict(usage=TokenUsage(**raw["usage"]))))
            else:
                if not transport.may_dispatch():
                    raise ValueError("SC1_RECOVERY_ALLOWANCE_EXHAUSTED")
                lock = live.heartbeat_state.lock if live.heartbeat_state else nullcontext()
                with lock:
                    live._check_heartbeat()
                    if not live.runner.store.usage.reserve_budget(
                        call,
                        input_tokens=capacity,
                        max_output_tokens=output_reservation_tokens(
                            model_id=live.settings.model_id,
                            max_tokens=request["max_tokens"],
                            synthetic=False,
                        ),
                        pricing=None,
                        now=int(live.runner.clock()),
                    ):
                        raise ValueError("SC1_PENDING_CALL")
                live._fence()
                with lock:
                    live._check_heartbeat()
                    if not live.runner.store.usage.mark_dispatched(call):
                        raise ValueError("SC1_PENDING_CALL")
                context = (
                    live.probe.response_context(role="elements", replica=request["replicate_id"])
                    if hasattr(live.probe, "response_context")
                    else nullcontext()
                )
                with (
                    context,
                    request_scope(optional, original, failures) if optional else nullcontext(),
                ):
                    response = transport.invoke(request)
            live.runner.store.usage.record_usage(call, response.usage, now=int(live.runner.clock()))
            provider = json.loads(response.provider_response_json or "{}")
            failure = provider.get("i27_sc1_failure") if optional else None
            if failure is not None:
                if failure["request_id"] != request["request_id"]:
                    raise ValueError("I27_SC1_FAILURE_REQUEST_MISMATCH")
                failures.record(failure)
            if response.usage.status != "succeeded" or not response.raw_response_json:
                if failure is not None and failure["degraded"]:
                    # Preserve a failed vote and its reason in the immutable
                    # inventory; no absent/present substitute is manufactured.
                    return dict(
                        request_id=original["request_id"],
                        status="failed",
                        i27_sc1_failure=failure,
                        reason="SC1_OPTIONAL_TRANSIENT_UNINSPECTED",
                    )
                raise ValueError("SC1_PROVIDER_FAILED")
            result = {
                k: original[k]
                for k in (
                    "request_id",
                    "request_signature",
                    "packet_sha256",
                    "replicate_id",
                    "model_sha256",
                    "prompt_sha256",
                )
            }
            provider = json.loads(response.provider_response_json or "{}")
            result.update(
                provider_response_id=response.usage.provider_request_id,
                status=response.usage.status,
                synthetic=response.synthetic or bool(provider.get("simulated")),
                raw_response_json=response.raw_response_json,
                saved_response_origin=provider.get("saved_response_origin", {}),
                replayed_from_other_request=bool(provider.get("response_reuse")),
                transport_request_sha256=canonical_hash(request),
            )
            if failure is not None:
                result["i27_sc1_failure"] = failure
            return result
        except Exception as error:
            # A settled invalid answer poisons this chunk, not unrelated pages.
            # Budget, authorization, lease and transport uncertainty still stop.
            stopped = not (
                execution
                and str(error) == "SC1_PROVIDER_FAILED"
                and response is not None
                and response.usage.status == "succeeded"
            )
            if parallel and stopped:
                stop_event.set()
            raise
        finally:
            live.account(request["request_id"])

    build_options = {}
    if parallel:
        from proofops.adapters.local.s5_inventory_execution import build_inventory

        build_options["build"] = partial(
            build_inventory, max_workers=live.runner.max_workers, stopped=stop_event.is_set
        )
    provider = SC1InventoryProvider(
        live.receipts / "sc1-inventory-artifacts",
        model_sha256=live.settings.model_sha256,
        invoke=invoke,
        **build_options,
    )
    result = provider(graph, selection)
    live._fence()
    # Reopening a completed immutable artifact must also expose its settled usage.
    for request_id in result["raw_responses"]:
        live.account(request_id)
    if optional:
        for value in result["raw_responses"].values():
            if isinstance(value, dict) and value.get("i27_sc1_failure"):
                failures.record(value["i27_sc1_failure"])
        live.usage["i27_sc1_failures"] = failures.summary()
    live.usage["sc1_inventory_plan"]["completed_calls"] = result["completed_calls"]
    return result
