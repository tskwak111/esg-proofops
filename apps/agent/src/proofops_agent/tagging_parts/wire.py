"""Element request rendering and response restoration without transport state."""

import json
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from proofops.application.tagging.contracts import TaggingSettings
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json
from proofops.domain.values import _require_uuid, _source_ref_from_dict

from proofops_agent.extraction_parts.contracts import DisplayCatalog, RequestBody, RestoreReference
from proofops_agent.upstage_extraction import UpstageClaimExtractor

MODEL_PROFILE = "upstage-compact-ids-frozen-unicode-v1"
COVERAGE_PROFILE = "upstage-compact-coverage-unicode-v2"
QUOTE_PROFILE = "upstage-compact-source-quotes-v3"
QUOTE_V4_PROFILE = "upstage-compact-source-quotes-v4"
QUOTE_V5_PROFILE = "upstage-compact-source-quotes-v5"
CONSISTENCY_PROFILE = "upstage-compact-element-consistency-v6"


def build_wire_request(
    request: dict[str, Any],
    settings: TaggingSettings,
    *,
    display_catalog: DisplayCatalog | None,
    request_body: RequestBody,
) -> tuple[str, str, dict[str, dict[str, Any]], str]:
    from proofops.application.tagging.finals_i4 import K4_ELEMENTS, elements_k4

    system = request["system_prompt"]
    prefix = settings.rendered_system + "\nValidated classification; tag only its elements: "
    if not isinstance(system, str) or not system.startswith(prefix):
        raise ValueError("UPSTAGE_TAGGING_CLASSIFICATION_REQUIRED")
    classification = json.loads(system[len(prefix) :])
    if (
        not isinstance(classification, dict)
        or set(classification) != {"track", "safe_harbor_category"}
        or classification["track"] not in ("goal", "performance", "management")
        or classification["safe_harbor_category"]
        not in (None, "forward_looking", "emissions_estimate", "third_party_information")
    ):
        raise ValueError("UPSTAGE_TAGGING_CLASSIFICATION_INVALID")
    user = json.loads(request["user_json"])
    if (
        not isinstance(user, dict)
        or any(user.get(k) != request[k] for k in ("claim_id", "packet_sha256", "replicate_id"))
        or not isinstance(user.get("untrusted_document_data"), dict)
    ):
        raise ValueError("UPSTAGE_TAGGING_PACKET_MISMATCH")
    if settings.model_profile in (
        COVERAGE_PROFILE,
        QUOTE_PROFILE,
        QUOTE_V4_PROFILE,
        QUOTE_V5_PROFILE,
        CONSISTENCY_PROFILE,
    ):
        data = user["untrusted_document_data"]
        coverage = data.get("search_coverage", {})
        if (
            not isinstance(coverage, dict)
            or coverage.get("not_found_state", "unknown") != "unknown"
        ):
            raise ValueError("UPSTAGE_TAGGING_COVERAGE_INVALID")
        summary: dict[str, str | int] = {"not_found_state": "unknown"}
        for prefix in ("omitted", "unprocessed"):
            ids = coverage.get(f"{prefix}_source_ids", [])
            if not isinstance(ids, list):
                raise ValueError("UPSTAGE_TAGGING_COVERAGE_INVALID")
            for identifier in ids:
                _require_uuid("coverage source_id", identifier)
            summary[f"{prefix}_source_count"] = len(ids)
            summary[f"{prefix}_source_ids_sha256"] = canonical_hash(ids)
        data["search_coverage"] = summary
    data = user["untrusted_document_data"]
    display = data.pop("display_text", None)
    catalog = display_catalog
    if catalog is not None:
        if settings.model_profile not in (
            QUOTE_PROFILE,
            QUOTE_V4_PROFILE,
            QUOTE_V5_PROFILE,
            CONSISTENCY_PROFILE,
        ):
            raise ValueError("DISPLAY_QUOTE_PROFILE_REQUIRED")
        if display != catalog.element_pins(data):
            raise ValueError("DISPLAY_PACKET_MISMATCH")
        replacements = {
            r["quote"]: catalog.pin(r)["text"]
            for r in [
                *data["claim_source_refs"],
                *(r for c in data["evidence_candidates"] for r in c["source_refs"]),
            ]
        }

        data["atomic_quote"] = replacements.get(data["atomic_quote"], data["atomic_quote"])
        data["display_policy"] = display["policy"]
        data["display_map_sha256"] = canonical_hash(display)
    elif display is not None:
        raise ValueError("DISPLAY_PROFILE_REQUIRED")
    if (
        settings.model_profile in (QUOTE_V5_PROFILE, CONSISTENCY_PROFILE)
        and "claim_source_refs" in data
    ):
        data["claim_source_refs"] = [
            {
                "quote": catalog.pin(asdict(ref))["text"] if catalog else ref.quote,
                "page_num": ref.page_num,
            }
            for ref in (_source_ref_from_dict(raw) for raw in data["claim_source_refs"])
        ]
    if catalog and settings.model_profile not in (QUOTE_V5_PROFILE, CONSISTENCY_PROFILE):
        data["claim_source_refs"] = [
            raw | {"quote": catalog.pin(raw)["text"]} for raw in data["claim_source_refs"]
        ]
    if settings.model_profile == CONSISTENCY_PROFILE:
        # IDs depend on original source position, never retrieval rank or replica.
        for candidate in data.get("evidence_candidates", []):
            candidate["source_refs"].sort(
                key=lambda ref: (
                    ref["page_num"],
                    ref["source_id"],
                    ref["char_start"],
                    ref["char_end"],
                    ref["quote"],
                )
            )
        data["evidence_candidates"].sort(
            key=lambda candidate: canonical_json(candidate["source_refs"])
        )
    refs: dict[str, dict[str, Any]] = {}
    for candidate in data.get("evidence_candidates", []):
        if settings.model_profile in (QUOTE_V5_PROFILE, CONSISTENCY_PROFILE):
            candidate.pop("source_id", None)
        identifiers = []
        for raw_ref in candidate.get("source_refs", []):
            ref = asdict(_source_ref_from_dict(raw_ref))
            identifier = f"e{len(refs)}"
            if catalog:
                ref["_display"] = catalog.pin(ref)
            refs[identifier] = ref
            identifiers.append(identifier)
        candidate["source_refs"] = identifiers
    catalog_fields = (
        ("quote", "page_num")
        if settings.model_profile in (QUOTE_V5_PROFILE, CONSISTENCY_PROFILE)
        else ("quote", "page_num", "verification_state")
    )
    data["evidence_catalog"] = {
        key: {
            field: (
                ref["_display"]["text"] if field == "quote" and "_display" in ref else ref[field]
            )
            for field in catalog_fields
        }
        for key, ref in refs.items()
    }
    table = data.pop("table_observation_evidence", None)
    if "tb1_table_bundles" in data:
        from proofops.application.tagging.tb1_table_bundles import bundle_refs

        def tb1_id(source: dict[str, Any]) -> str:
            matches = [
                key
                for key, ref in refs.items()
                if all(
                    ref.get(k) == source[k]
                    for k in ("source_id", "char_start", "char_end", "quote")
                )
            ]
            if not matches:
                raise ValueError("TB1_EVIDENCE_CATALOG_MISMATCH")
            return matches[0]

        data["tb1_table_bundles"] = [
            {
                **{
                    k: item[k]
                    for k in ("row_number", "column_number", "year", "period_role", "focal")
                },
                **{k + "_id": tb1_id(item[k]) for k in ("value", "unit", "period")},
                **{
                    k + "_ids": [tb1_id(r) for r in item[k]]
                    for k in ("row_labels", "column_headers", "notes")
                },
                "required_ids": [tb1_id(r) for r in bundle_refs(item)],
            }
            for item in data["tb1_table_bundles"]
        ]
        if data["tb1_table_bundles"] and "qt1_table_tuples" in data:
            data["qt1_table_tuples"] = []
    for field in ("qt1_table_tuples", "qt1_baseline_links"):
        if field not in data:
            continue
        compact = []
        for item in data.pop(field):
            value = {}
            for role in ("value", "unit", "period"):
                source = item[role]
                matches = [
                    key
                    for key, ref in refs.items()
                    if all(
                        ref.get(k) == source[k]
                        for k in ("source_id", "char_start", "char_end", "quote")
                    )
                ]
                if not matches:
                    raise ValueError("QT1_EVIDENCE_CATALOG_MISMATCH")
                value[role + "_id"] = matches[0]
            value.update(
                {k: item[k] for k in ("year", "period_role", "meaning", "elements") if k in item}
            )
            compact.append(value)
        data[field] = compact
    if table is not None:

        def cell_id(source: dict[str, Any]) -> str:
            matches = [
                key
                for key, ref in refs.items()
                if all(
                    ref.get(k) == source[k]
                    for k in ("source_id", "char_start", "char_end", "quote")
                )
            ]
            if not matches:
                raise ValueError("TABLE_EVIDENCE_CATALOG_MISMATCH")
            return matches[0]

        data["table_observation"] = dict(
            current_value_id=cell_id(table["value"]),
            unit_id=cell_id(table["unit"]),
            current_year_id=cell_id(table["year"]),
            comparisons=[
                dict(value_id=cell_id(c["value"]), year_id=cell_id(c["year"]))
                for c in table["comparisons"]
            ],
        )
    if settings.model_profile == CONSISTENCY_PROFILE:
        data["element_evidence_ids"] = {
            element: [
                identifier
                for candidate in data["evidence_candidates"]
                if element in candidate["allowed_elements"]
                for identifier in candidate["source_refs"]
            ]
            for element in data["allowed_elements"]
        }
    schema = json.loads(settings.schema_json)
    schema["$defs"]["SourceRef"] = {"type": "string", "pattern": "^e[0-9]+$"}
    if settings.model_profile in (
        QUOTE_PROFILE,
        QUOTE_V4_PROFILE,
        QUOTE_V5_PROFILE,
        CONSISTENCY_PROFILE,
    ):
        schema["$defs"]["SourceRef"] = {
            "type": "object",
            "required": ["id", "quote"],
            "additionalProperties": False,
            "properties": {
                "id": {"type": "string", "enum": list(refs)},
                "quote": {"type": "string", "minLength": 1},
            },
        }
    allowed = user["untrusted_document_data"].get("allowed_elements")
    if (
        not isinstance(allowed, list)
        or not allowed
        or any(not isinstance(element, str) for element in allowed)
        or len(set(allowed)) != len(allowed)
    ):
        raise ValueError("UPSTAGE_TAGGING_ELEMENTS_REQUIRED")
    schema["properties"]["track"] = {"const": classification["track"]}
    schema["properties"]["safe_harbor_category"] = {"const": classification["safe_harbor_category"]}
    schema["$defs"]["Element"]["properties"]["element_id"] = {"enum": allowed}
    schema["properties"]["elements"].update(minItems=len(allowed), maxItems=len(allowed))
    response_policy = data.get("tagging_response_policy")
    if response_policy is not None:
        from proofops.application.tagging.k4_contract import RESPONSE_POLICY

        if response_policy != RESPONSE_POLICY:
            raise ValueError("K4_RESPONSE_POLICY_MISMATCH")
        for field in ("claim_id", "packet_sha256", "replicate_id"):
            schema["properties"].pop(field)
            schema["required"].remove(field)
    instructions = (
        "\nTransport contract compact-evidence-ids-v1: evidence_refs contains only "
        "evidence_catalog IDs such as e0. Select IDs; never repeat or alter source text, "
        "coordinates, offsets or verification state. The server restores those exactly."
    )
    if table is not None:
        instructions += (
            "\nThe table_observation links literal attested cells of this exact row. "
            "For P1 evaluate the current value with its unit; select both source IDs "
            "and use the exact current value quote as normalized_value. For P2 evaluate "
            "the comparison value with its explicit year header in this same table; "
            "select both quotes if sufficient. These links are candidate sources, "
            "not element votes. Preserve unknown when the element is not stated."
        )
    if settings.model_profile in (
        QUOTE_PROFILE,
        QUOTE_V4_PROFILE,
        QUOTE_V5_PROFILE,
        CONSISTENCY_PROFILE,
    ):
        instructions = (
            "\nTransport contract compact-source-quotes-v3: each evidence_refs item is "
            '{"id":"e0","quote":"exact source substring"}. Select an evidence_catalog '
            "ID and a non-empty exact quote occurring only once within that catalog quote. "
            "Include enough context to disambiguate repeated text. Never supply offsets, "
            "coordinates or verification state; the server restores provenance. "
            "A non-null normalized_value must equal one selected quote (NFC/whitespace "
            "normalization only), never a paraphrase or summary. Use a precise value quote "
            "for numerical elements and additional context quotes as needed; qualitative "
            "elements may use null normalized_value while retaining literal evidence. "
            "Exact quotation does not establish claim attribution or semantic sufficiency."
        )
    if settings.model_profile == CONSISTENCY_PROFILE or (
        data.get("pipeline_profile") == "finals-unattended-v2"
    ):
        # Scope only trusted rule cards. Keep all guards, examples and evidence.
        marker = "This rule reference is tagging guidance, not an approval of the draft rulepack.\n"
        if marker in system and settings.system_prompt != K4_ELEMENTS:
            head, tail = system.split(marker, 1)
            reference, end = json.JSONDecoder().raw_decode(tail)
            cards = [e for e in reference["elements"] if e["id"] in allowed]
            if {e["id"] for e in cards} != set(allowed):
                raise ValueError("UPSTAGE_TAGGING_ELEMENTS_REQUIRED")
            reference["elements"] = cards
            system = (
                head
                + marker
                + json.dumps(reference, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + tail[end:]
            )
    wire_system = system.replace(settings.schema_json, canonical_json(schema), 1) + instructions
    if settings.model_profile in (
        COVERAGE_PROFILE,
        QUOTE_PROFILE,
        QUOTE_V4_PROFILE,
        QUOTE_V5_PROFILE,
        CONSISTENCY_PROFILE,
    ):
        wire_system += (
            "\nCoverage v2: omitted/unprocessed source counts and list hashes summarize "
            "unseen identifiers retained by the server. Missing evidence remains unknown; "
            "neither a count nor a hash is evidence or proof of absence."
        )
    if settings.model_profile == CONSISTENCY_PROFILE:
        wire_system += (
            "\nConsistency v6: Evaluate each requested definition independently using "
            "only its element_evidence_ids. These lists route evidence, never certify "
            "sufficiency. Read source_scope: local_claim is preferred when sufficient; "
            "other sources require explicit same entity, metric, period and boundary. "
            "Missing attribution remains unknown even if a nearby sentence sounds relevant. "
            "For present select a non-empty literal quote that directly states the element, "
            "including its subject/action context; do not infer from generic intentions. "
            "Choose the earliest sufficient catalog ID and the shortest unambiguous quote "
            "retaining that context; add another citation only if required for sufficiency. "
            "M1 needs a named means or standard; generic improvement alone is insufficient. "
            "M2 needs a concrete operating process; intentions alone are insufficient. "
            "M4 needs concrete implementation results; generic aspirations are insufficient. "
            "M5 needs a responsible organization or governance arrangement; compensation "
            "alone does not establish governance. M6 needs an explicit compensation link. "
            "M3 needs external verification, never infer it from a framework name. "
            "If no sufficient quote exists use unknown with [] and null value; never absent. "
            "Unknown is not absence. Keep qualitative normalized_value null. "
            "Numerical values require their own exact quote as already specified. "
            "Source, binding and numeric validation remain mandatory on the server; "
            "only three independent unanimous guarded votes can be confirmed."
        )
    if catalog:
        from proofops.application.ingest.display_text import SYSTEM_SUFFIX

        wire_system += SYSTEM_SUFFIX
    from proofops.application.tagging.k7_wire import POLICY_K10
    from proofops.application.tagging.k11_contract import WIRE_POLICY as K11_WIRE_POLICY
    from proofops.application.tagging.k11_contract import WIRE_V1_POLICY as K11_WIRE_V1_POLICY

    k11 = data.get("tagging_wire_policy") in (K11_WIRE_V1_POLICY, K11_WIRE_POLICY)
    k10 = data.get("tagging_wire_policy") == POLICY_K10 or k11
    k9 = data.get("local_implementation_binding_policy") is not None
    if k9:
        from proofops.application.tagging.k9_contract import (
            BINDING_POLICY,
            BINDING_V1_POLICY,
            BINDING_V2_POLICY,
            BINDING_V3_POLICY,
            BINDING_V4_POLICY,
            ELEMENT_GUIDANCE,
        )

        k9_binding = data.pop("local_implementation_binding_policy")
        if k9_binding not in (
            BINDING_V1_POLICY,
            BINDING_V2_POLICY,
            BINDING_V3_POLICY,
            BINDING_V4_POLICY,
            BINDING_POLICY,
        ):
            raise ValueError("K9_BINDING_POLICY_MISMATCH")
        wire_system += ELEMENT_GUIDANCE
    quality_policy = data.get("structural_quality_policy")
    if settings.system_prompt == K4_ELEMENTS:
        if response_policy is None:
            raise ValueError("I4_RESPONSE_POLICY_REQUIRED")
        if k10:
            from proofops.application.tagging.k10_contract import elements

            if k11:
                from proofops.application.tagging.k11_contract import elements as k11_elements

                # External package helper is untyped; its annotations are outside this scope.
                wire_system = k11_elements(  # type: ignore[no-untyped-call]
                    schema,
                    classification,
                    policy=data["tagging_wire_policy"],
                    quality_policy=quality_policy,
                )
            else:
                # External package helper is untyped; its annotations are outside this scope.
                wire_system = elements(schema, classification, quality_policy=quality_policy)  # type: ignore[no-untyped-call]
        else:
            # External package helper is untyped; its annotations are outside this scope.
            wire_system = elements_k4(schema, classification, quality_policy=quality_policy)  # type: ignore[no-untyped-call]
        if k9 and not k10:
            from proofops.application.tagging.k9_contract import element_guidance_for

            # External package helper is untyped; its annotations are outside this scope.
            wire_system += element_guidance_for(k9_binding, data.get("atomic_quote", ""))  # type: ignore[no-untyped-call]
        # Authorization above covered these server policies before projection.
        data.pop("tagging_response_policy", None)
        data.pop("selected_quantity_policy", None)
    if "structural_quality_policy" in data:
        from proofops.application.tagging.q1_contract import (
            element_guidance,
            validate_policy,
        )

        # External package helper is untyped; its annotations are outside this scope.
        validate_policy(data.pop("structural_quality_policy"))  # type: ignore[no-untyped-call]
        # External package helper is untyped; its annotations are outside this scope.
        wire_system += element_guidance(data.get("atomic_quote", ""))  # type: ignore[no-untyped-call]
    if "v3_dec92_policy" in data:
        from proofops.application.tagging.v3_dec92 import ELEMENT_GUIDANCE, validate_policy

        # External package helper is untyped; its annotations are outside this scope.
        validate_policy(data.pop("v3_dec92_policy"))  # type: ignore[no-untyped-call]
        wire_system += "\n" + ELEMENT_GUIDANCE
    if "qt2_contextual_elements_policy" in data:
        from proofops.application.tagging.qt2_context import GUIDANCE, validate_policy

        # External package helper is untyped; its annotations are outside this scope.
        validate_policy(data.pop("qt2_contextual_elements_policy"))  # type: ignore[no-untyped-call]
        wire_system += "\n" + GUIDANCE
    POLICY: dict[str, Any]
    if "qt1_tuple_policy" in data:
        from proofops.application.tagging.qt1_tuples import GUIDANCE, POLICY

        if data.pop("qt1_tuple_policy") != POLICY:
            raise ValueError("QT1_TUPLE_POLICY_MISMATCH")
        if not data.get("tb1_table_bundles"):
            wire_system += "\n" + GUIDANCE
    if "qt1_baseline_policy" in data:
        from proofops.application.tagging.qt1_baseline import GUIDANCE, POLICY

        if data.pop("qt1_baseline_policy") != POLICY:
            raise ValueError("QT1_BASELINE_POLICY_MISMATCH")
        wire_system += "\n" + GUIDANCE
    if "tb1_table_policy" in data:
        from proofops.application.tagging.tb1_table_bundles import GUIDANCE, POLICY

        if data.pop("tb1_table_policy") != POLICY:
            raise ValueError("TB1_TABLE_POLICY_MISMATCH")
        wire_system += "\n" + GUIDANCE
    if "tagging_wire_policy" in data:
        from proofops.application.tagging.k7_wire import (
            INSTRUCTIONS,
            MANAGEMENT_GUIDANCE,
            MANAGEMENT_GUIDANCE_V2,
            NAMED_MEANS_GUIDANCE,
            POLICY,
            POLICY_K8,
            POLICY_K8_V2,
            POLICY_K8_V3,
            POLICY_K10,
            POLICY_V1,
            fit_context,
        )

        if data["tagging_wire_policy"] not in (
            POLICY,
            POLICY_V1,
            POLICY_K8,
            POLICY_K8_V2,
            POLICY_K8_V3,
            POLICY_K10,
            K11_WIRE_POLICY,
            K11_WIRE_V1_POLICY,
        ):
            raise ValueError("K7_WIRE_POLICY_MISMATCH")
        if data["tagging_wire_policy"] == POLICY_K8 and classification["track"] == "management":
            wire_system += MANAGEMENT_GUIDANCE
        if (
            data["tagging_wire_policy"] in (POLICY_K8_V2, POLICY_K8_V3)
            and classification["track"] == "management"
        ):
            wire_system += MANAGEMENT_GUIDANCE_V2
        if (
            data["tagging_wire_policy"] == POLICY_K8_V3
            and classification["track"] == "management"
            and "단열" in data.get("atomic_quote", "")
        ):
            wire_system += NAMED_MEANS_GUIDANCE
        wire_system += INSTRUCTIONS
        # External package helper is untyped; its annotations are outside this scope.
        wire_user = fit_context(  # type: ignore[no-untyped-call]
            wire_system,
            user,
            lambda system, value: request_body(
                system,
                value,
                request_id=request["request_id"],
                max_tokens=request["max_tokens"],
                json_mode=True,
            ),
        )
        return wire_system, wire_user, refs, canonical_json(schema)
    wire_user = json.dumps(user, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return wire_system, wire_user, refs, canonical_json(schema)


def restore_ref(
    selection: Any,
    refs: dict[str, dict[str, Any]],
    *,
    model_profile: str,
    display_catalog: DisplayCatalog | None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if model_profile not in (
        QUOTE_PROFILE,
        QUOTE_V4_PROFILE,
        QUOTE_V5_PROFILE,
        CONSISTENCY_PROFILE,
    ):
        return refs[selection]
    if not isinstance(selection, dict) or set(selection) != {"id", "quote"}:
        raise ValueError("invalid source quote selection")
    quote = selection["quote"]
    if not isinstance(quote, str) or not quote.strip():
        raise ValueError("non-empty source quote required")
    original = refs[selection["id"]]
    if "_display" in original:
        catalog = display_catalog
        raw = {k: v for k, v in original.items() if k != "_display"}
        if catalog is None or catalog.pin(raw) != original["_display"]:
            raise ValueError("DISPLAY_MAP_MISMATCH")
        if policy is None:
            return catalog.restore(quote, raw, original["_display"])
        return catalog.restore(quote, raw, original["_display"], policy=policy)
    if display_catalog is not None:
        raise ValueError("DISPLAY_MAP_REQUIRED")
    if policy is not None:
        from proofops.application.tagging.citation_restore import POLICY, restore_whitespace
        from proofops.application.tagging.k6_citations import POLICY as K6_POLICY
        from proofops.application.tagging.pb2_citation_restore import POLICY as TABLE_POLICY
        from proofops.application.tagging.pb2_citation_restore import restore_table
        from proofops.application.tagging.pb6_citation_restore import POLICY as VALUE_POLICY

        if policy not in (POLICY, TABLE_POLICY, VALUE_POLICY, K6_POLICY):
            raise ValueError("CITATION_RESTORE_POLICY_UNKNOWN")
        restore: Callable[[str, dict[str, Any]], dict[str, Any]] = (
            restore_table
            if policy in (TABLE_POLICY, VALUE_POLICY, K6_POLICY)
            else restore_whitespace
        )
        return restore(quote, original)
    span = UpstageClaimExtractor._locate(quote, original["quote"])
    return original | dict(
        quote=quote,
        char_start=original["char_start"] + span["char_start"],
        char_end=original["char_start"] + span["char_end"],
    )


def restore_payload(
    payload: dict[str, Any],
    refs: dict[str, Any],
    *,
    model_profile: str,
    display_catalog: DisplayCatalog | None,
    restore_ref: RestoreReference,
    refine_year: Callable[[dict[str, Any]], None],
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if policy is not None:
        from proofops.application.tagging.citation_restore import POLICY
        from proofops.application.tagging.k6_citations import POLICY as K6_POLICY
        from proofops.application.tagging.pb2_citation_restore import POLICY as TABLE_POLICY
        from proofops.application.tagging.pb6_citation_restore import POLICY as VALUE_POLICY

        if policy not in (POLICY, TABLE_POLICY, VALUE_POLICY, K6_POLICY):
            raise ValueError("CITATION_RESTORE_POLICY_UNKNOWN")
    for element in payload.get("elements", []):
        try:
            selected = element["evidence_refs"]
            if not isinstance(selected, list):
                raise ValueError("invalid references")
            if policy is not None and policy == K6_POLICY:
                from proofops.application.tagging.k6_citations import anchor_units

                # External package helper is untyped; its annotations are outside this scope.
                selected = anchor_units(selected, refs)  # type: ignore[no-untyped-call]
            element["evidence_refs"] = [restore_ref(key, refs, policy=policy) for key in selected]
            if display_catalog is not None:
                value = element.get("normalized_value")
                exact = [
                    ref["quote"]
                    for choice, ref in zip(selected, element["evidence_refs"], strict=True)
                    if choice["quote"] == value
                ]
                if exact and len(set(exact)) == 1:
                    element["normalized_value"] = exact[0]
            if model_profile in (
                QUOTE_V4_PROFILE,
                QUOTE_V5_PROFILE,
                CONSISTENCY_PROFILE,
            ):
                refine_year(element)
            if policy is not None and policy in (VALUE_POLICY, K6_POLICY):
                from proofops.application.tagging.pb6_citation_restore import (
                    refine_selected_value,
                )

                # External package helper is untyped; its annotations are outside this scope.
                refine_selected_value(element)  # type: ignore[no-untyped-call]
        except (ValueError, KeyError, TypeError, AttributeError):
            if policy is None:
                raise
            element.update(
                state="unknown",
                evidence_refs=[],
                normalized_value=None,
                credited_from=None,
                reason_code="CITATION_RESTORE_UNRESOLVED",
            )
            payload.setdefault("warnings", []).append(
                "CITATION_RESTORE_UNRESOLVED:" + element["element_id"]
            )
    return payload


def refine_g1_year(element: dict[str, Any]) -> None:
    """Add a unique literal year only inside an already selected citation."""
    if element.get("element_id") != "G1" or element.get("state") != "present":
        return
    norm_val = element.get("normalized_value")
    if (
        not isinstance(norm_val, str)
        or len(norm_val) != 5
        or not norm_val.endswith("년")
        or not all("0" <= ch <= "9" for ch in norm_val[:4])
        or norm_val[0] == "0"
    ):
        return
    refs = element.get("evidence_refs")
    if not isinstance(refs, list):
        return
    if any(r.get("quote") == norm_val for r in refs):
        return
    candidates = []
    for r in refs:
        orig = r.get("quote", "")
        if orig.count(norm_val) > 1:
            return
        try:
            span = UpstageClaimExtractor._locate(norm_val, orig)
            if span["char_start"] > 0 and orig[span["char_start"] - 1].isdigit():
                continue
            new_ref = r.copy()
            new_ref["quote"] = norm_val
            new_ref["char_start"] = r["char_start"] + span["char_start"]
            new_ref["char_end"] = r["char_start"] + span["char_end"]
            candidates.append(new_ref)
        except ValueError:
            pass
    unique = []
    for c in candidates:
        if c not in unique:
            unique.append(c)
    if len(unique) == 1:
        refs.append(unique[0])
