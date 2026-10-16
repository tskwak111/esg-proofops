"""V25: literal QT1 value/unit/period bundles. No extraction pass or new votes."""

import re
from dataclasses import asdict, replace

from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.ingest.qt1_tables import NOTE, UNIT, candidates_for
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef

GUIDANCE = (
    "QT1 V25: table tuples preserve value, actual unit and period as separate sources. "
    "For P1 select all three IDs and normalize to the exact value quote. For P2 select "
    "the earlier observation value, its year and unit from this same row. A target "
    "column is not an observation/comparison. Footnote markers, dates and '단위' "
    "are not quantities. '-' is missing, never zero. Keep contrary values."
)
POLICY = dict(
    profile="qt1_v25_table_tuples_v1",
    base="selected-table-coverage-qt1-v1",
    guidance_sha256=canonical_hash(GUIDANCE),
    admission="verified-value-unit-period-row-and-applicable-notes; selected-by-each-replica",
    comparison="same-row-earlier-observation-only; no-target-or-page-year-borrow",
    authority="candidates-only; no-new-extraction-or-votes",
)
_QUANTITY = re.compile(r"[+−-]?\d[\d,.]*(?:\s*[^\d\s].*)?")
_DATE = re.compile(r"(?:19|20)\d{2}[./-]\d{1,2}[./-]\d{1,2}")
_SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")


def contains(outer, inner):
    return (
        outer["source_id"] == inner["source_id"]
        and outer["char_start"] <= inner["char_start"] < inner["char_end"] <= outer["char_end"]
    )


def _ref(value):
    return value.get("source_ref") if value else None


def _literal_unit(value):
    ref = value["source_ref"]
    match = re.fullmatch(r"[+−-]?\d[\d,.]*\s*([^\d\s].*)", ref["quote"])
    if match and UNIT.fullmatch(match[1].strip()):
        start = match.start(1)
        return ref | dict(
            char_start=ref["char_start"] + start,
            char_end=ref["char_start"] + match.end(1),
            quote=match[1],
        )
    return None


def _notes(row, value, table, graph):
    texts = [c["quote"] for c in row["cells"] if c["column"] < value["column"]]
    texts += [c["quote"] for c in value["column_headers"]]
    markers = set()
    for text in texts:
        without_scope = re.sub(r"\([^()]*Scope[^()]*\)", "", text, flags=re.I)
        markers.update(NOTE.findall(without_scope))
        markers.update(m.translate(_SUPERSCRIPTS) for m in re.findall(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+", text))
        # Flattened superscripts require a matching numbered note below the table.
        if match := re.search(r"\)\s*(\d{1,2})$", text):
            markers.add(match[1])
    sources = [c for c in row["context_sources"] if c["role"] == "table_footnote"]
    # Some retained parsers flatten note 1 as "1.2024년부터". This is a
    # numbered note, not the year header and not a quantity of one.
    for block in graph.blocks:
        if block.page_num != table.page_num or block.kind != "paragraph" or block.bbox is None:
            continue
        match = re.match(r"^(\d{1,2})\.\s*(?=\S)", block.normalized_text)
        if not match or match[1] not in markers:
            continue
        owners = [
            b
            for b in graph.blocks
            if b.kind == "table"
            and b.page_num == table.page_num
            and b.bbox is not None
            and 0 <= block.bbox[1] - b.bbox[3] <= (b.bbox[2] - b.bbox[0]) * 0.25
            and max(block.bbox[0], b.bbox[0]) < min(block.bbox[2], b.bbox[2])
            and re.search(r"\)\s*" + re.escape(match[1]) + r"(?:\s|$)", b.normalized_text)
        ]
        if len(owners) == 1 and owners[0].source_id == table.source_id:
            sources.append(dict(marker=match[1], source_ref=asdict(block.source_ref())))
    selected = [c for c in sources if c["marker"] in markers]
    resolved = all(sum(c["marker"] == marker for c in selected) == 1 for marker in markers)
    return [c["source_ref"] for c in selected], resolved


def tuples_for(table, graph):
    result = []
    try:
        rows = candidates_for(table, graph)
    except ValueError as error:
        if not str(error).startswith("J8_GRID_"):
            raise
        return []  # no owned grid means unknown, never fabricated cells or absence
    for row in rows:

        def owned_ref(ref):
            if ref is None:
                return None
            checked = verify_source_ref(SourceRef(**ref), graph, tenant_id=graph.tenant_id)
            if checked.verification_state == "verified":
                return asdict(checked)
            # A verified cell does not promote the whole parent table. Resolve
            # only the same grid origin and exact substring, then re-verify it.
            for cell in row["cells"] + row["headers"] + row["row_headers"]:
                if not contains(cell["source_ref"], ref):
                    continue
                block = next(
                    (b for b in graph.blocks if b.source_id == cell["cell_source_id"]), None
                )
                if block is None or block.normalized_text != cell["quote"]:
                    continue
                candidate = block.source_ref(
                    normalized_char_start=ref["char_start"] - cell["source_ref"]["char_start"],
                    normalized_char_end=ref["char_end"] - cell["source_ref"]["char_start"],
                )
                checked = verify_source_ref(candidate, graph, tenant_id=graph.tenant_id)
                if checked.verification_state == "verified":
                    return asdict(checked)
            return ref

        for value in row["values"]:
            quote = value["quote"].strip()
            if not _QUANTITY.fullmatch(quote) or _DATE.fullmatch(quote):
                continue
            unit = owned_ref(_ref(row["unit"]) or _literal_unit(value))
            period = owned_ref(_ref(value["year_source"]))
            headers = " ".join(h["quote"] for h in value["column_headers"])
            role = "target" if "목표" in headers else "observation"
            # Scenario years and future contribution captions do not prove observations.
            if "SSP" in headers or (
                value["year_source"] and value["year_source"].get("role") == "table_caption"
            ):
                role = "unspecified"
            notes, notes_resolved = _notes(row, value, table, graph)
            value_ref = owned_ref(value["source_ref"])
            required = [row["source_ref"], value_ref, unit, period, *notes]
            verified = bool(unit and period and notes_resolved) and all(
                r is not None
                and verify_source_ref(
                    SourceRef(**r), graph, tenant_id=graph.tenant_id
                ).verification_state
                == "verified"
                for r in required
            )
            item = dict(
                table_id=table.source_id,
                row=row["source_ref"],
                value=value_ref,
                unit=unit,
                period=period,
                year=value["year"],
                period_role=role,
                notes=notes,
                notes_resolved=notes_resolved,
                admitted=bool(verified),
                policy_sha256=canonical_hash(POLICY),
            )
            result.append(item | dict(tuple_sha256=canonical_hash(item)))
    return result


def tuple_evidence(claim, graph, *, tenant_id):
    if (
        (claim.tenant_id, graph.tenant_id) != (tenant_id, tenant_id)
        or len(claim.source_refs) != 1
        or claim.source_quality != "verified"
    ):
        return []
    ref = claim.source_refs[0]
    if verify_source_ref(ref, graph, tenant_id=tenant_id).verification_state != "verified":
        return []
    table = next((b for b in graph.blocks if b.source_id == ref.source_id), None)
    if table is None or table.kind != "table":
        return []
    return [
        t
        for t in tuples_for(table, graph)
        if t["admitted"]
        and contains(t["row"], asdict(ref))
        # A subclaim must contain this exact value; a neighboring row cannot supply it.
        and contains(asdict(ref), t["value"])
    ]


def add_sources(data, refs, elements, *, scope):
    for ref in refs:
        candidate = next(
            (c for c in data["evidence_candidates"] if c["source_id"] == ref["source_id"]), None
        )
        if candidate is None:
            candidate = dict(
                source_id=ref["source_id"],
                source_scope=scope,
                allowed_elements=[],
                source_refs=[],
            )
            data["evidence_candidates"].append(candidate)
        candidate["allowed_elements"] = list(
            dict.fromkeys([*candidate["allowed_elements"], *elements])
        )
        if ref not in candidate["source_refs"]:
            candidate["source_refs"].append(ref)


def augment_packet(data, claim, graph, *, tenant_id):
    data["qt1_tuple_policy"] = POLICY
    elements = [e for e in ("P1", "P2") if e in data["allowed_elements"]]
    items = tuple_evidence(claim, graph, tenant_id=tenant_id) if elements else []
    data["qt1_table_tuples"] = items
    if elements:
        for item in items:
            add_sources(
                data, [item[k] for k in ("value", "unit", "period")], elements, scope="same_table"
            )
    return data


def validate_packet(data, claim, graph, *, tenant_id):
    expected = (
        tuple_evidence(claim, graph, tenant_id=tenant_id)
        if any(e in data["allowed_elements"] for e in ("P1", "P2"))
        else []
    )
    if data.get("qt1_tuple_policy") != POLICY or canonical_hash(
        data.get("qt1_table_tuples")
    ) != canonical_hash(expected):
        raise ValueError("QT1_TUPLE_REPLAY_MISMATCH")
    return data["qt1_table_tuples"]


def prepare_element(element, items):
    if element.state != "present" or element.element_id not in ("P1", "P2"):
        return element, False
    refs = [asdict(r) for r in element.evidence_refs]
    for item in items:
        if not item["admitted"] or item["period_role"] != "observation":
            continue
        required = [item[k] for k in ("value", "unit", "period")]
        if element.normalized_value not in (
            item["value"]["quote"],
            item["period"]["quote"] if element.element_id == "P2" else None,
        ):
            continue
        if element.element_id == "P2" and not any(
            t["row"] == item["row"]
            and t["period_role"] == "observation"
            and t["year"] > item["year"]
            and t["unit"]["quote"] == item["unit"]["quote"]
            for t in items
        ):
            continue
        if all(any(contains(r, p) for r in refs) for p in required) and all(
            any(contains(p, r) for p in [*required, item["row"]]) for r in refs
        ):
            return replace(element, evidence_refs=tuple(SourceRef(**r) for r in required)), True
    return element, False
