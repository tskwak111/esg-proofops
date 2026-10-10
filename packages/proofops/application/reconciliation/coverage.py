"""Optional page/note coverage sidecars, independent of the frozen 1.1 schemas."""

from collections.abc import Mapping
from typing import Any


def coverage_reason(entry: Mapping[str, Any], documents: Mapping[str, Any]) -> str | None:
    """Reject forged completeness; older document-only receipts remain supported."""
    required = entry["required_document_ids"]
    complete = entry["state"] == "complete"
    for owner in [entry, *(documents[key] for key in required)]:
        catalog = owner.get("coverage_catalog")
        if catalog is not None:
            if not isinstance(catalog, Mapping) or catalog.get("state") not in (
                "complete",
                "incomplete",
            ):
                return "coverage_unverified"
            if complete and catalog["state"] == "incomplete":
                return "coverage_incomplete"
        for limit_key in ("candidate_limit", "limits"):
            limit = owner.get(limit_key)
            if limit is not None and (
                not isinstance(limit, Mapping) or type(limit.get("truncated")) is not bool
            ):
                return "coverage_unverified"
            if complete and isinstance(limit, Mapping) and limit["truncated"]:
                return "candidate_catalog_truncated_incomplete_search"
    has_units = any("coverage_units" in documents[key] for key in required)
    if any(
        "coverage_catalog" in documents[key] and "coverage_units" not in documents[key]
        for key in required
    ):
        return "coverage_unverified"
    if not has_units and "coverage_manifest" not in entry:
        return None
    manifest = entry.get("coverage_manifest")
    if not isinstance(manifest, list):
        return "coverage_unverified"
    expected: dict[tuple[str, str], Mapping[str, Any]] = {}
    for document_id in required:
        units = documents[document_id].get("coverage_units")
        if not isinstance(units, list) or not units:
            return "coverage_unverified"
        for unit in units:
            if not isinstance(unit, Mapping) or unit.get("kind") not in ("page", "note"):
                return "coverage_unverified"
            if any(not isinstance(unit.get(k), str) or not unit[k] for k in ("unit_id", "locator")):
                return "coverage_unverified"
            key = (document_id, unit["unit_id"])
            if key in expected:
                return "coverage_unverified"
            expected[key] = unit
    seen = set()
    covered_sources = set()
    for row in manifest:
        if not isinstance(row, Mapping):
            return "coverage_unverified"
        if any(not isinstance(row.get(k), str) for k in ("document_id", "unit_id")):
            return "coverage_unverified"
        key = (row["document_id"], row["unit_id"])
        if key not in expected or key in seen:
            return "coverage_unverified"
        seen.add(key)
        document = documents[key[0]]
        if (
            row.get("artifact_sha256") != document.get("artifact_sha256")
            or row.get("locator") != expected[key]["locator"]
        ):
            return "coverage_unverified"
        if any(type(row.get(k)) is not bool for k in ("readable", "reviewed")):
            return "coverage_unverified"
        if complete and (not row["readable"] or not row["reviewed"]):
            return "coverage_incomplete"
        source_ids = row.get("source_ids")
        if not isinstance(source_ids, list):
            return "coverage_unverified"
        for source_id in source_ids:
            if not isinstance(source_id, str):
                return "coverage_unverified"
            binding = document.get("source_bindings", {}).get(source_id)
            if not isinstance(binding, Mapping) or binding.get("coverage_unit_id") != key[1]:
                return "coverage_unverified"
            if row["readable"] and row["reviewed"]:
                covered_sources.add(source_id)
    if complete and seen != set(expected):
        return "coverage_incomplete"
    if not set(entry["reviewed_source_ids"]) <= covered_sources:
        return "coverage_unverified"
    return None
