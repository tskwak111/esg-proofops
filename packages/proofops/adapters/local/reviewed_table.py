"""Bridge an operator-reviewed PDF grid into an unverified canonical table.

The review artifact is source-bound but is not a parser or a verification
receipt.  This adapter deliberately builds one isolated candidate graph and
delegates numeric normalization to ``normalize_table_bindings``; it never
promotes a reviewed cell, infers a unit, or admits a numeric observation.

The one geometric correction it does make: a reviewed rectangle is drawn on the
extractor's word boxes, which are font metric boxes rather than ink.  Where those
disagree with the glyphs (measured: every pinned word of ``lotte.pdf`` page 117
inks a median 5.957pt above its reported box), the reviewed rectangle does not
contain its own text, so the native selected-cell verifier correctly refuses the
cell's promoted crop.  Each canonical cell box is therefore the ink union of
exactly the words that review already pinned to that cell -- same membership,
same raw text, same row/column/span, same source hashes.  Nothing is widened to
unpinned text and an unresolvable cell keeps the reviewed rectangle and records
why, which can only hold a cell back.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from proofops.adapters.local.reviewed_table_layout import (
    _COMBINED_SCHEMA as _COMBINED_SCHEMA,
)
from proofops.adapters.local.reviewed_table_layout import (
    _EXTERNAL_CONTEXT_FIELDS as _EXTERNAL_CONTEXT_FIELDS,
)
from proofops.adapters.local.reviewed_table_layout import (
    _GEOMETRY_SCHEMA as _GEOMETRY_SCHEMA,
)
from proofops.adapters.local.reviewed_table_layout import (
    _LINEAGE_TOL as _LINEAGE_TOL,
)
from proofops.adapters.local.reviewed_table_layout import (
    _SCHEMA as _SCHEMA,
)
from proofops.adapters.local.reviewed_table_layout import (
    _TENANT as _TENANT,
)
from proofops.adapters.local.reviewed_table_layout import (
    _canonical_cell_boxes as _canonical_cell_boxes,
)
from proofops.adapters.local.reviewed_table_layout import (
    _external_review_context as _external_review_context,
)
from proofops.adapters.local.reviewed_table_layout import (
    _id as _id,
)
from proofops.adapters.local.reviewed_table_layout import (
    _native_bbox as _native_bbox,
)
from proofops.adapters.local.reviewed_table_layout import (
    _overlaps as _overlaps,
)
from proofops.adapters.local.reviewed_table_layout import (
    _page_word_ink as _page_word_ink,
)
from proofops.adapters.local.reviewed_table_layout import (
    _require_review as _require_review,
)
from proofops.adapters.local.reviewed_table_layout import (
    _union as _union,
)
from proofops.adapters.local.reviewed_table_layout import (
    graph_from_review as graph_from_review,
)
from proofops.adapters.local.reviewed_table_layout import (
    normalize_reviewed_layout as normalize_reviewed_layout,
)
from proofops.adapters.local.reviewed_table_layout import (
    reviewed_cell_geometry as reviewed_cell_geometry,
)
from proofops.application.evidence.citations import verify_source_ref
from proofops.application.ingest.graph_fusion import (
    CanonicalDocumentGraph,
)
from proofops.application.ingest.normalize import (
    NormalizationResult,
    Observation,
    normalize_table_bindings,
)
from proofops.domain.numeric import observation_source_holds
from proofops.domain.provenance import canonical_hash

_NUMERIC_INPUT_SCHEMA = "reviewed_table_numeric_input_v1"


def artifact_from_review(
    review: dict[str, Any],
    source: bytes,
    *,
    tenant_id: str = _TENANT,
    native_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a JSON-safe immutable evaluation artifact; never an admission record."""
    graph, result, table_id, role_bindings = normalize_reviewed_layout(
        review, source, tenant_id=tenant_id
    )
    cell_geometry = reviewed_cell_geometry(review, source)
    cells = {
        candidate.source.source_native_id.removeprefix("reviewed-cell:"): block
        for block in graph.blocks
        for candidate in block.candidates
        if candidate.source.source_native_id.startswith("reviewed-cell:")
    }
    canonical_cells = []
    for key, review_cell in sorted(review["cells"].items()):
        block = cells[key]
        geometry = cell_geometry["cells"][key]
        canonical_cells.append(
            {
                "cell_key": key,
                "canonical_cell_id": block.source_id,
                "raw_text": review_cell["raw_text"],
                "raw_text_sha256": sha256(review_cell["raw_text"].encode()).hexdigest(),
                "physical_page": review["physical_page"],
                "bbox": review_cell["bbox"],
                "canonical_bbox": list(block.bbox) if block.bbox else None,
                "canonical_bbox_source": geometry["canonical_bbox_source"],
                "reviewed_region_offset_pt": geometry.get("reviewed_region_offset_pt"),
                "canonical_bbox_hold_reason": geometry.get("reason"),
                "row": review_cell["row"],
                "column": review_cell["column"],
                "row_span": review_cell["row_span"],
                "column_span": review_cell["column_span"],
                "word_indices": review_cell["word_indices"],
                "clipped_word_indices": review_cell["clipped_word_indices"],
                "rotated_word_indices": review_cell["rotated_word_indices"],
                "extraction_status": review_cell["extraction_status"],
                "quality": block.quality,
            }
        )
    observations = []
    for item in result.observations:
        value = asdict(item)
        value["source_refs"] = [
            {**asdict(ref), "bbox": list(ref.bbox) if ref.bbox else None}
            for ref in item.source_refs
        ]
        value["source_blocks"] = [block.source_id for block in item.source_blocks]
        value["parent_relations"] = [list(relation) for relation in item.parent_relations]
        value["unit_interpretation"] = "raw_literal_only"
        observations.append(value)
    artifact = {
        "schema": _SCHEMA,
        "geometry_schema": _GEOMETRY_SCHEMA,
        "status": "unverified_candidate",
        "eligible_for_admission": False,
        "tenant_id": tenant_id,
        "source": {
            "source_sha256": review["source_sha256"],
            "physical_page": review["physical_page"],
            "coordinate_system": review["coordinate_system"],
            "page_bbox": review["page_bbox"],
            "layout_sha256": review["layout_sha256"],
            "review_status": review["status"],
            "reviewer": review["layout"].get("reviewer"),
            "layout_interpretation": review["layout_interpretation"],
        },
        "native_verification": native_receipt if native_receipt is not None else "not_run",
        "semantic_verification": "not_run",
        "canonical_cell_geometry": {
            "rule": (
                "canonical cell bbox = ink union of exactly the native words the review "
                "pinned to that cell; reviewed membership, text, grid indices and spans "
                "are unchanged and no unpinned word is included"
            ),
            "pinned_word_ink": cell_geometry["pinned_word_ink"],
            "cells_from_native_word_ink": sum(
                1
                for detail in cell_geometry["cells"].values()
                if detail["canonical_bbox_source"] == "native_word_ink_union"
            ),
            "cells_from_operator_reviewed_region": sorted(
                key
                for key, detail in cell_geometry["cells"].items()
                if detail["canonical_bbox_source"] == "operator_reviewed_region"
            ),
        },
        "canonical_table": {"table_id": table_id, "cells": canonical_cells},
        "explicit_role_bindings": role_bindings,
        "numeric_observations": observations,
        "normalization_issues": [issue.to_dict() for issue in result.conflicts],
        "holds": [
            "operator_reviewed_layout_is_not_native_source_verification",
            "semantic_metric_period_unit_binding_not_admitted",
            "raw_split_subscript_units_preserved_without_unit_conversion",
        ],
        "graph_sha256": canonical_hash(asdict(graph)),
    }
    artifact["artifact_sha256"] = canonical_hash(artifact)
    return artifact


def load_artifact(
    review_path: Path,
    pdf_path: Path,
    *,
    tenant_id: str = _TENANT,
    native_attest: bool = False,
) -> dict[str, Any]:
    review = json.loads(review_path.read_text())
    source = pdf_path.read_bytes()
    native_receipt = None
    if native_attest:
        graph, _, _, _ = normalize_reviewed_layout(review, source, tenant_id=tenant_id)
        from proofops.adapters.local.selected_cell_table_verification import attest_tables

        native_receipt = attest_tables(graph, source, tenant_id=tenant_id)
    return artifact_from_review(review, source, tenant_id=tenant_id, native_receipt=native_receipt)


# ---------------------------------------------------------------------------
# Numeric-service input view
#
# Everything below turns the reviewed grid into the input the existing pure
# numeric check already consumes (``application.numeric_analysis``). It adds no
# verifier: the promotion of a cell comes from the unmodified native selected-cell
# receipt through its own ``replay_tables``, and the promotion of a citation comes
# from the unmodified ``citations.verify_source_ref``. A reviewed role assignment
# stays an explicit operator/AI declaration and is never turned into a grade.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReviewedNumericInputs:
    """The reviewed grid expressed in the numeric service's own input types.

    ``normalization`` is the existing ``NormalizationResult``, so the observations
    and unresolved issues stay in the type the normalizer already returns.
    """

    graph: CanonicalDocumentGraph
    native_receipt: dict[str, Any]
    table_id: str
    cell_source_ids: dict[str, str]
    promoted_source_ids: frozenset[str]
    normalization: NormalizationResult
    candidates: tuple[dict[str, Any], ...]
    context_receipts: tuple[dict[str, Any], ...] = ()
    # Caller-reviewed footnote/coverage passages outside the table grid. Carried
    # forward from ``review["context"]`` unchanged; never verified or promoted
    # here. See ``_external_review_context``.
    external_context: tuple[dict[str, Any], ...] = ()

    @property
    def observations(self) -> tuple[Observation, ...]:
        return self.normalization.observations


def native_attested_layout(
    review: dict[str, Any],
    source: bytes,
    *,
    tenant_id: str = _TENANT,
    verify_context: bool = False,
    requested_values: bool = False,
    also: Sequence[dict[str, Any]] = (),
) -> tuple[
    CanonicalDocumentGraph,
    dict[str, Any],
    dict[str, str],
    str,
    frozenset[str],
    tuple[dict[str, Any], ...],
]:
    """Reviewed graph after the existing native attestation and its own replay.

    ``graph_from_review`` is called with its existing result shape; the graph it
    returns is handed to the existing selected-cell verifier and replay for values.
    Optional context proof/replay adds literal metric/unit/header cells; reviewed
    role declarations alone never promote anything. ``requested_values`` opts
    into a separate bounded receipt for exactly the declared value cells; the
    default and legacy context/header proofs remain unchanged.

    ``also`` is forwarded to ``graph_from_review`` so one combined snapshot can hold
    several reviewed grids. Every grid's value cells go through the same unchanged
    value verifier and every grid's declared role cells through the same context
    verifier; ``table_id`` stays the first review's table and the extra tables are
    reachable through the returned cell-id map under their ``"<n>:reviewed-table"``
    keys.
    """
    reviews = (review, *tuple(also))
    graph, native_ids = graph_from_review(review, source, tenant_id=tenant_id, also=also)
    from proofops.adapters.local.receipt_environment_compat import replay_receipt
    from proofops.adapters.local.selected_cell_table_verification import (
        attest_tables,
        replay_tables,
    )

    # The external replay dispatcher preserves the graph result of these readers.
    replay = cast(Callable[..., CanonicalDocumentGraph], replay_receipt)
    header_receipt = None
    if requested_values:
        from proofops.adapters.local import requested_table_verification as requested

        canonical_input = {
            c.source.source_native_id: b.source_id for b in graph.blocks for c in b.candidates
        }
        selected_values = sorted(
            {
                canonical_input[
                    native_ids[("" if i == 0 else f"{i}:") + c["source_cells"]["value"]]
                ]
                for i, item in enumerate(reviews)
                for c in item["candidates"]
            }
        )
        receipt = requested.attest_tables(graph, source, selected_values, tenant_id=tenant_id)
        promoted = replay(
            requested.replay_tables, receipt, graph, source, selected_values, tenant_id=tenant_id
        )
        if verify_context:
            # Existing context reader revalidates its own legacy header proof;
            # never disguise the requested-value receipt as a v3 receipt.
            header_receipt = attest_tables(graph, source, tenant_id=tenant_id)
    else:
        receipt = attest_tables(graph, source, tenant_id=tenant_id)
        promoted = replay(replay_tables, receipt, graph, source, tenant_id=tenant_id)
        header_receipt = receipt
    canonical = {
        candidate.source.source_native_id: block.source_id
        for block in promoted.blocks
        for candidate in block.candidates
    }
    context_receipts = []
    if verify_context:
        from proofops.adapters.local.reviewed_context_verification import (
            MAX_CELLS,
            attest_context_cells,
            replay_context_cells,
        )

        # Both receipts attest the same original graph; combine only their replayed
        # promotions, never feed a changed graph back into the header receipt.
        value_keys: set[str] = set()
        context_keys: set[str] = set()
        for index, item in enumerate(reviews):
            prefix = "" if index == 0 else f"{index}:"
            value_keys.update(prefix + c["source_cells"]["value"] for c in item["candidates"])
            context_keys.update(
                prefix + c["source_cells"][role]
                for c in item["candidates"]
                # ``column_qualifier`` is the opt-in per-column sub-header under a
                # banded year header; it is a real reviewed cell like the other
                # three, so it goes through the same unchanged context verifier.
                for role in ("metric", "unit", "year", "column_qualifier")
                if role in c["source_cells"]
            )
        selected = sorted(canonical[native_ids[key]] for key in context_keys - value_keys)
        for offset in range(0, len(selected), MAX_CELLS):
            batch = selected[offset : offset + MAX_CELLS]
            proof = attest_context_cells(
                graph, source, batch, tenant_id=tenant_id, header_receipt=header_receipt
            )
            checked = replay(
                replay_context_cells,
                proof,
                graph,
                source,
                batch,
                tenant_id=tenant_id,
                header_receipt=header_receipt,
            )
            verified = {block.source_id for block in checked.blocks if block.quality == "verified"}
            promoted = replace(
                promoted,
                blocks=tuple(
                    replace(block, quality="verified") if block.source_id in verified else block
                    for block in promoted.blocks
                ),
            )
            context_receipts.append(proof)
    return (
        promoted,
        receipt,
        {key: canonical[native] for key, native in native_ids.items()},
        canonical["reviewed-table"],
        frozenset(
            source_id
            for record in receipt["records"]
            for selection in record["selections"]
            for source_id in selection["promoted_source_ids"]
        )
        | frozenset(
            record["source_id"]
            for proof in context_receipts
            for record in proof["records"]
            if record["status"] == "verified"
        ),
        tuple(context_receipts),
    )


def _numeric_usability(
    observation: Observation,
    graph: CanonicalDocumentGraph,
    promoted_source_ids: frozenset[str],
    reviewed_context: dict[str, Any],
    external_context: tuple[dict[str, Any], ...] = (),
) -> tuple[list[str], dict[str, Any]]:
    """Why the numeric service can or cannot read this observation as a source.

    Reports one hold per blocking cell, named by the role that pinned it, so a
    hold is actionable instead of a single opaque refusal. Nothing here decides a
    value: it only reads back the existing verifier's and the domain's own state.

    ``reviewed_context`` carries the reviewed cell keys the four-role normalization
    does not bind (the facility row label and the footnote cells). A nonempty one is
    its own hold: the review says this value has a facility and a note, and neither
    is bound, so the observation stays unverified even when all four literal cells
    verify. An empty list is not a hold, and nothing here invents note semantics.

    ``external_context`` is the separate table-level set of reviewed passages that
    are not any cell (see ``_external_review_context``): a nonempty one can never be
    bound by the per-candidate mechanism above, by construction, so every candidate
    of a table that carries one stays held for it. This does not say the passage
    applies to this value, this year or every year; it only refuses to let an
    unrelated, unbound, caller-reviewed passage disappear from the diagnostic.
    """
    roles = {target: name for _, target, name in observation.parent_relations}
    value_ids = {source for source, _, _ in observation.parent_relations}
    roles.update({source: "value_raw" for source in value_ids})
    holds: list[str] = []
    refs = {}
    for ref in observation.source_refs:
        role = roles.get(ref.source_id, "unpinned_context")
        refs[role] = {
            "source_id": ref.source_id,
            "quote": ref.quote,
            "verification_state": ref.verification_state,
            "natively_promoted": ref.source_id in promoted_source_ids,
        }
        if ref.verification_state != "verified":
            holds.append(f"source_unverified:{role}")
        elif ref.source_id not in promoted_source_ids:
            holds.append(f"cell_not_natively_promoted:{role}")
    if observation.value_state != "value":
        holds.append(f"value_state:{observation.value_state}")
    if len(value_ids) != 1:
        holds.append("observation_root_unresolved")
    for role, keys in sorted(reviewed_context.items()):
        if keys:
            holds.append(f"reviewed_context_unbound:{role}")
    if external_context:
        holds.extend(f"external_context_unbound:{entry['kind']}" for entry in external_context)
    source_holds = observation_source_holds(observation, graph)
    holds.extend(f"source_hold:{reason}" for reason in source_holds["reasons"])
    return sorted(dict.fromkeys(holds)), {"refs": refs, "source_holds": source_holds}


def reviewed_numeric_inputs(
    review: dict[str, Any],
    source: bytes,
    *,
    tenant_id: str = _TENANT,
    verify_context: bool = False,
    requested_values: bool = False,
) -> ReviewedNumericInputs:
    """Normalize the reviewed roles over the natively attested graph.

    An observation is promoted to ``quality="verified"`` only when every one of
    its own source refs verified through ``verify_source_ref`` against that graph
    and every one of those cells is in the replayed native value/context proofs. That is
    strictly narrower than the refs the pure check re-validates itself, so this
    flag can never admit a value the domain would refuse. Anything else keeps the
    normalizer's ``unverified`` quality and carries its blocking cells.
    """
    graph, receipt, cell_ids, table_id, promoted_ids, context_receipts = native_attested_layout(
        review,
        source,
        tenant_id=tenant_id,
        verify_context=verify_context,
        requested_values=requested_values,
    )
    external_context = _external_review_context(review)
    observations, issues, candidates = [], list(graph.issues), []
    for index, item in enumerate(review["candidates"]):
        refs = item.get("source_cells")
        if not isinstance(refs, dict):
            raise ValueError("reviewed candidate cell roles required")
        required = {"metric", "unit", "year", "value"}
        if not required <= set(refs) or any(not isinstance(refs[key], str) for key in required):
            raise ValueError("reviewed candidate explicit metric/unit/year/value roles required")
        if any(refs[key] not in cell_ids for key in required):
            raise ValueError("reviewed candidate references an unknown cell")
        if set(refs) - required - {"notes", "row_labels", "column_qualifier"}:
            raise ValueError("unsupported reviewed cell role")
        assignment = {
            "metric_raw": cell_ids[refs["metric"]],
            "unit_raw": cell_ids[refs["unit"]],
            "reporting_period": cell_ids[refs["year"]],
            "value_raw": cell_ids[refs["value"]],
        }
        # Reviewed context the existing four-role normalization does not bind: the
        # facility row label and the footnote cells. These are real dimensions of
        # the value, so they are kept visible per candidate by their own reviewed
        # cell keys and, when nonempty, hold the observation below.
        context = {}
        for role in ("row_labels", "notes"):
            keys = refs.get(role, [])
            if not isinstance(keys, list) or any(
                not isinstance(key, str) or key not in cell_ids for key in keys
            ):
                raise ValueError("reviewed context must reference known cells")
            context[role] = list(keys)
        if "column_qualifier" in refs:
            # A banded year header states the year; the sub-header states whether the
            # column is a target or an actual, and that is not bound by the four-role
            # normalization. Keeping it as context means a candidate whose column
            # qualifier is unbound is held, so a target can never be read as an actual.
            key = refs["column_qualifier"]
            if not isinstance(key, str) or key not in cell_ids:
                raise ValueError("reviewed context must reference known cells")
            context["column_qualifier"] = [key]
        record = {
            "candidate_index": index,
            "value_cell": refs["value"],
            "role_cells": {role: refs[role] for role in ("metric", "unit", "year", "value")},
            "unbound_reviewed_context": context,
            "unbound_reviewed_dimensions": sorted(
                set(refs) - required - {"row_labels", "notes", "column_qualifier"}
            ),
            "normalization_status": "held",
        }
        try:
            normalized = normalize_table_bindings(
                graph, table_id=table_id, bindings=(assignment,), tenant_id=tenant_id
            )
        except ValueError as error:
            record["hold_reason"] = str(error)
            record["numeric_usability"] = "not_normalized"
            candidates.append(record)
            continue
        observation = normalized.observations[0]
        observation = replace(
            observation,
            source_refs=tuple(
                verify_source_ref(ref, graph, tenant_id=tenant_id)
                for ref in observation.source_refs
            ),
        )
        holds, detail = _numeric_usability(
            observation, graph, promoted_ids, context, external_context
        )
        if not holds:
            observation = replace(observation, quality="verified")
        observations.append(observation)
        issues.extend(normalized.conflicts)
        record.update(
            normalization_status="normalized",
            observation_id=observation.observation_id,
            value_raw=observation.value_raw,
            metric_raw=observation.metric_raw,
            reporting_period=observation.reporting_period,
            unit_raw=observation.unit_raw,
            unit_canonical=observation.unit_canonical,
            scale_multiplier=observation.scale_multiplier,
            scope=observation.scope,
            subject=observation.subject,
            quality=observation.quality,
            numeric_usability="usable_numeric_source" if not holds else "held",
            numeric_holds=holds,
            **detail,
        )
        candidates.append(record)
    unique = {issue.issue_id: issue for issue in issues}
    return ReviewedNumericInputs(
        graph=graph,
        native_receipt=receipt,
        table_id=table_id,
        cell_source_ids=cell_ids,
        promoted_source_ids=promoted_ids,
        normalization=NormalizationResult(
            tuple(observations), tuple(unique[key] for key in sorted(unique)), graph
        ),
        candidates=tuple(candidates),
        context_receipts=context_receipts,
        external_context=external_context,
    )


def reviewed_table_claim_bridge_status() -> dict[str, Any]:
    """Why a real claim cannot be bound to this grid yet; never a substitute claim.

    A claim must be an actually discovered statement with its own verified source
    provenance. Binding one out of the same table cells that are the evidence would
    compare the table with itself, so no claim is constructed here. Two independent
    blockers remain, both measured on the real pages rather than assumed.
    """
    return {
        "claim_bridge": "unresolved",
        "blockers": [
            # The dimension cells of a reviewed value are never citable, so even a
            # real narrative claim could not be checked against this grid today.
            "reviewed_dimension_cells_unverified:"
            "native_selected_cell_attestation_promotes_the_value_cell_only",
            # The reviewed layout is its own parse, by construction: a different
            # geometry rule must not reuse the frozen run's parse identity.
            "reviewed_parse_manifest_differs_from_the_frozen_run_carrying_discovered_claims",
        ],
    }


def numeric_input_report(inputs: ReviewedNumericInputs, review: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe diagnostic of what the numeric service can read, and what holds."""
    usable = [c for c in inputs.candidates if c.get("numeric_usability") == "usable_numeric_source"]
    blocking: dict[str, int] = {}
    for candidate in inputs.candidates:
        for hold in candidate.get("numeric_holds") or ():
            blocking[hold] = blocking.get(hold, 0) + 1
    report = {
        "schema": _NUMERIC_INPUT_SCHEMA,
        "status": "numeric_service_input_only",
        "eligible_for_admission": False,
        "semantic_verification": "not_run",
        "interpretation": review.get("layout_interpretation"),
        "tenant_id": inputs.graph.tenant_id,
        "source": {
            "source_sha256": review["source_sha256"],
            "physical_page": review["physical_page"],
            "layout_sha256": review["layout_sha256"],
            "document_version_id": inputs.graph.document_version_id,
            "parse_manifest_id": inputs.graph.parse_manifest_id,
        },
        "native_receipt": {
            "schema": inputs.native_receipt["schema"],
            "policy_sha256": inputs.native_receipt["policy_sha256"],
            "artifact_sha256": inputs.native_receipt["artifact_sha256"],
            "promoted_cell_count": len(
                {
                    source_id
                    for record in inputs.native_receipt["records"]
                    for selection in record["selections"]
                    for source_id in selection["promoted_source_ids"]
                }
            ),
        },
        "table_id": inputs.table_id,
        "observation_count": len(inputs.observations),
        "usable_numeric_source_count": len(usable),
        "blocking_holds": dict(sorted(blocking.items())),
        "candidates": [json.loads(json.dumps(c, default=str)) for c in inputs.candidates],
        "normalization_issues": [issue.to_dict() for issue in inputs.normalization.conflicts],
        "numeric_service_call": numeric_service_call(inputs),
        **reviewed_table_claim_bridge_status(),
        "holds": [
            "operator_reviewed_role_assignment_is_not_semantic_approval",
            "reviewed_row_label_and_footnote_context_is_not_bound_by_the_4_role_normalization",
            "native_selected_cell_attestation_promotes_the_value_cell_only",
        ],
    }
    if inputs.context_receipts:
        report["context_cell_receipts"] = list(inputs.context_receipts)
        report["context_cell_verification"] = {
            "verified": sum(
                r["status"] == "verified" for p in inputs.context_receipts for r in p["records"]
            ),
            "held": sum(
                r["status"] != "verified" for p in inputs.context_receipts for r in p["records"]
            ),
            "scope": "literal_text_only",
        }
        report["blockers"][0] = "reviewed_numeric_source_or_context_bindings_remain_unresolved"
        report["holds"][-1] = "context_literals_do_not_approve_semantic_bindings"
    if inputs.external_context:
        # Table-level, not per-candidate: a footnote/coverage passage the review
        # pinned outside the grid can never be bound by the per-candidate
        # notes/row_labels mechanism above, so it is reported once here rather
        # than attributed to any one value. Every candidate already carries its
        # own ``external_context_unbound:<kind>`` hold from ``_numeric_usability``.
        report["unresolved_external_context"] = list(inputs.external_context)
        report["holds"].append(
            "reviewed_external_context_present_and_unbound:"
            + ",".join(sorted({entry["kind"] for entry in inputs.external_context}))
        )
    report["report_sha256"] = canonical_hash(report)
    return report


def numeric_service_call(inputs: ReviewedNumericInputs) -> dict[str, Any]:
    """Invoke the existing numeric service on this grid with no claim and no binding.

    This is a real call into ``application.numeric_analysis``, not a projection of
    one: the reviewed graph and its normalized observations are the inputs the
    service itself validates. ``claims=()`` and ``bindings=()`` because no claim of
    this document is bound to the grid, so the honest result carries no outcome and
    no finding. Supplying a binding here would be manufacturing acceptance.
    """
    from proofops.application.numeric_analysis import analyze_numeric_consistency

    report = analyze_numeric_consistency(
        tenant_id=inputs.graph.tenant_id,
        original=inputs.graph,
        observations=inputs.observations,
        bindings=(),
        claims=(),
    )
    return {
        "invocation": "application.numeric_analysis.analyze_numeric_consistency",
        "claims_supplied": 0,
        "bindings_supplied": 0,
        "observations_supplied": len(inputs.observations),
        "tenant_id": report.tenant_id,
        "document_version_id": report.document_version_id,
        "parse_manifest_id": report.parse_manifest_id,
        "source_sha256": report.source_sha256,
        "outcome_count": len(report.outcomes),
        "has_findings": report.has_findings,
        "interpretation": (
            "no claim of this document is bound to the reviewed grid, so the service "
            "returns no outcome; this is an executed integration, not a finding and "
            "not a grade"
        ),
    }
