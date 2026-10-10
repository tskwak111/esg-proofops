"""Verified fact and classification periods; never derive dates from report years."""

from collections.abc import Mapping
from datetime import date
from typing import Any


def _period(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    start, end = value.get("period_start"), value.get("period_end")
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    try:
        if date.fromisoformat(start) > date.fromisoformat(end):
            return None
    except ValueError:
        return None
    return start, end


def period_reason(packet: Mapping[str, Any], documents: Mapping[str, Any]) -> str | None:
    sources = {source["source_id"]: source for source in packet["sources"]}
    fact_periods = {}
    for role in ("sustainability", "financial"):
        fact = packet[role]
        document = documents[sources[fact["source_id"]]["document_id"]]
        binding = document["fact_bindings"][fact["source_id"]]
        value = binding.get("period_binding")
        required = document.get("period_binding_required") is True
        if value is None and not required:
            continue
        period = _period(value)
        if period is None:
            return "fact_period_binding_missing"
        fact_periods[role] = period
        if packet["item"] == "C2" and fact["normalized"] != "/".join(period):
            return "fact_period_binding_mismatch"
    if packet["item"] != "C4":
        return None
    identity = packet["identity"]
    claim_period = _period(identity)
    context = packet["c4_context"]
    for source_id in (*context["definition_source_ids"], *context["calculation_source_ids"]):
        document = documents[sources[source_id]["document_id"]]
        binding = document["source_bindings"][source_id]
        value = binding.get("period_binding")
        if value is None and document.get("period_binding_required") is not True:
            continue
        period = _period(value)
        if period is None or claim_period is None:
            return "classification_period_binding_missing"
        if period != claim_period:
            return "classification_period_mismatch"
    if any(period != claim_period for period in fact_periods.values()):
        return "classification_period_mismatch"
    return None
