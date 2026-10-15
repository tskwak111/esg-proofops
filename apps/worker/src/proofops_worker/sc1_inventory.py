"""One hosted inventory per final graph, using existing money/lease/receipt fences."""

import json
from contextlib import nullcontext
from decimal import Decimal

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
    estimated = reserve * calls
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
    stopped = False

    def invoke(original):
        nonlocal stopped
        if stopped:
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
                with context:
                    response = transport.invoke(request)
            live.runner.store.usage.record_usage(call, response.usage, now=int(live.runner.clock()))
            if response.usage.status != "succeeded" or not response.raw_response_json:
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
            raise
        finally:
            live.account(request["request_id"])

    provider = SC1InventoryProvider(
        live.receipts / "sc1-inventory-artifacts",
        model_sha256=live.settings.model_sha256,
        invoke=invoke,
    )
    result = provider(graph, selection)
    live._fence()
    # Reopening a completed immutable artifact must also expose its settled usage.
    for request_id in result["raw_responses"]:
        live.account(request_id)
    live.usage["sc1_inventory_plan"]["completed_calls"] = result["completed_calls"]
    return result
