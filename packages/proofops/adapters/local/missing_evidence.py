"""Reuse local graph/search and immutable job artifacts; no model/OCR calls."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO

from proofops.adapters.local.evidence_search import LocalEvidenceSearch
from proofops.application.evidence.binding import accept_binding, relation_tags_for
from proofops.application.evidence.element_queries import READABILITY_POLICY
from proofops.application.evidence.missing import SEARCH_PROFILE_HASH, literal_hits, search_elements
from proofops.application.evidence.report_level import POLICIES, check_report_level
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json
from proofops.domain.values import SourceRef


def image_area_ratios(page) -> list[float]:
    """Rendered image area upper bounds from native operators; no pixels/OCR.

    Track determinant through q/Q/cm and nested Form matrices. Clipping is not
    inferred: area is a conservative bound, recorded rather than image resolution.
    """
    from pypdf.generic import ContentStream

    area = float(page.cropbox.width) * float(page.cropbox.height)
    ratios = []

    def determinant(matrix):
        return abs(float(matrix[0]) * float(matrix[3]) - float(matrix[1]) * float(matrix[2]))

    def walk(stream, resources, scale, depth):
        if depth > READABILITY_POLICY["image_geometry_max_depth"]:
            raise ValueError("image geometry nesting limit")
        if stream is None:
            return
        resources = resources.get_object() if hasattr(resources, "get_object") else resources
        parsed = stream if isinstance(stream, ContentStream) else ContentStream(stream, page.pdf)
        stack = []
        for args, operator in parsed.operations:
            if operator == b"q":
                stack.append(scale)
            elif operator == b"Q":
                if not stack:
                    raise ValueError("image geometry graphics stack")
                scale = stack.pop()
            elif operator == b"cm":
                scale *= determinant(args)
            elif operator == b"INLINE IMAGE":
                ratios.append(min(1.0, scale / area))
            elif operator == b"Do":
                xobjects = resources.get("/XObject", {})
                xobjects = xobjects.get_object() if hasattr(xobjects, "get_object") else xobjects
                target = xobjects.get(args[0])
                if target is None:
                    raise ValueError("image geometry missing XObject")
                target = target.get_object()
                if target.get("/Subtype") == "/Image":
                    ratios.append(min(1.0, scale / area))
                elif target.get("/Subtype") == "/Form":
                    matrix = target.get("/Matrix", (1, 0, 0, 1, 0, 0))
                    walk(
                        target,
                        target.get("/Resources", resources),
                        scale * determinant(matrix),
                        depth + 1,
                    )

    if area <= 0:
        raise ValueError("image geometry page area")
    walk(page.get_contents(), page.get("/Resources", {}), 1.0, 0)
    return ratios


def page_readability(text: str, ratios: list[float]) -> dict:
    count = sum(not char.isspace() for char in text)
    valid = not any(token in text for token in ("\ufffd", "\x00", "(cid:"))
    largest = max(ratios, default=0.0)
    aggregate_bound = min(1.0, sum(ratios))
    dominant = (
        count < READABILITY_POLICY["normal_text_min_chars"]
        and aggregate_bound >= READABILITY_POLICY["image_dominant_min_area_ratio"]
    )
    state = (
        "invalid_text"
        if not valid
        else "image_dominant_unreadable"
        if dominant
        else "empty_text"
        if not count
        else "text_readable"
    )
    return dict(
        state=state,
        native_nonspace_chars=count,
        largest_image_area_ratio=largest,
        aggregate_image_area_upper_bound=aggregate_bound,
        rendered_image_count=len(ratios),
        text_layer_readable=state == "text_readable",
        image_content_verified=False,
    )


def document_search(
    content: bytes, *, identity: dict, graph=None, selected_pages=(), environment_pages=()
) -> dict:
    """Read all native PDF pages. Raster labels are unresolved, even on text pages.

    Native text is search context, never a verified SourceRef. Missing parser or
    malformed/empty text remains unreadable. Do not silently OCR or call a vendor.
    """
    if sha256(content).hexdigest() != identity["source_sha256"]:
        raise ValueError("document search source hash mismatch")
    count = identity["page_count"]
    pages, unreadable, image_pages, errors = {}, set(), set(), {}
    readability = {}
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(content))
        if len(reader.pages) != count:
            raise ValueError("document search page count mismatch")
        for n, page in enumerate(reader.pages, 1):
            try:
                text = page.extract_text() or ""
                pages[n] = text
                ratios = image_area_ratios(page)
                assessment = page_readability(text, ratios)
                readability[str(n)] = assessment
                if ratios:
                    image_pages.add(n)
                if not assessment["text_layer_readable"]:
                    unreadable.add(n)
            except Exception as exc:
                unreadable.add(n)
                errors[n] = type(exc).__name__
                readability[str(n)] = dict(
                    state="extraction_or_geometry_error", text_layer_readable=False
                )
    except Exception as exc:
        errors[0] = type(exc).__name__
        # A graph remains searchable when optional PDF tooling is unavailable,
        # but cannot attest whole-document readability.
        if graph is not None:
            for block in graph.blocks:
                pages[block.page_num] = pages.get(block.page_num, "") + block.raw_text + "\n"
        unreadable.update(range(1, count + 1))
    if graph is not None:
        unreadable.update(
            b.page_num
            for b in graph.blocks
            if b.quality in ("unreadable", "unlocated", "conflicted")
        )
        unreadable.update(
            issue.page_num for issue in graph.issues if issue.state in ("open", "unreadable")
        )
    missing = sorted(set(range(1, count + 1)) - pages.keys())
    # Paid work remains selected-page-only; native indexing visits every page.
    appendix_cues = (
        "GRI",
        "SASB",
        "검증의견",
        "검증 의견",
        "보증의견",
        "보증 의견",
        "Assurance Statement",
        "ESG DATA",
        "환경 데이터",
        "환경데이터",
    )
    appendix_detected = {
        p
        for p, text in pages.items()
        if any(term.casefold() in text.casefold() for term in appendix_cues)
    }
    environment = sorted(
        (set(environment_pages) if environment_pages else set(selected_pages) - appendix_detected)
        & set(pages)
    )
    appendix = sorted((appendix_detected | set(selected_pages)) - set(environment))
    overview = sorted(
        p
        for p, text in pages.items()
        if p not in environment + appendix
        and any(
            term.casefold() in text.casefold()
            for term in ("About this report", "보고 범위", "보고 경계", "거버넌스", "Governance")
        )
    )
    remaining = sorted(set(pages) - set(environment + appendix + overview))
    priority = [
        dict(scope="environment", pages=environment),
        dict(scope="appendix", pages=appendix),
        dict(scope="overview_governance", pages=overview),
        dict(scope="remaining", pages=remaining),
    ]
    payload = dict(
        **identity,
        profile_sha256=SEARCH_PROFILE_HASH,
        native_reader="pypdf-6.19.0",
        readability_policy=READABILITY_POLICY,
        page_readability=readability,
        page_texts={str(p): text for p, text in sorted(pages.items())},
        page_hashes={str(p): sha256(text.encode()).hexdigest() for p, text in pages.items()},
        selected_pages=list(selected_pages),
        priority_scopes=priority,
        coverage=dict(
            page_count=count,
            searched_pages=sorted(pages),
            search_order=environment + appendix + overview + remaining,
            readable_pages=sorted(set(pages) - unreadable),
            unreadable_pages=sorted(unreadable),
            missing_pages=missing,
            image_pages=sorted(image_pages),
            image_dominant_unreadable_pages=sorted(
                int(p)
                for p, item in readability.items()
                if item["state"] == "image_dominant_unreadable"
            ),
            absence_readability_complete=not (image_pages or unreadable or missing or errors),
            errors={str(p): error for p, error in errors.items()},
        ),
    )
    return payload | {"artifact_sha256": canonical_hash(payload)}


def validated_present_refs(elements, inputs, claim, graph):
    """Replay existing citation/binding gates; search output cannot enter this path."""
    confirmed: dict[str, list[dict]] = {}
    if inputs is None:
        return confirmed
    inputs.validate()
    page_texts: dict[int, list[str]] = {}
    for block in graph.blocks:
        page_texts.setdefault(block.page_num, []).append(block.raw_text)
    for element in elements:
        if element["state"] != "present":
            continue
        refs = [SourceRef(**r) for r in element["evidence_refs"]]
        if not refs or any(
            verify_source_ref(r, graph, tenant_id=claim.tenant_id).verification_state != "verified"
            for r in refs
        ):
            continue
        eid = element["element_id"]
        policy = element.get("reason_code")
        if policy in POLICIES.values():
            accepted = POLICIES.get(eid) == policy and check_report_level(
                eid,
                policy,
                refs,
                claim_refs=claim.source_refs,
                claim_quote=claim.quote,
                page_texts=page_texts,
                credited_from=element.get("credited_from"),
            )
        else:
            accepted = all(
                accept_binding(
                    inputs.context,
                    r,
                    relation_tags_for(r, inputs.relation_tags),
                    original=graph,
                    tenant_id=claim.tenant_id,
                    rulepack=inputs.rulepack,
                    element_id=eid,
                )
                == "accepted"
                for r in refs
            )
        if accepted:
            confirmed[eid] = [asdict(r) for r in refs]
    return confirmed


def missing_evidence(claims, tenant, run_id, claim, *, track, elements, inputs=None):
    if inputs is not None:
        graph = inputs.original
    else:
        _, _, graph = claims.load_evidence(tenant, run_id)
    if (
        claim.tenant_id != tenant
        or graph.tenant_id != tenant
        or claim.document_version_id != graph.document_version_id
        or claim.parse_manifest_id != graph.parse_manifest_id
        or claim.source_sha256 != graph.source_sha256
    ):
        raise ValueError("element search claim/graph identity mismatch")
    snapshot = claims.store.snapshot(tenant, run_id)
    identity = dict(
        tenant_id=tenant,
        run_id=run_id,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        source_sha256=graph.source_sha256,
        page_count=snapshot["document"]["page_count"],
    )
    key = canonical_hash(identity | {"profile_sha256": SEARCH_PROFILE_HASH})
    jobs = claims.store.jobs
    with jobs._transaction() as db:
        raw = jobs._raw(db, tenant, run_id, "document_evidence_search", key)
    if raw is not None:
        document = json.loads(raw)
        if (
            any(document.get(k) != v for k, v in identity.items())
            or document.get("profile_sha256") != SEARCH_PROFILE_HASH
            or document["artifact_sha256"]
            != canonical_hash({k: v for k, v in document.items() if k != "artifact_sha256"})
        ):
            raise ValueError("document search artifact mismatch")
    else:
        content = claims.uploads.read_original(tenant, graph.document_version_id)
        document = document_search(
            content,
            identity=identity,
            graph=graph,
            selected_pages=snapshot["selected_pages"],
            environment_pages=snapshot.get("extraction_limits", {}).get("claim_pages", ()),
        )
        with jobs._transaction() as db:
            if jobs._raw(db, tenant, run_id, "document_evidence_search", key) is None:
                jobs._put(
                    db, tenant, run_id, "document_evidence_search", key, document, immutable=True
                )
    # Recheck citation/binding before reuse. Pin every input that affects search
    # and display, including graph quality and the currently validated facts.
    confirmed = validated_present_refs(elements, inputs, claim, graph)
    pins = dict(
        **identity,
        claim_id=claim.claim_id,
        claim_sha256=canonical_hash(asdict(claim)),
        run_input_sha256=snapshot["input_hash"],
        profile_sha256=SEARCH_PROFILE_HASH,
        tag_sha256=canonical_hash(elements),
        track=track,
        graph_sha256=canonical_hash(asdict(graph)),
        document_search_sha256=document["artifact_sha256"],
        confirmed_refs_sha256=canonical_hash(confirmed),
    )
    element_key = "input:" + canonical_hash(pins)
    with jobs._transaction() as db:
        cached = jobs._raw(db, tenant, run_id, "element_evidence_search", element_key)
    if cached is not None:
        artifact = json.loads(cached)
        if any(artifact.get(k) != v for k, v in pins.items()) or artifact.get(
            "artifact_sha256"
        ) != canonical_hash({k: v for k, v in artifact.items() if k != "artifact_sha256"}):
            raise ValueError("element search artifact mismatch")
        return json.loads(canonical_json(artifact["elements"]))
    search = LocalEvidenceSearch(
        graph,
        tenant_id=tenant,
        pages=sorted({b.page_num for b in graph.blocks}),
        index_generation=SEARCH_PROFILE_HASH,
    )
    from proofops.application.evidence.element_queries import ELEMENT_TERMS
    from proofops.domain.rules.engine import MAPPINGS

    candidates = {}
    blocks = {b.source_id: b for b in graph.blocks}
    for eid in MAPPINGS.get(track, {}):
        hits = search.search_all(search.scope, " ".join(ELEMENT_TERMS[eid]))
        refs = []
        for hit in hits.hits:
            block = blocks[hit.source_id]
            if (
                block.winner is None
                or not block.raw_text
                or not literal_hits({block.page_num: block.raw_text}, ELEMENT_TERMS[eid])
            ):
                continue
            try:
                ref = block.source_ref()
            except ValueError:
                continue  # unlocated source remains a native search diagnostic
            # Short exact display spans; all source ids retained in artifact.
            ref = replace(
                ref,
                char_start=0,
                char_end=min(200, len(block.raw_text)),
                quote=block.raw_text[:200],
                verification_state="candidate",
            )
            refs.append(asdict(ref))
        candidates[eid] = refs
    result = search_elements(
        track=track,
        claim_quote=claim.quote,
        document=document,
        elements=elements,
        confirmed_refs=confirmed,
        candidate_refs=candidates,
    )
    # First response and persisted/cached responses use identical nested key
    # ordering and JSON-native types; dictionary construction order is irrelevant.
    result = json.loads(canonical_json(result))
    payload = pins | {"elements": result}
    artifact = payload | {"artifact_sha256": canonical_hash(payload)}
    with jobs._transaction() as db:
        prior = jobs._raw(db, tenant, run_id, "element_evidence_search", element_key)
        if prior is None:
            jobs._put(
                db, tenant, run_id, "element_evidence_search", element_key, artifact, immutable=True
            )
        elif canonical_hash(json.loads(prior)) != canonical_hash(artifact):
            raise ValueError("element search artifact mismatch")
    return result
