"""Bind model-selected P1/P2 to attested cells of one explicit PB1 observation.

No tagging or grading is inferred. An unknown vote, unverified row/cell, different
row, year, unit or tenant never qualifies. Whole-row P1 selections are narrowed
only when the model's own normalized selection covers the current value.
"""

from dataclasses import asdict, replace

from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.ingest.pb1_tables import observations
from proofops.domain.provenance import canonical_hash

POLICY = dict(
    profile="table-selected-evidence-pb2-v1",
    elements=["P1", "P2"],
    source="attested-row-and-cells",
    present="model-selection-required",
)
POLICY_HASH = canonical_hash(POLICY)


def observation_sources(claim, graph, *, tenant_id):
    if tenant_id != graph.tenant_id or claim.tenant_id != tenant_id or len(claim.source_refs) != 1:
        return None
    ref = claim.source_refs[0]
    if verify_source_ref(ref, graph, tenant_id=tenant_id).verification_state != "verified":
        return None
    blocks = {b.source_id: b for b in graph.blocks}
    table = blocks.get(ref.source_id)
    if table is None or table.kind != "table" or table.winner is None:
        return None
    context = table.candidates[table.winner].context
    if "pb1_table_claims" not in context:
        return None
    obs = next(
        (
            o
            for o in observations(table.normalized_text, context=" ".join(context))
            if o["start"] == ref.char_start and o["end"] == ref.char_end
        ),
        None,
    )
    if obs is None:
        return None
    ids = {
        e.source_id
        for e in graph.edges
        if e.relation == "table_parent" and e.target_id == table.source_id
    }
    grid = {}
    for sid in ids:
        b = blocks[sid]
        if b.kind != "table_cell" or b.winner is None:
            continue
        c = b.candidates[b.winner]
        if (c.source.parser_run_id, c.source.physical_page, c.table_native_id) != (
            table.candidates[table.winner].source.parser_run_id,
            table.page_num,
            table.candidates[table.winner].source.source_native_id,
        ):
            return None
        key = c.row_number, c.column_number
        if key in grid:
            return None
        grid[key] = b
    specs = []
    cursor = ref.char_start
    for col, text in enumerate(ref.quote.split("\t")):
        b = grid.get((obs["row"], col))
        if text != (b.raw_text if b else ""):
            return None
        if text:
            cell_ref = verify_source_ref(b.source_ref(), graph, tenant_id=tenant_id)
            specs.append(dict(column=col, start=cursor, end=cursor + len(text), ref=cell_ref))
        cursor += len(text) + 1
    value = next((s for s in specs if s["column"] == obs["value_column"]), None)
    units = [s for s in specs if s["ref"].quote == obs["unit"]]
    header = grid.get((obs["year_header"]["row"], obs["value_column"]))
    if value is None or len(units) != 1 or header is None:
        return None
    year = verify_source_ref(header.source_ref(), graph, tenant_id=tenant_id)
    required = (value["ref"], units[0]["ref"], year)
    if any(r.verification_state != "verified" for r in required):
        return None
    comparisons = []
    for item in obs["comparisons"]:
        val = next((s for s in specs if s["column"] == item["column"]), None)
        heads = [
            b
            for (r, c), b in grid.items()
            if r < obs["row"]
            and c == item["column"]
            and b.raw_text.strip() in (item["year"], item["year"] + "년")
        ]
        if val is not None and len(heads) == 1:
            head = verify_source_ref(heads[0].source_ref(), graph, tenant_id=tenant_id)
            if val["ref"].verification_state == head.verification_state == "verified":
                comparisons.append(dict(value=val, year=head))
    return dict(
        observation=obs,
        row=ref,
        specs=specs,
        value=value,
        unit=units[0],
        year=year,
        comparisons=comparisons,
    )


def augment_packet(data, claim, graph, *, tenant_id):
    data["table_evidence_policy"] = POLICY
    if not {"P1", "P2"}.intersection(data["allowed_elements"]):
        return data
    sources = observation_sources(claim, graph, tenant_id=tenant_id)
    if sources is None:
        return data
    candidates = data["evidence_candidates"]
    ids = {c["source_id"] for c in candidates}
    refs = [sources["value"]["ref"], sources["unit"]["ref"], sources["year"]]
    for comp in sources["comparisons"]:
        refs += [comp["value"]["ref"], comp["year"]]
    for ref in refs:
        if ref.source_id not in ids:
            candidates.append(
                dict(
                    source_id=ref.source_id,
                    source_scope="same_table",
                    allowed_elements=[e for e in ("P1", "P2") if e in data["allowed_elements"]],
                    source_refs=[asdict(ref)],
                )
            )
            ids.add(ref.source_id)
    data["table_observation_evidence"] = dict(
        policy_sha256=POLICY_HASH,
        observation=sources["observation"],
        value=asdict(sources["value"]["ref"]),
        unit=asdict(sources["unit"]["ref"]),
        year=asdict(sources["year"]),
        comparisons=[
            dict(value=asdict(c["value"]["ref"]), year=asdict(c["year"]))
            for c in sources["comparisons"]
        ],
    )
    return data


def prepare_element(element, claim, graph, *, tenant_id):
    if element.state != "present" or element.element_id not in ("P1", "P2"):
        return element, False
    sources = observation_sources(claim, graph, tenant_id=tenant_id)
    if sources is None or not element.evidence_refs or element.normalized_value is None:
        return element, False
    refs = element.evidence_refs
    row = sources["row"]
    allowed = [s["ref"] for s in sources["specs"]] + [sources["year"]]
    allowed += [c["year"] for c in sources["comparisons"]]

    def covers(target, selected):
        return target.source_id == selected.source_id and (
            selected.char_start <= target.char_start < target.char_end <= selected.char_end
        )

    if any(
        verify_source_ref(r, graph, tenant_id=tenant_id).verification_state != "verified"
        or not (covers(r, row) or any(covers(r, a) for a in allowed))
        for r in refs
    ):
        return element, False

    def selected(spec):
        return any(
            covers(spec["ref"], r)
            or (
                r.source_id == row.source_id
                and r.char_start <= spec["start"]
                and spec["end"] <= r.char_end
            )
            for r in refs
        )

    def normalized_selects(spec):
        # A model may quote the entire row and normalize to its selected value.
        # Only the exact already-attested focal cell is a valid narrowing.
        if " ".join(element.normalized_value.split()) == " ".join(spec["ref"].quote.split()):
            return selected(spec)
        for r in refs:
            if " ".join(r.quote.split()) != " ".join(element.normalized_value.split()):
                continue
            if covers(spec["ref"], r) or (
                r.source_id == row.source_id
                and r.char_start <= spec["start"]
                and spec["end"] <= r.char_end
            ):
                return True
        return False

    if element.element_id == "P1":
        if (
            not selected(sources["value"])
            or not selected(sources["unit"])
            or not normalized_selects(sources["value"])
        ):
            return element, False
        return replace(
            element,
            evidence_refs=(sources["value"]["ref"], sources["unit"]["ref"]),
            normalized_value=sources["value"]["ref"].quote,
        ), True
    for comp in sources["comparisons"]:
        if (
            selected(comp["value"])
            and any(covers(comp["year"], r) for r in refs)
            and normalized_selects(comp["value"])
        ):
            return element, True
    return element, False


def validated_observation(data, claim, graph, *, tenant_id):
    from proofops.domain.errors import DomainValidationError

    expected = augment_packet(
        {"evidence_candidates": [], "allowed_elements": data["allowed_elements"]},
        claim,
        graph,
        tenant_id=tenant_id,
    ).get("table_observation_evidence")
    if canonical_hash(data["table_observation_evidence"]) != canonical_hash(expected):
        raise DomainValidationError("table observation evidence mismatch")
    return expected


def structural_relation_ids(data, claim, graph, *, tenant_id):
    """Only appended P1/P2 sources whose literal attribution is already proven.

    Skipping a relation model is not an element vote. prepare_element still
    demands the model's own present selection, quantity/unit/year and all source
    guards. Other elements and external sources keep their ordinary role path.
    """
    if "table_observation_evidence" not in data:
        return frozenset()
    observation = validated_observation(data, claim, graph, tenant_id=tenant_id)
    if observation is None:
        return frozenset()
    refs = [observation[k] for k in ("value", "unit", "year")]
    refs += [r for comparison in observation["comparisons"] for r in comparison.values()]
    ids = {r["source_id"] for r in refs}
    return frozenset(
        c["source_id"]
        for c in data["evidence_candidates"]
        if c["source_id"] in ids and set(c["allowed_elements"]) <= {"P1", "P2"}
    )
