"""Opt-in literal row/column bundles. Candidates require fresh element selections.

QT1's checked grid owns every offset. TB1 restores the shared-year origin and
recognizes spaced year-note markers without modifying historical QT1 behavior.
No missing source, row, period, unit, or footnote is inferred or promoted.
"""

import re
from dataclasses import asdict, replace

from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.ingest.qt1_tables import UNIT, VALUE, candidates_for
from proofops.application.tagging.qt1_tuples import _literal_unit, _notes, add_sources, contains
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef

YEAR = re.compile(r"((?:19|20)\d{2})(?:\s*년)?(?:\s*(?:실적|성과|목표))?(?:\s*\d{1,2}\))*")
ELEMENTS = ("P1", "P2", "P3", "G1", "G2", "G3")
METHOD = re.compile(r"합산|환산|제외|나누|÷|계산식|산정식|calculat|convert", re.I)
GUIDANCE = """
TB1: tb1_table_bundles bind verified literal cells in ONE row to their own column
headers, year, unit, row labels and applicable footnotes. Each bundle lists
required_ids; cite ALL those IDs when using that bundle, with normalized_value
equal to its exact value quote (G1 uses the exact period quote). Read qualifiers
and notes, not just numbers. When TB1 bundles exist, they replace legacy QT1's
three-ID tuple advice: value/unit/year alone are INCOMPLETE. Include every row
label, column header and footnote ID from required_ids for P1/P2/P3/G1/G2/G3.
P1 uses a focal observed value, never the target
column, forecast, capacity-as-output or another row. P2 needs an earlier observed
value in that SAME row/unit and the later focal observation; prefer the immediately
preceding observed year. Cite the baseline's required_ids; optionally also cite
ALL required_ids of the later focal observation. A target is not a baseline.
P3 requires BOTH an explicit calculation method in the applicable notes AND its
calculation boundary in that same bundle's labels/notes. Cite the entire latest
focal observation bundle, including its method notes; normalized_value is null.
An isolated year, unit, scope label or data-restatement notice is not P3.
G1/G2 use the focal target's year/value. G3 requires a baseline value
AND its year/unit for that same target and metric; a target year alone is not a
baseline. Cite its complete baseline bundle; a complete focal target bundle may
also be cited. Do not infer a reduction from maintenance. Bundles are citable sources,
not element votes: select present only if the element definition is satisfied.
Keep conflict/unreadable and all other source/semantic guards. Python alone grades.
""".strip()
POLICY = dict(
    profile="tb1_verified_table_bundles_v1",
    elements=list(ELEMENTS),
    year_pattern=YEAR.pattern,
    guidance_sha256=canonical_hash(GUIDANCE),
    source="checked-origin-grid; individually-verified-cells-or-exact-table-subspans",
    binding="one-row; own-column-or-explicit-shared-year; all-axes-and-inherited-label-notes",
    admission="model-selects-entire-bundle; no-target-as-actual; no-other-row-or-unit",
    comparison="complete-baseline; optional-complete-later-focal-bundle-in-same-row-unit",
    wire="complete-TB1-bundles-replace-legacy-three-field-tuples-when-present",
    method_note_pattern=METHOD.pattern,
    max_bundles=12,
)


def checked_rows(table, graph):
    try:
        return candidates_for(table, graph)
    except ValueError as error:
        if not str(error).startswith("J8_GRID_"):
            raise
        return []


def header_refs(graph, refs):
    """Only header rows of numeric tables containing a selected claim span."""
    blocks = {b.source_id: b for b in graph.blocks}
    result = {}
    for ref in refs:
        table = blocks.get(ref.source_id)
        if table is None or table.kind != "table":
            continue
        for row in checked_rows(table, graph):
            if not row["values"] or not contains(row["source_ref"], asdict(ref)):
                continue
            groups: dict[int, list[dict]] = {}
            for cell in row["headers"]:
                groups.setdefault(cell["row"], []).append(cell)
            for cells in groups.values():
                head = table.source_ref(
                    normalized_char_start=min(c["start"] for c in cells),
                    normalized_char_end=max(c["end"] for c in cells),
                )
                result[(head.source_id, head.char_start, head.char_end)] = head
    return tuple(result.values())


def bundle_refs(item):
    refs = [item[k] for k in ("value", "unit", "period")]
    refs += item["row_labels"] + item["column_headers"] + item["notes"]
    return list({canonical_hash(r): r for r in refs}.values())


def bundles_for(claim, graph, *, tenant_id):
    if (
        claim.tenant_id != tenant_id
        or graph.tenant_id != tenant_id
        or claim.source_quality != "verified"
        or len(claim.source_refs) != 1
    ):
        return []
    focal = claim.source_refs[0]
    if verify_source_ref(focal, graph, tenant_id=tenant_id).verification_state != "verified":
        return []
    blocks = {b.source_id: b for b in graph.blocks}
    table = blocks.get(focal.source_id)
    if table is None or table.kind != "table":
        return []
    result = []
    for row in checked_rows(table, graph):
        if not contains(row["source_ref"], asdict(focal)):
            continue

        def verified(raw):
            if raw is None:
                return None
            ref = SourceRef(**raw)
            checked = verify_source_ref(ref, graph, tenant_id=tenant_id)
            if checked.verification_state == "verified":
                return asdict(checked)
            # An independently attested origin cell may back its exact substring.
            for cell in row["cells"] + row["headers"] + row["row_headers"]:
                if not contains(cell["source_ref"], raw):
                    continue
                block = blocks.get(cell["cell_source_id"])
                if block is None or block.normalized_text != cell["quote"]:
                    continue
                local = block.source_ref(
                    normalized_char_start=ref.char_start - cell["source_ref"]["char_start"],
                    normalized_char_end=ref.char_end - cell["source_ref"]["char_start"],
                )
                checked = verify_source_ref(local, graph, tenant_id=tenant_id)
                if checked.verification_state == "verified":
                    return asdict(checked)
            return None

        for value in row["values"]:
            if not VALUE.fullmatch(value["quote"].strip()) or not re.search(r"\d", value["quote"]):
                continue
            # Multi-column/row values have no unique axis in this version.
            if value["row_span"] != 1 or value["column_span"] != 1:
                continue
            heads = value["column_headers"]
            years = [h for h in heads if YEAR.fullmatch(h["quote"].strip())]
            year_source = years[0] if len(years) == 1 else value["year_source"]
            if year_source is None or year_source.get("role") == "table_caption":
                continue
            raw_period = year_source.get("source_ref")
            if raw_period is None:
                # QT1's shared-year descriptor is a separate dict from headers.
                matches = [
                    h
                    for h in row["headers"]
                    if (h["start"], h["end"], h["quote"])
                    == (year_source["start"], year_source["end"], year_source["quote"])
                ]
                if len(matches) != 1:
                    continue
                raw_period = matches[0]["source_ref"]
            year_match = YEAR.fullmatch(year_source.get("quote", "").strip())
            year = year_match[1] if year_match else value["year"]
            if year is None:
                continue
            labels = [
                c
                for c in row["cells"] + row["row_headers"]
                if c["column"] < value["column"]
                and not VALUE.fullmatch(c["quote"].strip())
                and not UNIT.fullmatch(c["quote"].strip())
            ]
            notes, resolved = _notes(
                row | dict(cells=row["cells"] + row["row_headers"]), value, table, graph
            )
            if not labels or not resolved:
                continue
            # Include marker-bearing year heads when QT1 did not parse their year.
            axis_text = " ".join(h["quote"] for h in heads)
            role = "target" if "목표" in axis_text else "observation"
            if re.search(r"SSP|시나리오|예측|전망|예상", axis_text):
                role = "unspecified"
            item = dict(
                table_id=table.source_id,
                row_number=row["row"],
                column_number=value["column"],
                focal=contains(asdict(focal), value["source_ref"]),
                value=verified(value["source_ref"]),
                unit=verified(row["unit"]["source_ref"] if row["unit"] else _literal_unit(value)),
                period=verified(raw_period),
                year=year,
                period_role=role,
                row_labels=[verified(c["source_ref"]) for c in labels],
                column_headers=[verified(h["source_ref"]) for h in heads],
                notes=[verified(n) for n in notes],
            )
            if all(item[k] is not None for k in ("value", "unit", "period")) and all(
                r is not None for k in ("row_labels", "column_headers", "notes") for r in item[k]
            ):
                result.append(item | dict(bundle_sha256=canonical_hash(item)))
    return result if len(result) <= POLICY["max_bundles"] else []


def augment_packet(data, claim, graph, *, tenant_id):
    elements = [e for e in ELEMENTS if e in data["allowed_elements"]]
    items = bundles_for(claim, graph, tenant_id=tenant_id) if elements else []
    data["tb1_table_policy"] = POLICY
    data["tb1_table_bundles"] = items
    for item in items:
        add_sources(data, bundle_refs(item), elements, scope="same_table")
    return data


def validate_packet(data, claim, graph, *, tenant_id):
    expected = (
        bundles_for(claim, graph, tenant_id=tenant_id)
        if any(e in ELEMENTS for e in data["allowed_elements"])
        else []
    )
    if data.get("tb1_table_policy") != POLICY or canonical_hash(
        data.get("tb1_table_bundles")
    ) != canonical_hash(expected):
        raise ValueError("TB1_TABLE_PACKET_MISMATCH")
    return expected


def prepare_element(element, items):
    if element.state != "present" or element.element_id not in ELEMENTS:
        return element, False
    refs = [asdict(r) for r in element.evidence_refs]
    for item in items:
        eid, role = element.element_id, item["period_role"]
        if eid in ("P1", "P2", "P3") and role != "observation":
            continue
        if eid in ("G1", "G2") and (role != "target" or not item["focal"]):
            continue
        if eid in ("P1", "P3") and not item["focal"]:
            continue
        if eid in ("P1", "P3") and any(
            t["focal"] and t["period_role"] == "observation" and t["year"] > item["year"]
            for t in items
        ):
            continue  # A complete time-series row's current observation is its latest column.
        if eid == "P3" and not any(METHOD.search(n["quote"]) for n in item["notes"]):
            continue
        later = []
        if eid in ("P2", "G3"):
            later_role = "observation" if eid == "P2" else "target"
            later = [
                t
                for t in items
                if t["focal"]
                and t["period_role"] == later_role
                and t["year"] > item["year"]
                and t["table_id"] == item["table_id"]
                and t["row_number"] == item["row_number"]
                and t["unit"]["quote"] == item["unit"]["quote"]
            ]
            if role != "observation" or not later:
                continue
        normalized = None if eid == "P3" else item["period" if eid == "G1" else "value"]["quote"]
        base = bundle_refs(item)
        options = [base] + [base + bundle_refs(t) for t in later]
        for required in options:
            required = list({canonical_hash(r): r for r in required}.values())
            if (
                element.normalized_value == normalized
                and all(any(contains(r, p) for r in refs) for p in required)
                and all(any(contains(p, r) for p in required) for r in refs)
            ):
                return replace(element, evidence_refs=tuple(SourceRef(**r) for r in required)), True
    return element, False
