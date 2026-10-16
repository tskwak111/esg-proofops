"""CH1: literal chart/image-table labels against trusted original-page OCR.

Extraction proposals have no authority. Every field is located anew in the OCR
of the original PDFium pixels, including proposals without any bounding box.
The artifact proves printed labels, not their semantic binding or a grade fact.
"""

import math
import re
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import source_fxf
from proofops.adapters.local import upstage_ocr_mapping_v2 as mapping
from proofops.adapters.local.source_attestation_errors import ocr_acquisition_failure_code
from proofops.adapters.local.upstage_ocr_page import parse_response, reader_policy
from proofops.domain.provenance import canonical_hash

ROLES = ("value", "unit", "year", "series")
KINDS = {"bar", "line", "pie", "image_table"}
BASES = {"printed", "visual_estimate", "axis_tick"}
NUMBER = re.compile(r"[+−-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:%|％)?")
YEAR = re.compile(r"(?:19|20)\d{2}(?:년)?")
POLICY = dict(
    profile="ch1_printed_chart_labels_v1",
    min_confidence=0.98,
    max_pages=10,
    max_regions=64,
    max_observations=512,
    source="original-PDFium-annotated-pixels; trusted-Upstage-OCR-word-polygons",
    matching="exact-whole-words; unique-or-explicit-word-ids; no-number-repair",
    inference="visual-estimates-and-axis-ticks-display-only; no-height-or-area-derived-values",
    binding="field-proof-is-not-year/series-binding; unknown-until-separate-admission",
    authority="review-candidates-only; fresh-3/3-tagging-and-existing-domain-guards-required",
)


def policy():
    from proofops.application.ingest import ch1_layout

    return POLICY | dict(
        layout_sha256=sha256(Path(ch1_layout.__file__).read_bytes()).hexdigest(),
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        mapping_sha256=sha256(Path(mapping.__file__).read_bytes()).hexdigest(),
        renderer=source_fxf.policy(),
        ocr=reader_policy(),
    )


def _box(value, width, height):
    return (
        isinstance(value, tuple | list)
        and len(value) == 4
        and all(type(v) in (int, float) and math.isfinite(v) for v in value)
        and 0 <= value[0] < value[2] <= width
        and 0 <= value[1] < value[3] <= height
    )


def _union(words):
    return [
        min(w["bbox"][0] for w in words),
        min(w["bbox"][1] for w in words),
        max(w["bbox"][2] for w in words),
        max(w["bbox"][3] for w in words),
    ]


def _inside(inner, outer):
    return outer[0] <= inner[0] < inner[2] <= outer[2] and (
        outer[1] <= inner[1] < inner[3] <= outer[3]
    )


def _words(response, manifest):
    if [response["width"], response["height"]] != manifest["pixel_size"]:
        raise ValueError("CH1_OCR_PIXEL_SIZE_MISMATCH")
    result = []
    for word in response["words"]:
        polygon = [
            [
                x * manifest["width_pt"] / response["width"],
                y * manifest["height_pt"] / response["height"],
            ]
            for x, y in word["polygon"]
        ]
        result.append(word | dict(pdf_polygon=polygon, bbox=mapping._bounds(polygon)))
    return result


def _field(proposal, words, region, role):
    unknown = dict(status="unknown", reason="label_not_supplied", words=[])
    if proposal is None:
        return unknown
    quote = proposal["quote"]
    unknown.update(quote=quote, reason="printed_label_not_found")
    available = [w for w in words if region is None or _inside(w["bbox"], region)]
    ids = proposal.get("word_ids")
    if ids is not None:
        by_id = {w["id"]: w for w in available}
        matches = [[by_id[i] for i in ids]] if all(i in by_id for i in ids) else []
    else:
        # A whole word can contain spaces. Multiword matches are exact and local;
        # provider order is not trusted as page/column reading order.
        matches = [[w] for w in available if w["text"] == quote]
        parts = quote.split(" ")
        if len(parts) > 1:
            for first in available:
                if first["text"] != parts[0]:
                    continue
                seq = [first]
                for part in parts[1:]:
                    prev = seq[-1]["bbox"]
                    neighbors = [
                        w
                        for w in available
                        if w["text"] == part
                        and w["bbox"][0] >= prev[2]
                        and w["bbox"][0] - prev[2] <= 3 * (prev[3] - prev[1])
                        and min(w["bbox"][3], prev[3]) - max(w["bbox"][1], prev[1])
                        >= 0.5 * min(w["bbox"][3] - w["bbox"][1], prev[3] - prev[1])
                    ]
                    if len(neighbors) != 1:
                        break
                    seq.append(neighbors[0])
                if len(seq) == len(parts):
                    matches.append(seq)
    if len(matches) != 1:
        unknown["reason"] = "ambiguous_printed_label" if matches else "printed_label_not_found"
        return unknown
    chosen = matches[0]
    if " ".join(w["text"] for w in chosen) != quote:
        return unknown | dict(reason="word_text_mismatch")
    if any(w["confidence"] < POLICY["min_confidence"] for w in chosen):
        return unknown | dict(reason="ocr_confidence_below_threshold")
    if any(mapping._tilted(w["pdf_polygon"]) for w in chosen):
        return unknown | dict(reason="ocr_word_rotation_ambiguous")
    # A word cannot quietly borrow an overlapping detection, even when the
    # proposal lists a single apparently valid word ID.
    for word in chosen:
        for other in words:
            if other["id"] == word["id"]:
                continue
            overlap = mapping._clipped_area(word["pdf_polygon"], other["bbox"])
            if (
                overlap
                / min(mapping._area(word["pdf_polygon"]), mapping._area(other["pdf_polygon"]))
                > 0.2
            ):
                return unknown | dict(reason="ocr_word_overlap_ambiguous")
    for left, right in zip(chosen, chosen[1:]):
        a, b = left["bbox"], right["bbox"]
        if (
            b[0] < a[2]
            or b[0] - a[2] > 3 * (a[3] - a[1])
            or min(a[3], b[3]) - max(a[1], b[1]) < 0.5 * min(a[3] - a[1], b[3] - b[1])
        ):
            return unknown | dict(reason="disconnected_label_words")
    literal = quote
    if "span" in proposal:
        start, end = proposal["span"]
        if (
            role not in {"unit", "year"}
            or not 0 <= start < end <= len(quote)
            or (
                role == "year"
                and (
                    (start and quote[start - 1].isdigit())
                    or (end < len(quote) and quote[end].isdigit())
                )
            )
        ):
            return unknown | dict(reason="invalid_literal_slice")
        literal = quote[start:end]
    if role == "value" and NUMBER.fullmatch(literal) is None:
        return unknown | dict(reason="not_a_literal_numeric_label")
    if role == "year" and YEAR.fullmatch(literal) is None:
        return unknown | dict(reason="not_an_explicit_year_label")
    return dict(
        status="verified",
        reason=None,
        quote=quote,
        literal=literal,
        bbox=_union(chosen),
        word_ids=[w["id"] for w in chosen],
        words=chosen,
    )


def _validate_request(source, request):
    if not isinstance(source, bytes) or not 0 < len(source) <= 100 * 1024 * 1024:
        raise ValueError("CH1_SOURCE_INVALID")
    if sha256(source).hexdigest() != request.get("source_sha256"):
        raise ValueError("CH1_SOURCE_MISMATCH")
    for key in ("tenant_id", "run_id", "document_version_id", "parse_manifest_id"):
        if not isinstance(request.get(key), str) or not 0 < len(request[key]) <= 200:
            raise ValueError("CH1_IDENTITY_REQUIRED")
    pages = request.get("selected_pages")
    if (
        not isinstance(pages, list)
        or not 1 <= len(pages) <= POLICY["max_pages"]
        or any(type(p) is not int or p < 1 for p in pages)
        or pages != sorted(set(pages))
    ):
        raise ValueError("CH1_SELECTED_PAGES_INVALID")
    regions = request.get("regions")
    if not isinstance(regions, list) or not 0 <= len(regions) <= POLICY["max_regions"]:
        raise ValueError("CH1_REGIONS_INVALID")
    region_ids = set()
    count = 0
    for region in regions:
        if (
            not isinstance(region, dict)
            or not isinstance(region.get("id"), str)
            or not region["id"]
            or region["id"] in region_ids
            or type(region.get("page")) is not int
            or region["page"] not in pages
            or region.get("kind") not in KINDS
        ):
            raise ValueError("CH1_REGION_INVALID")
        region_ids.add(region["id"])
        observations = region.get("observations")
        if not isinstance(observations, list):
            raise ValueError("CH1_OBSERVATIONS_INVALID")
        count += len(observations)
        seen = set()
        for item in observations:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("id"), str)
                or not item["id"]
                or item["id"] in seen
                or item.get("basis") not in BASES
            ):
                raise ValueError("CH1_OBSERVATION_INVALID")
            seen.add(item["id"])
            for role in ROLES:
                field = item.get(role)
                if field is None:
                    continue
                if (
                    not isinstance(field, dict)
                    or not isinstance(field.get("quote"), str)
                    or not 0 < len(field["quote"]) <= 300
                    or "\n" in field["quote"]
                ):
                    raise ValueError("CH1_FIELD_INVALID")
                ids = field.get("word_ids")
                if ids is not None and (
                    not isinstance(ids, list)
                    or not 1 <= len(ids) <= 30
                    or any(type(i) is not int or i < 0 for i in ids)
                    or len(set(ids)) != len(ids)
                ):
                    raise ValueError("CH1_WORD_IDS_INVALID")
                span = field.get("span")
                if span is not None and (
                    not isinstance(span, list)
                    or len(span) != 2
                    or any(type(i) is not int for i in span)
                ):
                    raise ValueError("CH1_LITERAL_SLICE_INVALID")
    if count > POLICY["max_observations"]:
        raise ValueError("CH1_OBSERVATION_LIMIT")


def recover(source, request, *, store, saved_pages=None):
    """New immutable extraction, or strict recomputation with no acquisition.

    The caller must resolve tenant/document authorization before this local adapter,
    as for FXF. Request identity and selected-page scope are bound into the receipt.
    """
    _validate_request(source, request)
    retained = {p["physical_page"]: p for p in saved_pages} if saved_pages is not None else None
    needed = sorted({r["page"] for r in request["regions"]})
    if retained is not None and (len(retained) != len(saved_pages) or sorted(retained) != needed):
        raise ValueError("CH1_REPLAY_PAGE_SET_MISMATCH")
    reads, words = [], {}
    for page in needed:
        image = source_fxf.render_page(source, page)
        item = dict(physical_page=page, manifest=image["manifest"])
        if retained is not None:
            prior = retained[page]
            if prior.get("manifest") != image["manifest"]:
                raise ValueError("CH1_REPLAY_PAGE_MISMATCH")
            if "collection" in prior:
                item["collection"] = store.validate(
                    prior["collection"], image, tenant_id=request["tenant_id"]
                )
            elif prior.get("failure") == "OCR_REPLAY_PAGE_MISSING" or (
                ocr_acquisition_failure_code(ValueError(prior.get("failure"))) is not None
            ):
                item["failure"] = prior["failure"]
            else:
                raise ValueError("CH1_REPLAY_PAGE_INVALID")
        else:
            try:
                collection = store.fetch(
                    image, tenant_id=request["tenant_id"], run_id=request["run_id"]
                )
                item["collection"] = store.validate(
                    collection, image, tenant_id=request["tenant_id"]
                )
            except ValueError as error:
                code = ocr_acquisition_failure_code(error)
                if code is None and str(error) != "OCR_REPLAY_PAGE_MISSING":
                    raise
                item["failure"] = code or "OCR_REPLAY_PAGE_MISSING"
        if "collection" in item:
            words[page] = _words(
                parse_response(bytes.fromhex(item["collection"]["response_hex"])), image["manifest"]
            )
        reads.append(item)
    by_page = {r["physical_page"]: r for r in reads}
    regions = []
    for region in request["regions"]:
        page = region["page"]
        manifest = by_page[page]["manifest"]
        bounds = region.get("bbox")
        if bounds is not None and not _box(bounds, manifest["width_pt"], manifest["height_pt"]):
            raise ValueError("CH1_REGION_GEOMETRY_INVALID")
        items = []
        for proposal in region["observations"]:
            fields = {
                role: _field(proposal.get(role), words.get(page, []), bounds, role)
                for role in ROLES
            }
            if proposal["basis"] != "printed":
                fields["value"] = dict(
                    status="unknown",
                    reason="not_a_printed_data_label",
                    quote=(proposal.get("value") or {}).get("quote"),
                    words=[],
                )
            proved = [f for f in fields.values() if f["status"] == "verified"]
            complete = all(fields[r]["status"] == "verified" for r in ROLES)
            # Coordinates support review of a proposed association, never prove
            # legend colours, chart ownership, period meaning or company scope.
            items.append(
                dict(
                    id=proposal["id"],
                    basis=proposal["basis"],
                    fields=fields,
                    status="verified" if complete else "unknown",
                    verification_scope="printed_labels_only",
                    binding_status="unknown",
                    eligible_for_scoring=False,
                    bbox=_union([w for f in proved for w in f["words"]]) if proved else None,
                    page_read_sha256=canonical_hash(by_page[page]),
                )
            )
        regions.append(
            dict(
                id=region["id"],
                page=page,
                kind=region["kind"],
                requested_bbox=bounds,
                observations=items,
            )
        )
    body = dict(
        schema="ch1_chart_recovery_v1",
        policy=policy(),
        request=request,
        request_sha256=canonical_hash(request),
        page_reads=reads,
        regions=regions,
    )
    return body | dict(artifact_sha256=canonical_hash(body))


def replay(receipt, source, request, *, store):
    if receipt.get("policy") != policy() or receipt.get("request") != request:
        raise ValueError("CH1_POLICY_OR_SCOPE_MISMATCH")
    expected = recover(source, request, store=store, saved_pages=receipt["page_reads"])
    if canonical_hash(receipt) != canonical_hash(expected):
        raise ValueError("CH1_RECEIPT_MISMATCH")
    return expected


def extract(source, scope, layouts, *, store, policy_sha256, saved_pages=None):
    """Opt-in deterministic extraction from OCR, then source re-verification.

    This does not add fabricated strings or coordinates to the canonical graph.
    The returned labels are a separate, immutable review artifact.
    """
    from proofops.application.ingest.ch1_layout import propose

    if policy_sha256 != canonical_hash(policy()):
        raise ValueError("CH1_POLICY_PIN_MISMATCH")
    if not isinstance(layouts, list) or len(layouts) > POLICY["max_regions"]:
        raise ValueError("CH1_REGIONS_INVALID")
    seeds = [
        dict(id=r["id"], page=r["page"], kind=r["kind"], bbox=r.get("bbox"), observations=[])
        for r in layouts
    ]
    acquisition = recover(source, scope | dict(regions=seeds), store=store, saved_pages=saved_pages)
    reads = {p["physical_page"]: p for p in acquisition["page_reads"]}
    proposals, diagnostics = [], []
    for layout in layouts:
        page = reads[layout["page"]]
        if "collection" not in page:
            proposals.append(next(r for r in seeds if r["id"] == layout["id"]))
            diagnostics.append(dict(id=layout["id"], status="unknown", reason=page["failure"]))
            continue
        words = _words(
            parse_response(bytes.fromhex(page["collection"]["response_hex"])), page["manifest"]
        )
        proposal = propose(
            layout, words, [page["manifest"]["width_pt"], page["manifest"]["height_pt"]]
        )
        proposals.append(proposal)
        diagnostics.append(
            dict(
                id=layout["id"],
                status="candidates" if proposal["observations"] else "unknown",
                reason=proposal.get("reason"),
            )
        )
    request = scope | dict(regions=proposals, ch1_layouts=layouts, ch1_diagnostics=diagnostics)
    return recover(source, request, store=store, saved_pages=acquisition["page_reads"])
