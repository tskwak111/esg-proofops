"""Deterministic registry search; quotes are candidates until human difference linkage."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


def difference_binding(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Exact review target, invalidated by changes to identity, facts or decision context."""
    return deepcopy(
        {
            key: packet[key]
            for key in (
                "identity",
                "item",
                "sustainability",
                "financial",
                "comparability",
                "claim",
                "c3_context",
                "c4_context",
            )
        }
    )


def human_linked(binding: Mapping[str, Any], packet: Mapping[str, Any]) -> bool:
    return (
        binding.get("human_reviewed") is True
        and isinstance(binding.get("reviewed_by"), str)
        and bool(binding["reviewed_by"].strip())
        and binding.get("difference_binding") == difference_binding(packet)
    )


def registered_explanation_search(
    packet: Mapping[str, Any], documents: Mapping[str, Any], coverage: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Return registered reviewed explanation quotes in stable order, without inference.

    This port enumerates evidence only. The service revalidates bytes, semantic roles,
    coverage and human difference linkage before any candidate affects a decision.
    """
    receipt = coverage.get(packet["search"]["receipt_id"])
    if not isinstance(receipt, Mapping):
        return []
    reviewed = receipt.get("reviewed_source_ids", [])
    required = receipt.get("required_document_ids", [])
    if not isinstance(reviewed, list) or not isinstance(required, list):
        raise ValueError("coverage_unverified")
    candidates = []
    for document_id in sorted(documents):
        if document_id not in required:
            continue
        document = documents[document_id]
        for source_id, binding in sorted(document.get("source_bindings", {}).items()):
            if source_id not in reviewed:
                continue
            if "explanation" not in binding.get("roles", []):
                continue
            candidates.append(
                {
                    "source_id": source_id,
                    "document_id": document_id,
                    "artifact_sha256": document["artifact_sha256"],
                    "locator": binding["locator"],
                    "quote": binding["quote"],
                }
            )
    return sorted(candidates, key=lambda source: source["source_id"])
