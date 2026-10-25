"""Local PB1 observations and QT1 reconciliation under the extractor's policy."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from proofops_agent.upstage_extraction import UpstageClaimExtractor


def extract_pb1(
    self: UpstageClaimExtractor,
    packet: dict[str, Any],
    text: str,
    context_graph: Any,
) -> dict[str, Any] | None:
    """Return local table observations, or continue to the model when required."""
    from proofops_agent import upstage_extraction as facade

    self._require_graph(packet, context_graph)
    from proofops.application.ingest.pb1_tables import observations

    data = packet["untrusted_document_data"]
    block = next(b for b in context_graph.blocks if b.source_id == data["source_id"])
    context = " ".join(block.candidates[block.winner].context)
    if self._w9:
        from proofops.application.ingest.w9_tables import observations_for

        if self._j8:
            from proofops.application.ingest.j8_cells import observations_for

        if self._k6:
            from proofops.application.ingest.k6_coverage import observations_for

        raw_rows = observations_for(block, context_graph)
    else:
        raw_rows = observations(text, context=context)
    rows = raw_rows
    if self._table_footnotes:
        from proofops.application.tagging.dec24 import table_footnote

        rows = [r for r in raw_rows if not table_footnote(r["quote"], kind="table")]
    result: dict[str, Any] = {
        "spans": [
            dict(
                char_start=r["start"],
                char_end=r["end"],
                quote=r["quote"],
                kind="claim",
                reason=None,
                topic_ids=["environment"],
            )
            for r in rows
        ]
    }
    boundary_records: list[dict[str, Any]] = []
    if self._k1:
        from proofops.application.ingest.k1_boundaries import trim_table_labels

        result["spans"], boundary_records = trim_table_labels(result["spans"], text, kind="table")
    self._validate_spans(result, text)
    directory = self._receipts / (
        "pb1-" + facade.canonical_hash({"packet": packet, "policy": self._profile.rule_sha256})
        if self._w9
        else "pb1-" + facade.canonical_hash(packet)
    )
    if not directory.exists():
        directory.mkdir(mode=0o700)
        self._write(directory / "packet.json", facade.canonical_json(packet))
        self._write(directory / "observations.json", facade.canonical_json(raw_rows))
        if self._k1:
            self._write(directory / "k1-boundaries.json", facade.canonical_json(boundary_records))
        if self._table_footnotes:
            self._write(
                directory / "table-context-exclusions.json",
                facade.canonical_json([r for r in raw_rows if r not in rows]),
            )
        self._write(directory / "result.json", facade.canonical_json(result))
    elif facade.json.loads((directory / "result.json").read_text()) != result:
        raise ValueError("EXTRACTION_PB1_REPLAY_MISMATCH")
    if rows or any(
        "\t" in line
        and any(__import__("re").fullmatch(r"20\d{2}(?:년)?", c.strip()) for c in line.split("\t"))
        for line in text.split("\n")[:4]
    ):
        return result
    return None


def reconcile_qt1(
    self: UpstageClaimExtractor,
    packet: dict[str, Any],
    context_graph: Any,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Reconcile table candidates and preserve the immutable before/after receipt."""
    from proofops_agent import upstage_extraction as facade

    self._validate_context_graph(packet, context_graph)
    from proofops.application.ingest.qt1_tables import candidates_for, reconcile

    data = packet["untrusted_document_data"]
    block = next(b for b in context_graph.blocks if b.source_id == data["source_id"])
    candidates = candidates_for(block, context_graph)
    spans, coverage = reconcile(data["text"], candidates, result["spans"])
    try:
        self._validate_spans({"spans": spans}, data["text"])
    except ValueError:
        # Recovered table spans pass the same quote/offset guards as model
        # spans. A rejected table remains unknown without losing siblings.
        # Identity, grid and immutable receipt checks stay outside this catch.
        raise facade.ExtractionOutputError(
            "TABLE_QT1_SPAN_INVALID", failure_code="TABLE_QT1_SPAN_INVALID"
        ) from None
    record = dict(
        packet=packet,
        profile=facade.asdict(self.profile),
        candidates=candidates,
        coverage=coverage,
        before=result,
        after=dict(spans=spans),
    )
    path = self._receipts / (
        "qt1-"
        + facade.canonical_hash(
            dict(packet=packet, profile=facade.asdict(self.profile), candidates=candidates)
        )
        + ".json"
    )
    encoded = facade.canonical_json(record)
    if path.exists():
        if path.read_text() != encoded:
            raise ValueError("QT1_EXTRACTION_REPLAY_MISMATCH")
    else:
        self._write(path, encoded)
    return {"spans": spans}
