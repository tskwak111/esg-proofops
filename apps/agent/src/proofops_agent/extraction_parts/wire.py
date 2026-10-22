"""Source-bound request construction and one resolver shared by live and replay.

Functions receive the extractor policy/context explicitly and retain raw offsets.
They do not dispatch providers or write receipts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any
from uuid import UUID, uuid5

from proofops.application.claims import (
    ExtractionOutputError,
)
from proofops.application.ingest.atomic_candidates import (
    PROFILE as ATOMIC_PROFILE,
)
from proofops.application.ingest.atomic_candidates import PROFILE_V3 as ATOMIC_PROFILE_V3
from proofops.application.ingest.atomic_candidates import (
    atomic_candidates,
)
from proofops.application.ingest.table_row_candidates import (
    POLICY as ROW_POLICY,
)
from proofops.application.ingest.table_row_candidates import (
    PROFILE as ROW_PROFILE,
)
from proofops.application.ingest.table_row_candidates import (
    row_candidates,
)
from proofops.domain.provenance import canonical_hash
from proofops.domain.sentences import sentence_spans
from proofops.domain.values import _require_sha256, _require_uuid

from proofops_agent.extraction_parts.profiles import (
    _MAX_ATOMIC_CANDIDATES,
    _MAX_SOURCE_SENTENCES,
    _context_system_prompt,
    _display_suffix,
    _i3_wire_suffix,
    _i4_identity_suffix,
    _j8_suffix,
    _qc_figure_suffix,
    _system_prompt,
    _w9_suffix,
    join_selected_linewraps,
)


def _require_graph(self, packet: dict, context_graph: Any) -> None:
    """Graph presence matches the context option; then verify its identity."""
    if self._context:
        if context_graph is None:
            raise ValueError("EXTRACTION_CONTEXT_REQUIRED")
        self._validate_context_graph(packet, context_graph)
    elif context_graph is not None and not self._display_text_profile:
        raise ValueError("EXTRACTION_CONTEXT_UNEXPECTED")


def _resolve_payload(
    self,
    payload: Any,
    text: str,
    source_id: str,
    display_pin=None,
    *,
    packet=None,
    context_graph=None,
) -> tuple[tuple, dict[str, Any]]:
    """Turn one raw model response into validated spans plus its rejection record.

    Live and replay paths share this single site, so a stored response can
    only ever be resolved by the policy that wrote it. Quote mode is
    unchanged: each returned quote is located and individually validated,
    individually unusable quotes are recorded by index, and a response whose
    every quote fails is refused. Source-ID mode resolves offsets locally
    from ids this process minted; an unknown, repeated or non-string id
    voids the whole response instead of being silently dropped, because it
    means the model did not answer the asked question.
    """
    if self._source_ids:
        atomic_index = None
        if self._atomic or self._table_rows:
            blocks = self._context_for(packet, context_graph)[0] if self._context else []
            atomic_index = [
                (entry["sentence_id"], (entry["char_start"], entry["char_end"]))
                for entry in (
                    self._atomic_entries(packet, text, blocks)
                    if self._atomic
                    else self._row_entries(packet, text, blocks, context_graph=context_graph)
                )
            ]
        spans, diagnostics = self._resolve_sentence_ids(
            payload,
            text,
            source_id,
            index=atomic_index,
            paragraph_kind=(
                "derived_paragraph"
                if self._sentence_prefix
                and context_graph is not None
                and any(
                    e.source_id == source_id and e.relation == "derived_from"
                    for e in context_graph.edges
                )
                else "paragraph"
                if self._h1 and packet and packet["untrusted_document_data"]["kind"] == "heading"
                else packet["untrusted_document_data"]["kind"]
                if packet
                else None
            ),
            join_lines=(
                self._linewrap_join
                and not (
                    self._atomic_v3
                    and any(
                        "extraction-atomic-v3:" in sid for sid in payload.get("sentence_ids", [])
                    )
                )
                and packet is not None
                and (
                    packet["untrusted_document_data"]["kind"] == "paragraph"
                    or self._h1
                    and packet["untrusted_document_data"]["kind"] == "heading"
                )
            ),
        )
        if (
            self._pb1_context_guard
            and packet is not None
            and packet["untrusted_document_data"]["kind"] in {"table", "table_row", "table_cell"}
        ):
            from proofops.application.ingest.pb1_fragments import table_context_row

            diagnostics["table_context_excluded"] = [
                dict(char_start=span.char_start, char_end=span.char_end)
                for span in spans
                if table_context_row(span.quote)
            ]
            spans = tuple(span for span in spans if not table_context_row(span.quote))
        if self._table_footnotes and packet is not None:
            from proofops.application.tagging.dec24 import adjacent_table, table_footnote

            table_context = adjacent_table(
                packet, context_graph, located_only=self._located_table_context
            )
            excluded = [
                span
                for span in spans
                if table_footnote(
                    span.quote,
                    kind=packet["untrusted_document_data"]["kind"],
                    table_context=table_context,
                )
            ]
            diagnostics["table_footnote_excluded"] = [
                dict(
                    char_start=span.char_start,
                    char_end=span.char_end,
                    reason="table_context_only_dec24",
                )
                for span in excluded
            ]
            spans = tuple(span for span in spans if span not in excluded)
        refine_selected: Callable[..., Any]
        if self._j3 and packet is not None:
            if self._j7:
                from proofops.application.ingest.j7_split import refine_selected
            else:
                from proofops.application.ingest.j3_recall import refine_selected
            from proofops.application.ingest.w9_tables import graph_cells, observations_for

            kind = packet["untrusted_document_data"]["kind"]
            cells = None
            if kind == "table":
                self._validate_context_graph(packet, context_graph)
                table = next(b for b in context_graph.blocks if b.source_id == source_id)
                # PB1 time-series observations keep value/unit/year together.
                if not observations_for(table, context_graph):
                    cells = graph_cells(table, context_graph)
            refined, changes = refine_selected(
                [dict(asdict(span), topic_ids=list(span.topic_ids)) for span in spans],
                text,
                kind=kind,
                cells=cells,
            )
            try:
                spans = self._validate_spans({"spans": refined}, text)
            except ValueError:
                diagnostics["j7_refinement_rejected" if self._j7 else "j3_refinement_rejected"] = (
                    changes
                )
            else:
                diagnostics["j7_refinements" if self._j7 else "j3_refinements"] = changes
        if self._qt1_goal_split and packet is not None:
            from proofops.application.ingest.qt1_goal_split import refine_selected

            selected, changes = refine_selected(
                [asdict(s) | dict(topic_ids=list(s.topic_ids)) for s in spans],
                text,
                kind=packet["untrusted_document_data"]["kind"],
            )
            spans = self._validate_spans({"spans": selected}, text)
            diagnostics["qt1_goal_refinements"] = changes
        if self._k1 and packet is not None:
            from proofops.application.ingest.k1_boundaries import trim_table_labels

            selected, diagnostics["k1_boundaries"] = trim_table_labels(
                [asdict(s) | dict(topic_ids=list(s.topic_ids)) for s in spans],
                text,
                kind=packet["untrusted_document_data"]["kind"],
            )
            spans = self._validate_spans({"spans": selected}, text)
        if self._h1:
            from proofops.application.ingest.h1_boundaries import scope_note, strategy_title

            notes = [span for span in spans if scope_note(span.quote)]
            diagnostics["h1_scope_notes"] = [
                dict(
                    char_start=span.char_start,
                    char_end=span.char_end,
                    reason="explicit_target_boundary_note_context_only",
                )
                for span in notes
            ]
            spans = tuple(span for span in spans if span not in notes)
            title = packet.get("h1_native_title", {}) if packet else {}
            if title.get("is_title") is True and strategy_title(text):
                from proofops.application.ingest.h1_boundaries import POLICY as H1_POLICY

                if (
                    title.get("source_id") != source_id
                    or title.get("source_sha256") != packet.get("source_sha256")
                    or title.get("quote_sha256") != canonical_hash(text)
                    or title.get("policy_sha256") != canonical_hash(H1_POLICY)
                ):
                    raise ExtractionOutputError("H1_TITLE_PROOF_INVALID")
                diagnostics["h1_native_title"] = title
                spans = tuple(span for span in spans if span.quote != text)
        if self._k6 and packet is not None:
            from proofops.application.ingest.k6_coverage import rescue_targets

            selected, diagnostics["k6_target_rescue"] = rescue_targets(
                [asdict(s) | dict(topic_ids=list(s.topic_ids)) for s in spans],
                text,
                kind=packet["untrusted_document_data"]["kind"],
            )
            spans = self._validate_spans({"spans": selected}, text)
        if self._q1 and packet is not None and packet["untrusted_document_data"]["kind"] == "table":
            from proofops.application.ingest.j8_cells import graph_cells
            from proofops.application.ingest.q1_tables import retain_activities

            self._validate_context_graph(packet, context_graph)
            block = next(b for b in context_graph.blocks if b.source_id == source_id)
            selected, diagnostics["q1_activity_rescue"] = retain_activities(
                [asdict(s) | dict(topic_ids=list(s.topic_ids)) for s in spans],
                text,
                graph_cells(block, context_graph),
            )
            spans = self._validate_spans({"spans": selected}, text)
        return spans, diagnostics
    quotes = self._quotes(payload)
    span_dicts = []
    rejected_quote_indices = []
    for index, quote in enumerate(quotes):
        try:
            if display_pin is not None:
                from proofops.application.ingest.display_text import (
                    display_alignment,
                    locate_display,
                )

                start, end, raw_quote = locate_display(
                    quote, display_alignment(text, display_pin["deleted_offsets"])
                )
                span = dict(
                    char_start=start,
                    char_end=end,
                    quote=raw_quote,
                    kind="claim",
                    reason=None,
                    topic_ids=["environment"],
                )
            else:
                span = self._locate(quote, text)
            self._validate_spans({"spans": [span]}, text)
        except ValueError:
            rejected_quote_indices.append(index)
        else:
            span_dicts.append(span)
    if quotes and not span_dicts:
        raise ValueError("no valid claim quotes")
    return self._validate_spans({"spans": span_dicts}, text), {
        "rejected_quote_indices": rejected_quote_indices
    }


def _resolve_sentence_ids(
    self,
    payload: Any,
    text: str,
    source_id: str,
    *,
    index=None,
    join_lines=False,
    paragraph_kind=None,
) -> tuple[tuple, dict[str, Any]]:
    """Restore exact source spans for selected sentence ids; reject everything else."""
    if (
        not isinstance(payload, dict)
        or set(payload) != {"sentence_ids"}
        or not isinstance(payload["sentence_ids"], list)
    ):
        raise ValueError("sentence-ids-only response required")
    allowed = dict(
        index if index is not None else self._sentence_index(text, source_id, self._content_bounds)
    )
    if self._i4_identity:
        allowed = {f"c{i}": span for i, span in enumerate(allowed.values())}
    selected = []
    seen: set[str] = set()
    for sentence_id in payload["sentence_ids"]:
        # A context block id, a sentence id from another source, an id the
        # model made up and a repeated id are all the same failure here.
        if not isinstance(sentence_id, str) or sentence_id not in allowed or sentence_id in seen:
            raise ValueError("unknown or repeated sentence id")
        seen.add(sentence_id)
        start, end = allowed[sentence_id]
        selected.append(
            (
                sentence_id,
                {
                    "char_start": start,
                    "char_end": end,
                    # Restored from the original text, never from the response.
                    "quote": text[start:end],
                    "kind": "claim",
                    "reason": None,
                    "topic_ids": ["environment"],
                },
            )
        )
    span_dicts = []
    rejected_sentence_ids = []
    for sentence_id, span in selected:
        try:
            self._validate_spans({"spans": [span]}, text)
        except ValueError:
            # A source-text property (e.g. an unclosed original quotation),
            # not a model error: drop this sentence, keep the rest.
            rejected_sentence_ids.append(sentence_id)
        else:
            span_dicts.append(span)
    if selected and not span_dicts:
        raise ValueError("no usable selected sentences")
    prefix_records: list[dict[str, Any]] = []
    if self._sentence_prefix and join_lines:
        from proofops.application.ingest.sentence_prefix import expand_sentence_prefixes

        span_dicts, prefix_records = expand_sentence_prefixes(span_dicts, text, kind=paragraph_kind)
        self._validate_spans({"spans": span_dicts}, text)
    if join_lines:
        span_dicts = join_selected_linewraps(
            span_dicts, text, fragment_guard="pb1-v1" if self._pb1 else self._fragment_guard
        )
    return self._validate_spans({"spans": span_dicts}, text), {
        "rejected_sentence_ids": rejected_sentence_ids,
        **({"sentence_prefix": prefix_records} if self._sentence_prefix else {}),
    }


def _sentence_index(
    text: str, source_id: str, extraction_content_bounds: bool = False
) -> list[tuple[str, tuple[int, int]]]:
    """Bounded ``source_id:index`` sentence ids over the packet's own text.

    The ids are minted here and the offsets are this process's own, so
    nothing the model returns can move or rewrite a span. One construction
    site serves both the outbound wire and response resolution, so the
    allowed id set is exactly the sent one.
    """
    spans = sentence_spans(text)
    if extraction_content_bounds:
        adjusted_spans = []
        for start, end in spans:
            if end > start + 1 and text[end - 1] == "." and text[end - 2].isalpha():
                end -= 1
            adjusted_spans.append((start, end))
        spans = adjusted_spans
    if not spans:
        raise ExtractionOutputError("EXTRACTION_SOURCE_SENTENCES_EMPTY")
    if len(spans) > _MAX_SOURCE_SENTENCES:
        # Keep the source unknown and continue the batch instead of sending an
        # unbounded id list the model could silently truncate.
        raise ExtractionOutputError("EXTRACTION_SOURCE_SENTENCES_UNBOUNDED")
    return [
        (
            f"{source_id}:{index}:{span[0]}:{span[1]}"
            if extraction_content_bounds
            else f"{source_id}:{index}",
            span,
        )
        for index, span in enumerate(spans)
    ]


def _atomic_entries(self, packet, text, context_blocks, *, diagnostics=None):
    data = packet["untrusted_document_data"]
    axes = tuple(b["text"] for b in context_blocks if b["role"].startswith("table_"))
    candidates = atomic_candidates(
        text,
        kind=data.get("kind", "paragraph"),
        table_context=axes,
        diagnostics=diagnostics,
        policy_version=3 if self._atomic_v3 else 2,
    )
    if len(candidates) > _MAX_ATOMIC_CANDIDATES:
        raise ExtractionOutputError("EXTRACTION_SOURCE_SENTENCES_UNBOUNDED")
    entries = []
    for c in candidates:
        end = c.end
        if self._content_bounds and end > c.start + 1:
            if text[end - 1] == "." and text[end - 2].isalpha():
                end -= 1
        entries.append(
            {
                "sentence_id": (
                    f"{data['source_id']}:"
                    f"{ATOMIC_PROFILE_V3 if self._atomic_v3 else ATOMIC_PROFILE}:"
                    f"{c.start}:{end}"
                ),
                "text": text[c.start : end],
                "char_start": c.start,
                "char_end": end,
                "parent_quote": text[c.parent_start : c.parent_end],
                "parent_start": c.parent_start,
                "parent_end": c.parent_end,
                "kind": c.kind,
                "context_dependent": c.context_dependent,
            }
        )
    return entries


def _row_entries(self, packet, text, context_blocks, *, context_graph=None):
    data = packet["untrusted_document_data"]
    kind = data["kind"]
    if self._qc_native_figures:
        from proofops.application.ingest.k6_coverage import (
            FIGURE_MARKER,
            FIGURE_POLICY,
            FIGURE_V1_MARKER,
            FIGURE_V1_POLICY,
        )

        self._validate_context_graph(packet, context_graph)
        block = next(b for b in context_graph.blocks if b.source_id == data["source_id"])
        context = block.candidates[block.winner].context
        marker = FIGURE_MARKER if FIGURE_MARKER in context else FIGURE_V1_MARKER
        policy = FIGURE_POLICY if marker == FIGURE_MARKER else FIGURE_V1_POLICY
        if marker in context:
            if kind != "paragraph" or "qc_native_policy=" + canonical_hash(policy) not in context:
                raise ExtractionOutputError("QC_NATIVE_FIGURE_POLICY_MISMATCH")
            return [
                dict(
                    sentence_id=f"{data['source_id']}:{marker}:0:{len(text)}",
                    text=text,
                    char_start=0,
                    char_end=len(text),
                    binding_status="undetermined",
                )
            ]
    if kind not in ("table", "table_row", "table_cell", "figure"):
        if self._atomic_v3:
            # The combined profile keeps the mature v19 sentence/line-wrap
            # path unless the v3 recognition split actually changes an atom.
            # Standalone atomic mode still applies the complete v3 policy.
            current = self._atomic_entries(packet, text, context_blocks)
            old = atomic_candidates(text, kind=kind, policy_version=2)
            if [(entry["char_start"], entry["char_end"]) for entry in current] != [
                (candidate.start, candidate.end) for candidate in old
            ]:
                return current
        return [
            {"sentence_id": sid, "text": text[a:b], "char_start": a, "char_end": b}
            for sid, (a, b) in self._sentence_index(text, data["source_id"], self._content_bounds)
        ]
    if self._w9 and kind == "figure":
        return []
    if self._w9 and kind == "table":
        from proofops.application.ingest.w9_tables import cell_entries, graph_cells

        self._validate_context_graph(packet, context_graph)
        block = next(b for b in context_graph.blocks if b.source_id == data["source_id"])
        cells = graph_cells(block, context_graph)
        if self._j8:
            from proofops.application.ingest.j8_cells import cell_entries, graph_cells

            cells = graph_cells(block, context_graph)
        if self._q1:
            from proofops.application.ingest.q1_tables import cell_entries
        if self._j8 or any("\n" in c["text"] for c in cells):
            entries = cell_entries(text, cells, source_id=data["source_id"])
            if len(entries) > ROW_POLICY["max_candidates"]:
                raise ExtractionOutputError("EXTRACTION_SOURCE_SENTENCES_UNBOUNDED")
            return entries
    axes = [b for b in context_blocks if b["role"].startswith("table_")]
    candidates = row_candidates(text, kind=kind, table_context=tuple(b["text"] for b in axes))
    if len(candidates) > ROW_POLICY["max_candidates"]:
        raise ExtractionOutputError("EXTRACTION_SOURCE_SENTENCES_UNBOUNDED")
    entries = []
    for row in candidates:
        parent = list(axes)
        if row.header_start is not None:
            parent.append(
                {
                    "role": "same_source_header",
                    "source_id": data["source_id"],
                    "char_start": row.header_start,
                    "char_end": row.header_end,
                    "text": text[row.header_start : row.header_end],
                }
            )
        entries.append(
            {
                "sentence_id": f"{data['source_id']}:{ROW_PROFILE}:{row.start}:{row.end}",
                "text": text[row.start : row.end],
                "char_start": row.start,
                "char_end": row.end,
                "parent_context": parent,
                "binding_status": "undetermined",
            }
        )
    return entries


def _source_id_wire(
    self, packet: dict, text: str, packet_sha: str, context_graph: Any, display_catalog=None
) -> tuple[str, dict, str]:
    """Build the pinned source-ID wire: system, user data, bound request id.

    The source text travels already split, so there is no text for the model
    to copy back. Context blocks (when the context option is on) travel
    exactly as in context mode and still carry no sentence id. The request id
    binds the packet hash to the actual outbound content, so a different
    split, a different context or a different omission set addresses a
    different receipt and can never replay this one.
    """
    context_blocks, omitted_source_ids = (
        self._context_for(packet, context_graph) if self._context else ([], [])
    )
    sentence_ids = (
        []
        if self._atomic or self._table_rows
        else self._sentence_index(
            text, packet["untrusted_document_data"]["source_id"], self._content_bounds
        )
    )
    source_id = packet["untrusted_document_data"]["source_id"]
    data: dict[str, Any] = {
        "source_id": source_id,
        "source_sentences": [
            {"sentence_id": sentence_id, "text": text[start:end]}
            for sentence_id, (start, end) in sentence_ids
        ],
    }
    if self._atomic:
        diagnostics: dict[str, int] = {}
        data["source_sentences"] = self._atomic_entries(
            packet, text, context_blocks, diagnostics=diagnostics
        )
        data["candidate_diagnostics"] = diagnostics
        data["candidate_profile"] = ATOMIC_PROFILE_V3 if self._atomic_v3 else ATOMIC_PROFILE
    if self._table_rows:
        data["source_sentences"] = self._row_entries(
            packet, text, context_blocks, context_graph=context_graph
        )
        data["candidate_profile"] = ROW_PROFILE
    if self._context:
        data["context_blocks"] = context_blocks
        data["omitted_source_ids"] = omitted_source_ids
    system_prompt = _system_prompt(
        extraction_context=self._context,
        extraction_table_context=self._table_context,
        source_ids=True,
        assertion_prompt=self._assertion_prompt,
        complete_selection=self._complete_selection,
        extraction_atomic=self._atomic,
        extraction_atomic_v3=self._atomic_v3,
        extraction_table_rows=self._table_rows,
        extraction_recall_prompt=self._recall_prompt,
    )
    if self._w9:
        system_prompt += _w9_suffix()
    if self._j8:
        system_prompt += _j8_suffix()
        data["candidate_profile"] = "j8-owned-cell-candidates-v1"
    user_data: dict[str, Any] = {
        "tenant_id": packet["tenant_id"],
        "document_version_id": packet["document_version_id"],
        "parse_manifest_id": packet["parse_manifest_id"],
        "source_sha256": packet["source_sha256"],
        "untrusted_document_data": data,
    }
    if self._position_order:
        user_data["context_ordering"] = self._context_order_policy()
    system_prompt, user_data = self._display_wire(packet, system_prompt, user_data, display_catalog)
    if self._i3_wire:
        from proofops.application.ingest.i3_wire import compact

        user_data["untrusted_document_data"] = compact(user_data["untrusted_document_data"])
        system_prompt += _i3_wire_suffix()
    if self._i4_identity:
        for i, entry in enumerate(user_data["untrusted_document_data"]["source_sentences"]):
            entry["sentence_id"] = f"c{i}"
        system_prompt += _i4_identity_suffix()
    if self._qc_native_figures:
        system_prompt += _qc_figure_suffix()
    if self._j3:
        user_data["selected_span_policy_sha256"] = self._profile.rule_sha256
    content_sha = canonical_hash({"system_prompt": system_prompt, "user_data": user_data})
    request_id = str(uuid5(UUID(packet["parse_manifest_id"]), packet_sha + ":" + content_sha))
    return system_prompt, {**user_data, "request_id": request_id}, request_id


def _display_wire(self, packet, system, user, catalog):
    if not self._display_text_profile:
        return system, user
    from proofops.application.ingest.display_text import POLICY, display_alignment

    data = user["untrusted_document_data"]
    pin = packet["display_text"]
    pins = [pin]
    if "text" in data:
        data["text"] = pin["text"]
    if "source_sentences" in data:
        text = packet["untrusted_document_data"]["text"]
        bounds = (
            {s["sentence_id"]: (s["char_start"], s["char_end"]) for s in data["source_sentences"]}
            if self._atomic or self._table_rows
            else dict(self._sentence_index(text, data["source_id"], self._content_bounds))
        )
        for sentence in data["source_sentences"]:
            start, end = bounds[sentence["sentence_id"]]
            deleted = [i - start for i in pin["deleted_offsets"] if start < i < end - 1]
            sentence["text"] = display_alignment(text[start:end], deleted).text
    for block in data.get("context_blocks", []):
        context_pin = catalog.block_pin(block["source_id"])
        if context_pin["raw_sha256"] != canonical_hash(block["text"]):
            raise ValueError("DISPLAY_CONTEXT_MISMATCH")
        block["text"] = context_pin["text"]
        pins.append(context_pin)
    user["display_policy"] = POLICY
    if pins[1:] != packet["display_text_context"]:
        raise ValueError("DISPLAY_CONTEXT_MISMATCH")
    user["display_map_sha256"] = canonical_hash(pins)
    return system + _display_suffix(), user


def _packet_text(self, packet: Any) -> str:
    try:
        if not isinstance(packet, dict):
            raise ValueError("packet must be a mapping")
        _require_uuid("tenant_id", packet["tenant_id"])
        _require_uuid("document_version_id", packet["document_version_id"])
        _require_uuid("parse_manifest_id", packet["parse_manifest_id"])
        _require_sha256("source_sha256", packet["source_sha256"])
        data = packet["untrusted_document_data"]
        _require_uuid("source_id", data["source_id"])
        text = data["text"]
        if not isinstance(text, str) or not text:
            raise ValueError("source text required")
        expected = packet.get("extraction_profile")
        if expected is not None and expected != asdict(self._profile):
            raise ValueError("extraction profile mismatch")
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ValueError("EXTRACTION_PACKET_IDENTITY_INVALID") from None
    return packet["untrusted_document_data"]["text"]


def _validate_context_graph(packet: dict, context_graph: Any) -> None:
    """Verify graph and focal identity against the packet before any call.

    A cross-tenant, cross-document, cross-manifest, or cross-source graph
    fails closed, reusing the ingest structure validator for nested
    batch/candidate identity and duplicate/edge integrity. The focal block
    must then exist exactly once with a winner and byte-equal text, kind,
    and page: a missing or mismatched focal fails closed instead of
    degrading to an empty context. Source text matching alone is never
    sufficient.
    """
    try:
        data = packet["untrusted_document_data"]
        expected = (
            packet["tenant_id"],
            packet["document_version_id"],
            packet["parse_manifest_id"],
            packet["source_sha256"],
        )
        actual = (
            context_graph.tenant_id,
            context_graph.document_version_id,
            context_graph.parse_manifest_id,
            context_graph.source_sha256,
        )
    except (AttributeError, KeyError, TypeError):
        raise ValueError("EXTRACTION_CONTEXT_IDENTITY_INVALID") from None
    if actual != expected:
        raise ValueError("EXTRACTION_CONTEXT_IDENTITY_INVALID")
    try:
        from proofops.application.ingest.normalize import _validate as _validate_structure

        _validate_structure(context_graph, packet["tenant_id"])
    except (AttributeError, KeyError, TypeError, ValueError):
        raise ValueError("EXTRACTION_CONTEXT_IDENTITY_INVALID") from None
    try:
        matches = [block for block in context_graph.blocks if block.source_id == data["source_id"]]
    except (AttributeError, TypeError):
        raise ValueError("EXTRACTION_CONTEXT_FOCAL_INVALID") from None
    if len(matches) != 1:
        raise ValueError("EXTRACTION_CONTEXT_FOCAL_INVALID")
    target = matches[0]
    try:
        focal_ok = (
            target.winner is not None
            and target.normalized_text == data["text"]
            and target.kind == data["kind"]
            and target.page_num == data["page_num"]
        )
    except (AttributeError, KeyError, TypeError):
        raise ValueError("EXTRACTION_CONTEXT_FOCAL_INVALID") from None
    if not focal_ok:
        raise ValueError("EXTRACTION_CONTEXT_FOCAL_INVALID")


def _context_request_body(
    self, system_prompt: str, user_json: str, request_id: str
) -> dict[str, Any]:
    """One construction site for the stored context request document."""
    return {
        "system_prompt": system_prompt,
        "user_json": user_json,
        "request_id": request_id,
        "max_tokens": self._max_tokens,
        "json_mode": True,
        "content_sha256": canonical_hash({"system_prompt": system_prompt, "user_json": user_json}),
    }


def _context_wire(
    self, packet: dict, text: str, packet_sha: str, context_graph: Any, display_catalog=None
) -> tuple[str, dict, str]:
    """Build the pinned context wire: system, user data, bound request id.

    The system prompt is always the context profile's prompt — even when
    no block is found, in which case explicitly empty ``context_blocks``
    and ``omitted_source_ids`` are pinned rather than omitted. The request
    id binds the packet hash together with the actual outbound content, so
    a changed context (or changed omissions) addresses a different receipt
    and can never replay this one.
    """
    context_blocks, omitted_source_ids = self._context_for(packet, context_graph)
    system_prompt = _context_system_prompt(
        extraction_context=True, extraction_table_context=self._table_context
    )
    user_data: dict[str, Any] = {
        "tenant_id": packet["tenant_id"],
        "document_version_id": packet["document_version_id"],
        "parse_manifest_id": packet["parse_manifest_id"],
        "source_sha256": packet["source_sha256"],
        "untrusted_document_data": {
            "source_id": packet["untrusted_document_data"]["source_id"],
            "text": text,
            "context_blocks": context_blocks,
            "omitted_source_ids": omitted_source_ids,
        },
    }
    if self._position_order:
        user_data["context_ordering"] = self._context_order_policy()
    system_prompt, user_data = self._display_wire(packet, system_prompt, user_data, display_catalog)
    content_sha = canonical_hash({"system_prompt": system_prompt, "user_data": user_data})
    request_id = str(uuid5(UUID(packet["parse_manifest_id"]), packet_sha + ":" + content_sha))
    user_data = {**user_data, "request_id": request_id}
    return system_prompt, user_data, request_id


def _context_order_policy() -> dict:
    from proofops.application.tagging.preliminary import CONTEXT_POSITION_ORDER

    return CONTEXT_POSITION_ORDER


def _context_for(self, packet: dict, context_graph: Any) -> tuple[list[dict], list[str]]:
    """Bounded, source-bound interpretation-only blocks for this packet's block.

    Reuses the exact same pure helpers as the preliminary path (no
    framework, no duplicated selection logic). The caller verified the
    focal block first; the single match is reasserted here and any
    neighbor-computation integrity error propagates instead of degrading
    to silence. ``([], [])`` is returned ONLY when the verified focal has
    no adjacent/heading blocks, and that emptiness is pinned into the
    stored request by the caller.

    Under ``extraction_table_context`` the focal block's own table row and
    column headers are prepended when — and only when — the canonical graph
    actually resolves an unambiguous table lineage for it. This is the whole
    point of the option: for a table fragment the nearest-neighbour blocks
    are the neighbouring numeric cells, which is exactly the noise that
    made ``9.9억 원``-shaped fragments unjudgeable. Nearest-neighbour blocks
    of a resolved table cell are recorded as omitted rather than sent, and
    an unresolved lineage falls back to the unchanged neighbour context.
    """
    from proofops.application.tagging.preliminary import (
        _bounded_context_blocks,
        _context_entry,
        _position_key,
    )

    data = packet["untrusted_document_data"]
    matches = [block for block in context_graph.blocks if block.source_id == data["source_id"]]
    if len(matches) != 1:
        raise ValueError("EXTRACTION_CONTEXT_FOCAL_INVALID")
    focal = matches[0]
    if self._qc_native_figures:
        from proofops.application.ingest.k6_coverage import native_figure_context_blocks

        native_context = native_figure_context_blocks(focal, context_graph)
        if native_context:
            if sum(len(b.raw_text) + 1 for b in native_context) > self._context_chars:
                raise ExtractionOutputError("QC_NATIVE_FIGURE_CONTEXT_TOO_LARGE")
            return [
                _context_entry(i, b, "parent_paragraph") for i, b in enumerate(native_context)
            ], []
    neighbours, omitted = _bounded_context_blocks(
        context_graph,
        (focal.source_ref(),),
        max_context_chars=self._context_chars,
        max_context_blocks=4,
        position_order=self._position_order,
    )
    if not self._table_context:
        return neighbours, omitted
    from proofops.application.tagging.table_sources import table_structural_sources

    table = table_structural_sources(
        context_graph,
        (focal.source_ref(),),
        tenant_id=packet["tenant_id"],
        max_sources=6,
        max_chars=1000,
    )
    if not table.resolved:
        return neighbours, omitted
    blocks = {block.source_id: block for block in context_graph.blocks}
    axes = [
        _context_entry(index, blocks[item.ref.source_id], "table_" + item.role)
        for index, item in enumerate(table.verified + table.context_only)
        if item.ref.source_id in blocks
    ]
    # Retain declared section/paragraph context: a heading can distinguish
    # a plan from a result. Replace only nearby guesses with table axes.
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    used = 0
    for entry in axes + [b for b in neighbours if b["role"] != "nearby"]:
        if entry["source_id"] in selected_ids:
            continue
        size = len(entry["text"])
        if len(selected) >= 8 or used + size > self._context_chars:
            omitted.append(entry["source_id"])
            continue
        selected.append({**entry, "context_index": len(selected)})
        selected_ids.add(entry["source_id"])
        used += size
    if self._position_order:
        selected.sort(key=lambda entry: _position_key(blocks[entry["source_id"]]))
        selected = [{**entry, "context_index": index} for index, entry in enumerate(selected)]
    omitted_ids = list(
        dict.fromkeys(
            (
                *omitted,
                *table.omitted_source_ids,
                *(
                    entry["source_id"]
                    for entry in neighbours
                    if entry["source_id"] not in selected_ids
                ),
            )
        )
    )
    if self._position_order:
        omitted_ids.sort(key=lambda source_id: _position_key(blocks[source_id]))
    return selected, omitted_ids


def _quotes(payload: Any) -> list:
    if not isinstance(payload, dict) or set(payload) != {"claims"}:
        raise ValueError("claims-only response required")
    claims = payload["claims"]
    if not isinstance(claims, list) or any(
        not isinstance(quote, str) or not quote.strip() for quote in claims
    ):
        raise ValueError("claims array of non-empty strings required")
    return claims


def _locate(quote: str, text: str) -> dict:
    if quote not in text or text.find(quote) != text.rfind(quote):
        raise ValueError("claim quote absent or ambiguous")
    start = text.index(quote)
    return {
        "char_start": start,
        "char_end": start + len(quote),
        "quote": quote,
        "kind": "claim",
        "reason": None,
        "topic_ids": ["environment"],
    }
