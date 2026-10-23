"""Real source-bound Upstage claim extractor (service-integration step 1).

The caller injects and owns the UpstageProbe transport (budget ledger,
credentials, authorization); this module grants no access and reads no
environment. Every packet/request and allowlisted transport response is written to the explicit
receipt directory before quote validation, so failed model content is
retained. Only exact, unique original quotes become spans through the existing
strict validator; grades, labels, offsets, and source-quality approvals are
never invented here.
"""

from __future__ import annotations

import json

# Retain historical module-level imports as compatibility aliases.
import re as re
from collections.abc import Callable as Callable
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn, cast
from uuid import UUID, uuid5

from proofops.adapters.local.upstage import MODEL as UPSTAGE_MODEL
from proofops.adapters.local.upstage import MODEL_PRO4 as MODEL_PRO4
from proofops.adapters.local.upstage import UPSTAGE_TRANSPORT_STOP_CODES
from proofops.adapters.local.upstage import request_usage as _shared_request_usage
from proofops.application.claims import FAILURE_DIAGNOSTICS_POLICY as FAILURE_DIAGNOSTICS_POLICY
from proofops.application.claims import (
    ExtractionOutputError,
    ExtractionProfile,
    ExtractionSpan,
    validate_extraction_response,
)
from proofops.application.ingest.atomic_candidates import atomic_candidates as atomic_candidates
from proofops.application.ingest.table_row_candidates import row_candidates as row_candidates
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json
from proofops.domain.sentences import sentence_spans as sentence_spans
from proofops.domain.values import _require_sha256 as _require_sha256
from proofops.domain.values import _require_uuid as _require_uuid

from proofops_agent.extraction_parts import wire
from proofops_agent.extraction_parts.contracts import (
    _PROVIDER_METADATA_KEYS as _PROVIDER_METADATA_KEYS,
)
from proofops_agent.extraction_parts.contracts import (
    DisplayCatalog,
    DisplayCatalogOption,
    TitleCatalog,
    TitleCatalogOption,
)
from proofops_agent.extraction_parts.profiles import (
    _ASCII_DIGITS as _ASCII_DIGITS,
)
from proofops_agent.extraction_parts.profiles import (
    _ASSERTION_RULE_ENTRY as _ASSERTION_RULE_ENTRY,
)
from proofops_agent.extraction_parts.profiles import (
    _COMPLETE_SELECTION_RULE_ENTRY as _COMPLETE_SELECTION_RULE_ENTRY,
)
from proofops_agent.extraction_parts.profiles import (
    _CONTENT_BOUNDS_RULE_ENTRY as _CONTENT_BOUNDS_RULE_ENTRY,
)
from proofops_agent.extraction_parts.profiles import (
    _CONTEXT_RULE_ENTRY as _CONTEXT_RULE_ENTRY,
)
from proofops_agent.extraction_parts.profiles import (
    _MAX_ATOMIC_CANDIDATES as _MAX_ATOMIC_CANDIDATES,
)
from proofops_agent.extraction_parts.profiles import (
    _MAX_SOURCE_SENTENCES as _MAX_SOURCE_SENTENCES,
)
from proofops_agent.extraction_parts.profiles import (
    _RULE_DESCRIPTOR as _RULE_DESCRIPTOR,
)
from proofops_agent.extraction_parts.profiles import (
    _RULE_DESCRIPTOR_YEAR_NOTATION as _RULE_DESCRIPTOR_YEAR_NOTATION,
)
from proofops_agent.extraction_parts.profiles import (
    _SOURCE_ID_RULE_ENTRY as _SOURCE_ID_RULE_ENTRY,
)
from proofops_agent.extraction_parts.profiles import (
    _TABLE_CONTEXT_RULE_ENTRY as _TABLE_CONTEXT_RULE_ENTRY,
)
from proofops_agent.extraction_parts.profiles import (
    _YEAR_NOTATION_MARK as _YEAR_NOTATION_MARK,
)
from proofops_agent.extraction_parts.profiles import (
    _YEAR_NOTATION_QUOTATION_EXCEPTION as _YEAR_NOTATION_QUOTATION_EXCEPTION,
)
from proofops_agent.extraction_parts.profiles import (
    ASSERTION_SYSTEM_SUFFIX as ASSERTION_SYSTEM_SUFFIX,
)
from proofops_agent.extraction_parts.profiles import ATOMIC_POLICY as ATOMIC_POLICY
from proofops_agent.extraction_parts.profiles import ATOMIC_POLICY_V3 as ATOMIC_POLICY_V3
from proofops_agent.extraction_parts.profiles import (
    ATOMIC_SYSTEM_PROMPT as ATOMIC_SYSTEM_PROMPT,
)
from proofops_agent.extraction_parts.profiles import (
    ATOMIC_V3_SYSTEM_PROMPT as ATOMIC_V3_SYSTEM_PROMPT,
)
from proofops_agent.extraction_parts.profiles import (
    COMPLETE_SELECTION_SYSTEM_SUFFIX as COMPLETE_SELECTION_SYSTEM_SUFFIX,
)
from proofops_agent.extraction_parts.profiles import (
    CONTEXT_SYSTEM_SUFFIX as CONTEXT_SYSTEM_SUFFIX,
)
from proofops_agent.extraction_parts.profiles import (
    LINEWRAP_JOIN_POLICY as LINEWRAP_JOIN_POLICY,
)
from proofops_agent.extraction_parts.profiles import (
    RECALL_SYSTEM_SUFFIX as RECALL_SYSTEM_SUFFIX,
)
from proofops_agent.extraction_parts.profiles import (
    ROW_SYSTEM_SUFFIX as ROW_SYSTEM_SUFFIX,
)
from proofops_agent.extraction_parts.profiles import (
    SOURCE_ID_CONTEXT_SUFFIX as SOURCE_ID_CONTEXT_SUFFIX,
)
from proofops_agent.extraction_parts.profiles import (
    SOURCE_ID_SYSTEM_PROMPT as SOURCE_ID_SYSTEM_PROMPT,
)
from proofops_agent.extraction_parts.profiles import (
    SYSTEM_PROMPT as SYSTEM_PROMPT,
)
from proofops_agent.extraction_parts.profiles import (
    TABLE_CONTEXT_SYSTEM_SUFFIX as TABLE_CONTEXT_SYSTEM_SUFFIX,
)
from proofops_agent.extraction_parts.profiles import (
    _context_system_prompt as _context_system_prompt,
)
from proofops_agent.extraction_parts.profiles import (
    _display_suffix as _display_suffix,
)
from proofops_agent.extraction_parts.profiles import (
    _i3_wire_suffix as _i3_wire_suffix,
)
from proofops_agent.extraction_parts.profiles import (
    _i4_identity_suffix as _i4_identity_suffix,
)
from proofops_agent.extraction_parts.profiles import (
    _is_abbreviated_year_mark as _is_abbreviated_year_mark,
)
from proofops_agent.extraction_parts.profiles import (
    _j8_suffix as _j8_suffix,
)
from proofops_agent.extraction_parts.profiles import (
    _profile as _profile,
)
from proofops_agent.extraction_parts.profiles import (
    _profile_with_options as _profile_with_options,
)
from proofops_agent.extraction_parts.profiles import (
    _profile_with_year_notation as _profile_with_year_notation,
)
from proofops_agent.extraction_parts.profiles import (
    _qc_figure_suffix as _qc_figure_suffix,
)
from proofops_agent.extraction_parts.profiles import (
    _system_prompt as _system_prompt,
)
from proofops_agent.extraction_parts.profiles import (
    _w9_suffix as _w9_suffix,
)
from proofops_agent.extraction_parts.profiles import (
    join_selected_linewraps as join_selected_linewraps,
)
from proofops_agent.extraction_parts.profiles import (
    validate_extraction_response_with_year_notation,
)
from proofops_agent.extraction_parts.profiles import (
    year_notation_unclosed_quotation_ranges as year_notation_unclosed_quotation_ranges,
)
from proofops_agent.extraction_parts.wire import ATOMIC_PROFILE as ATOMIC_PROFILE
from proofops_agent.extraction_parts.wire import ATOMIC_PROFILE_V3 as ATOMIC_PROFILE_V3
from proofops_agent.extraction_parts.wire import ROW_POLICY as ROW_POLICY
from proofops_agent.extraction_parts.wire import ROW_PROFILE as ROW_PROFILE

if TYPE_CHECKING:
    from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
    from proofops.application.rb1_input_isolation import InputIsolation


class UpstageClaimExtractor:
    """ClaimExtractorPort over a caller-owned UpstageProbe with durable receipts."""

    def __init__(
        self,
        probe: Any,
        receipts: Path | str,
        *,
        max_tokens: int = 1024,
        extraction_year_notation: bool = False,
        extraction_context: bool = False,
        extraction_table_context: bool = False,
        extraction_source_ids: bool = False,
        extraction_assertion_prompt: bool = False,
        extraction_complete_selection: bool = False,
        extraction_content_bounds: bool = False,
        position_order: bool = False,
        display_text_profile: str | None = None,
        extraction_atomic: bool = False,
        extraction_atomic_v3: bool = False,
        extraction_failure_diagnostics: bool = False,
        extraction_linewrap_join: bool = False,
        extraction_fragment_guard: bool = False,
        extraction_table_rows: bool = False,
        extraction_recall_prompt: bool = False,
        extraction_pb1: bool = False,
        extraction_pb1_context_guard: bool = False,
        extraction_w9: bool = False,
        extraction_k3: bool = False,
        extraction_sentence_prefix: bool = False,
        extraction_k1: bool = False,
        extraction_table_footnotes: bool = False,
        extraction_located_table_context: bool = False,
        extraction_j3: bool = False,
        extraction_j7: bool = False,
        extraction_j8: bool = False,
        extraction_i3_wire: bool = False,
        extraction_i4_identity: bool = False,
        extraction_h1: bool = False,
        extraction_i5_tables: bool = False,
        extraction_k6: bool = False,
        extraction_q1: bool = False,
        extraction_qt1: bool = False,
        extraction_qc_native_figures: bool = False,
        extraction_fxg_split: bool = False,
        extraction_qt1_goal_split: bool = False,
    ) -> None:
        if type(extraction_q1) is not bool or (extraction_q1 and not extraction_j8):
            raise ValueError("Q1_EXTRACTION_PROFILE_INVALID")
        if type(extraction_k6) is not bool or (extraction_k6 and not extraction_j8):
            raise ValueError("K6_EXTRACTION_PROFILE_INVALID")
        if not callable(getattr(probe, "complete", None)):
            raise ValueError("UPSTAGE_PROBE_REQUIRED")
        if type(extraction_year_notation) is not bool:
            raise ValueError("UPSTAGE_YEAR_NOTATION_INVALID")
        if type(extraction_context) is not bool:
            raise ValueError("UPSTAGE_EXTRACTION_CONTEXT_INVALID")
        if type(position_order) is not bool or (position_order and not extraction_context):
            raise ValueError("UPSTAGE_CONTEXT_ORDER_INVALID")
        if type(extraction_table_context) is not bool or (
            extraction_table_context and not extraction_context
        ):
            raise ValueError("UPSTAGE_EXTRACTION_TABLE_CONTEXT_INVALID")
        if type(extraction_source_ids) is not bool:
            raise ValueError("UPSTAGE_EXTRACTION_SOURCE_IDS_INVALID")
        if type(extraction_assertion_prompt) is not bool or (
            extraction_assertion_prompt and not extraction_source_ids
        ):
            # The assertion suffix only refines source-ID selection; enabling it
            # without source-IDs (or with a non-bool) fails closed before any call.
            raise ValueError("UPSTAGE_EXTRACTION_ASSERTION_PROMPT_INVALID")
        if type(extraction_content_bounds) is not bool or (
            extraction_content_bounds and not extraction_source_ids
        ):
            raise ValueError("UPSTAGE_EXTRACTION_CONTENT_BOUNDS_INVALID")
        if type(extraction_complete_selection) is not bool or (
            extraction_complete_selection
            and not (extraction_source_ids and extraction_assertion_prompt)
        ):
            # Complete-selection requires both source-IDs and assertion-prompt;
            # enabling it without either (or with a non-bool) fails closed.
            raise ValueError("UPSTAGE_EXTRACTION_COMPLETE_SELECTION_INVALID")
        if type(extraction_atomic) is not bool or (extraction_atomic and not extraction_source_ids):
            raise ValueError("UPSTAGE_EXTRACTION_ATOMIC_INVALID")
        if type(extraction_atomic_v3) is not bool or (
            extraction_atomic_v3 and not (extraction_atomic or extraction_table_rows)
        ):
            raise ValueError("UPSTAGE_EXTRACTION_ATOMIC_V3_INVALID")
        if type(extraction_failure_diagnostics) is not bool or (
            extraction_failure_diagnostics and not extraction_source_ids
        ):
            raise ValueError("UPSTAGE_FAILURE_DIAGNOSTICS_INVALID")
        profile = _profile_with_options(
            getattr(probe, "model", UPSTAGE_MODEL),
            year_notation=extraction_year_notation,
            extraction_context=extraction_context,
            extraction_table_context=extraction_table_context,
            source_ids=extraction_source_ids,
            assertion_prompt=extraction_assertion_prompt,
            complete_selection=extraction_complete_selection,
            extraction_content_bounds=extraction_content_bounds,
            position_order=position_order,
            wire_policy_version=getattr(probe, "wire_policy_version", 1),
            display_text_profile=display_text_profile,
            extraction_atomic=extraction_atomic,
            extraction_atomic_v3=extraction_atomic_v3,
            extraction_failure_diagnostics=extraction_failure_diagnostics,
            extraction_linewrap_join=extraction_linewrap_join,
            extraction_fragment_guard=extraction_fragment_guard,
            extraction_table_rows=extraction_table_rows,
            extraction_recall_prompt=extraction_recall_prompt,
            extraction_pb1=extraction_pb1,
            extraction_pb1_context_guard=extraction_pb1_context_guard,
            extraction_w9=extraction_w9,
            extraction_k3=extraction_k3,
            extraction_sentence_prefix=extraction_sentence_prefix,
            extraction_k1=extraction_k1,
            extraction_table_footnotes=extraction_table_footnotes,
            extraction_located_table_context=extraction_located_table_context,
            extraction_j3=extraction_j3,
            extraction_j7=extraction_j7,
            extraction_j8=extraction_j8,
            extraction_i3_wire=extraction_i3_wire,
            extraction_i4_identity=extraction_i4_identity,
            extraction_h1=extraction_h1,
            extraction_i5_tables=extraction_i5_tables,
            extraction_k6=extraction_k6,
            extraction_q1=extraction_q1,
            extraction_qt1=extraction_qt1,
            extraction_qc_native_figures=extraction_qc_native_figures,
            extraction_fxg_split=extraction_fxg_split,
            extraction_qt1_goal_split=extraction_qt1_goal_split,
        )
        if type(max_tokens) is not int or not 1 <= max_tokens <= 4096:
            raise ValueError("UPSTAGE_MAX_TOKENS_INVALID")
        root = Path(receipts)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._probe = probe
        self._receipts = root
        self._max_tokens = max_tokens
        self._profile = profile
        if type(extraction_pb1) is not bool:
            raise ValueError("EXTRACTION_PB1_INVALID")
        if type(extraction_pb1_context_guard) is not bool or (
            extraction_pb1_context_guard and not extraction_pb1
        ):
            raise ValueError("EXTRACTION_PB1_CONTEXT_GUARD_INVALID")
        self._sentence_prefix = extraction_sentence_prefix
        self._k1 = extraction_k1
        self._table_footnotes = extraction_table_footnotes
        self._located_table_context = extraction_located_table_context
        self._pb1_context_guard = extraction_pb1_context_guard
        self._pb1 = extraction_pb1
        self._w9 = extraction_w9
        self._j3 = extraction_j3
        self._k3 = extraction_k3
        self._j7 = extraction_j7
        self._j8 = extraction_j8
        self._k6 = extraction_k6
        self._q1 = extraction_q1
        self._qt1 = extraction_qt1
        self._qc_native_figures = extraction_qc_native_figures
        self._fxg_split = extraction_fxg_split
        self._qt1_goal_split = extraction_qt1_goal_split
        self._i3_wire = extraction_i3_wire
        self._i4_identity = extraction_i4_identity
        self._h1 = extraction_h1
        self._i5_tables = extraction_i5_tables
        self._table_rows = extraction_table_rows
        self._recall_prompt = extraction_recall_prompt
        self._atomic = extraction_atomic
        self._atomic_v3 = extraction_atomic_v3
        self._failure_diagnostics = extraction_failure_diagnostics
        self._linewrap_join = extraction_linewrap_join
        self._fragment_guard = extraction_fragment_guard
        self._year_notation = extraction_year_notation
        self._context = extraction_context
        self._table_context = extraction_table_context
        self._source_ids = extraction_source_ids
        self._assertion_prompt = extraction_assertion_prompt
        self._complete_selection = extraction_complete_selection
        self._content_bounds = extraction_content_bounds
        self._position_order = position_order
        self._display_text_profile = display_text_profile
        self._context_chars = 512 if getattr(probe, "wire_policy_version", 1) == 2 else 2000
        self._request_ids: list[tuple[str, str]] = []

    def _validate_spans(self, payload: dict[str, Any], text: str) -> tuple[ExtractionSpan, ...]:
        """Validate spans with this extractor's own pinned policy.

        The live path and the receipt-replay path both funnel through here, so
        a stored receipt can only ever be served under the same validator that
        wrote it.
        """
        if self._year_notation:
            return validate_extraction_response_with_year_notation(payload, text)
        return validate_extraction_response(payload, text, reject_unclosed_quotations=True)

    @property
    def profile(self) -> ExtractionProfile:
        return self._profile

    def usage_checkpoint(self) -> int:
        return len(self._request_ids)

    def cumulative_usage(
        self, *, since: int = 0, parse_manifest_id: str | None = None
    ) -> dict[str, Any]:
        """Read only this operation's request IDs from the actual shared ledger."""
        identifiers = [
            identifier
            for manifest, identifier in self._request_ids[since:]
            if parse_manifest_id is None or manifest == parse_manifest_id
        ]
        ledger = getattr(self._probe, "ledger", None)
        try:
            result = _shared_request_usage(ledger, identifiers)
        except (ValueError, TypeError):
            raise ValueError("ACCOUNTING_UNAVAILABLE") from None
        # Caller-specific alias for compatibility; shared query owns model_calls.
        result["extractor_calls"] = result["model_calls"]
        return result

    @property
    def usage(self) -> dict[str, Any]:
        return self.cumulative_usage()

    def extract(
        self,
        packet: dict[str, Any],
        *,
        context_graph: Any = None,
        display_catalog: DisplayCatalog | None = None,
        h1_title_catalog: TitleCatalog | None = None,
    ) -> dict[str, Any]:
        result = self._extract(
            packet,
            context_graph=context_graph,
            display_catalog=display_catalog,
            h1_title_catalog=h1_title_catalog,
        )
        if not self._qt1 or packet["untrusted_document_data"]["kind"] != "table":
            return result
        self._validate_context_graph(packet, context_graph)
        from proofops.application.ingest.qt1_tables import candidates_for, reconcile

        data = packet["untrusted_document_data"]
        block = next(b for b in context_graph.blocks if b.source_id == data["source_id"])
        # External package helper is untyped; its annotations are outside this scope.
        candidates = candidates_for(block, context_graph)  # type: ignore[no-untyped-call]
        # External package helper is untyped; its annotations are outside this scope.
        spans, coverage = reconcile(data["text"], candidates, result["spans"])  # type: ignore[no-untyped-call]
        try:
            self._validate_spans({"spans": spans}, data["text"])
        except ValueError:
            # Recovered table spans pass the same quote/offset guards as model
            # spans. A rejected table remains unknown without losing siblings.
            # Identity, grid and immutable receipt checks stay outside this catch.
            raise ExtractionOutputError(
                "TABLE_QT1_SPAN_INVALID", failure_code="TABLE_QT1_SPAN_INVALID"
            ) from None
        record = dict(
            packet=packet,
            profile=asdict(self.profile),
            candidates=candidates,
            coverage=coverage,
            before=result,
            after=dict(spans=spans),
        )
        path = self._receipts / (
            "qt1-"
            + canonical_hash(
                dict(packet=packet, profile=asdict(self.profile), candidates=candidates)
            )
            + ".json"
        )
        encoded = canonical_json(record)
        if path.exists():
            if path.read_text() != encoded:
                raise ValueError("QT1_EXTRACTION_REPLAY_MISMATCH")
        else:
            self._write(path, encoded)
        return {"spans": spans}

    def _extract(
        self,
        packet: dict[str, Any],
        *,
        context_graph: Any = None,
        display_catalog: DisplayCatalog | None = None,
        h1_title_catalog: TitleCatalog | None = None,
    ) -> dict[str, Any]:
        """Extract atomic claims from ``packet``'s own text only.

        Production context path (R03f): when this extractor was built with
        ``extraction_context=True``, a validated ``context_graph`` is
        REQUIRED. The graph's tenant/document_version/parse_manifest/
        source_sha256 identity is verified against the packet before any
        receipt is touched or any call is made; the actual system prompt,
        user content, context blocks *and omissions* are hash-bound into a
        context-profile request identity, so a changed context can never
        replay an old receipt. An explicitly empty context (block not found)
        is still served under the context profile with empty blocks pinned in
        the stored request — never silently as legacy. Returned claim spans
        are still located and validated against the packet's own ``text``
        alone; context can never become a claim span.

        Legacy path (``extraction_context=False``): ``context_graph`` must be
        ``None`` and the wire is byte-identical to the pre-context behaviour
        under the legacy profile. ``context_graph`` default ``None``
        reproduces that legacy behaviour exactly.

        Source-ID path (R14, ``extraction_source_ids=True``): the source text
        is sent already split into locally minted ``source_id:index``
        sentences and the model may return only those identifiers. Spans are
        restored from this process's own offsets, so a model that would have
        retyped ``2023 년`` as ``2023년`` can no longer lose the sentence. The
        restored spans still pass the same frozen span validator, and the
        selection is a whole source sentence: atomicity stays unreviewed.
        Works with or without the context option; a graph is required exactly
        when the context option is on.
        """
        text = self._packet_text(packet)
        if self._h1 and h1_title_catalog is not None:
            self._validate_context_graph(packet, h1_title_catalog.graph)
            packet = packet | {
                "h1_native_title": h1_title_catalog.proof(
                    packet["untrusted_document_data"]["source_id"]
                )
            }
        if self._w9 and packet["untrusted_document_data"]["kind"] == "figure":
            return {"spans": []}
        if self._pb1 and packet["untrusted_document_data"]["kind"] == "table":
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

                # External package helper is untyped; its annotations are outside this scope.
                raw_rows = observations_for(block, context_graph)  # type: ignore[no-untyped-call]
            else:
                # External package helper is untyped; its annotations are outside this scope.
                raw_rows = observations(text, context=context)  # type: ignore[no-untyped-call]
            rows = raw_rows
            if self._table_footnotes:
                from proofops.application.tagging.dec24 import table_footnote

                # External package helper is untyped; its annotations are outside this scope.
                rows = [r for r in raw_rows if not table_footnote(r["quote"], kind="table")]  # type: ignore[no-untyped-call]
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

                result["spans"], boundary_records = trim_table_labels(
                    result["spans"], text, kind="table"
                )
            self._validate_spans(result, text)
            directory = self._receipts / (
                "pb1-" + canonical_hash({"packet": packet, "policy": self._profile.rule_sha256})
                if self._w9
                else "pb1-" + canonical_hash(packet)
            )
            if not directory.exists():
                directory.mkdir(mode=0o700)
                self._write(directory / "packet.json", canonical_json(packet))
                self._write(directory / "observations.json", canonical_json(raw_rows))
                if self._k1:
                    self._write(directory / "k1-boundaries.json", canonical_json(boundary_records))
                if self._table_footnotes:
                    self._write(
                        directory / "table-context-exclusions.json",
                        canonical_json([r for r in raw_rows if r not in rows]),
                    )
                self._write(directory / "result.json", canonical_json(result))
            elif json.loads((directory / "result.json").read_text()) != result:
                raise ValueError("EXTRACTION_PB1_REPLAY_MISMATCH")
            if rows or any(
                "\t" in line
                and any(
                    __import__("re").fullmatch(r"20\d{2}(?:년)?", c.strip())
                    for c in line.split("\t")
                )
                for line in text.split("\n")[:4]
            ):
                return result
        if self._display_text_profile:
            if display_catalog is None:
                raise ValueError("DISPLAY_CATALOG_REQUIRED")
            self._validate_context_graph(packet, display_catalog.graph)
            pin = display_catalog.block_pin(packet["untrusted_document_data"]["source_id"])
            if pin["raw_sha256"] != canonical_hash(text):
                raise ValueError("DISPLAY_RAW_TEXT_MISMATCH")
            context_pins = []
            if self._context:
                if context_graph is None:
                    raise ValueError("EXTRACTION_CONTEXT_REQUIRED")
                blocks, _ = self._context_for(packet, context_graph)
                context_pins = [display_catalog.block_pin(b["source_id"]) for b in blocks]
            packet = packet | {"display_text": pin, "display_text_context": context_pins}
        elif display_catalog is not None or "display_text" in packet:
            raise ValueError("DISPLAY_PROFILE_REQUIRED")
        packet_sha = canonical_hash(packet)
        if self._source_ids:
            self._require_graph(packet, context_graph)
            system_prompt, user_data, request_id = self._source_id_wire(
                packet, text, packet_sha, context_graph, display_catalog
            )
            user_json = json.dumps(
                user_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            request_body = self._context_request_body(system_prompt, user_json, request_id)
        elif self._context:
            if context_graph is None:
                raise ValueError("EXTRACTION_CONTEXT_REQUIRED")
            self._validate_context_graph(packet, context_graph)
            system_prompt, user_data, request_id = self._context_wire(
                packet, text, packet_sha, context_graph, display_catalog
            )
            user_json = json.dumps(
                user_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            request_body = self._context_request_body(system_prompt, user_json, request_id)
        else:
            if context_graph is not None and not self._display_text_profile:
                raise ValueError("EXTRACTION_CONTEXT_UNEXPECTED")
            request_id = str(uuid5(UUID(packet["parse_manifest_id"]), packet_sha))
            system_prompt = SYSTEM_PROMPT
            user_payload: dict[str, Any] = {
                "tenant_id": packet["tenant_id"],
                "document_version_id": packet["document_version_id"],
                "parse_manifest_id": packet["parse_manifest_id"],
                "source_sha256": packet["source_sha256"],
                "request_id": request_id,
                "untrusted_document_data": {
                    "source_id": packet["untrusted_document_data"]["source_id"],
                    "text": text,
                },
            }
            system_prompt, user_payload = self._display_wire(
                packet, system_prompt, user_payload, display_catalog
            )
            user_json = json.dumps(
                user_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            request_body = {
                "system_prompt": system_prompt,
                "user_json": user_json,
                "request_id": request_id,
                "max_tokens": self._max_tokens,
                "json_mode": True,
            }
        if self._fxg_split and user_data["untrusted_document_data"]["source_sentences"]:
            from proofops_agent.fxg_extraction import extract_parts, plan

            parts = plan(self._probe, system_prompt, user_data, max_tokens=self._max_tokens)
            if len(parts) > 1:
                return extract_parts(
                    self, packet, system_prompt, user_data, parts, context_graph=context_graph
                )
        directory = self._receipts / request_id
        if (
            self._fxg_split
            and user_data["untrusted_document_data"]["source_sentences"]
            and not directory.exists()
        ):
            from proofops.application.ingest.fxg_wire import before_dispatch

            # External package helper is untyped; its annotations are outside this scope.
            before_dispatch()  # type: ignore[no-untyped-call]
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            return self._replay_receipt(
                directory,
                packet,
                packet_sha,
                request_id,
                context_graph,
                display_catalog,
                request_body,
            )
        self._write(directory / "packet.json", canonical_json(packet))
        self._write(directory / "request.json", canonical_json(request_body))
        from proofops.adapters.local.openrouter import OpenRouterProbe

        if isinstance(self._probe, OpenRouterProbe):
            WIRE_POLICY: dict[str, Any]
            from proofops.adapters.local.openrouter import WIRE_POLICY

            if self._probe.model == "gpt-6-luna":
                from proofops.adapters.local.openai import WIRE_POLICY
            self._write(
                directory / "identity.json",
                canonical_json(
                    {
                        "provider": "openai" if self._probe.model == "gpt-6-luna" else "openrouter",
                        "model": self._probe.model,
                        "model_sha256": self._profile.model_sha256,
                        "prompt_sha256": self._profile.prompt_sha256,
                        **(
                            {
                                "wire_policy": WIRE_POLICY,
                                "context_budget_chars": self._context_chars,
                            }
                            if self._probe.wire_policy_version == 2
                            else {}
                        ),
                    }
                ),
            )
        local_empty = (self._atomic or self._table_rows) and not user_data[
            "untrusted_document_data"
        ]["source_sentences"]
        if self._atomic:
            self._write(
                directory / "candidate_diagnostics.json",
                canonical_json(
                    {
                        **user_data["untrusted_document_data"]["candidate_diagnostics"],
                        "model_call_skipped": local_empty,
                    }
                ),
            )
        if not local_empty:
            self._request_ids.append((packet["parse_manifest_id"], request_id))
        try:
            schema: dict[str, Any] = (
                {
                    "type": "object",
                    "properties": {"sentence_ids": {"type": "array", "items": {"type": "string"}}},
                    "required": ["sentence_ids"],
                    "additionalProperties": False,
                }
                if self._source_ids
                else {
                    "type": "object",
                    "properties": {"claims": {"type": "array", "items": {"type": "string"}}},
                    "required": ["claims"],
                    "additionalProperties": False,
                }
            )
            if self._i4_identity:
                selectors = [
                    e["sentence_id"]
                    for e in user_data["untrusted_document_data"]["source_sentences"]
                ]
                if selectors:
                    schema["properties"]["sentence_ids"].update(
                        uniqueItems=True, maxItems=len(selectors)
                    )
                    schema["properties"]["sentence_ids"]["items"] = {"enum": selectors}
            result = (
                {"provider": "local", "content": '{"sentence_ids":[]}'}
                if local_empty
                else self._probe.complete(
                    system_prompt,
                    user_json,
                    request_id=request_id,
                    max_tokens=self._max_tokens,
                    json_mode=True,
                    **(
                        {"schema_json": json.dumps(schema)}
                        if isinstance(self._probe, OpenRouterProbe)
                        else {}
                    ),
                )
            )
        except Exception as error:
            code = str(error) if isinstance(error, ValueError) else ""
            # These guards run before reservation. In particular a duplicate ID
            # must not make this operation inherit an older operation's spend.
            if code in {
                "DUPLICATE_PROBE_REQUEST",
                "PRICE_RECHECK_REQUIRED",
                "BUDGET_EXHAUSTED",
                "BUDGET_POLICY_MISMATCH",
                "PROBE_REQUEST_TOO_LARGE",
                "INVALID_PROBE_REQUEST",
            }:
                self._request_ids.remove((packet["parse_manifest_id"], request_id))
            self._fail(directory, packet_sha, request_id, code, transport=True)
        metadata = (
            {key: result[key] for key in (*_PROVIDER_METADATA_KEYS, "content") if key in result}
            if isinstance(result, dict)
            else {"invalid_transport_type": type(result).__name__}
        )
        self._write(directory / "raw_response.json", canonical_json(metadata))
        if isinstance(result, dict) and result.get("schema_valid") is False:
            self._fail(directory, packet_sha, request_id, "MODEL_SCHEMA_INVALID")
        if not isinstance(result, dict) or not isinstance(result.get("content"), str):
            self._fail(directory, packet_sha, request_id, "MODEL_SCHEMA_INVALID")
        try:
            payload = json.loads(result["content"])
            spans, rejected = self._resolve_payload(
                payload,
                text,
                packet["untrusted_document_data"]["source_id"],
                packet.get("display_text"),
                packet=packet,
                context_graph=context_graph,
            )
        except (ValueError, TypeError) as error:
            # Public error compatibility is unchanged. New-policy receipts keep
            # a bounded diagnostic code, never arbitrary exception/source text.
            code = (
                "MODEL_JSON_INVALID"
                if isinstance(error, json.JSONDecodeError)
                else "MODEL_SELECTOR_INVALID"
                if str(error) == "unknown or repeated sentence id"
                else "MODEL_SPAN_INVALID"
            )
            self._fail(directory, packet_sha, request_id, code)
        resolved = [
            {
                "char_start": span.char_start,
                "char_end": span.char_end,
                "quote": span.quote,
                "kind": span.kind,
                "reason": span.reason,
                "topic_ids": list(span.topic_ids),
            }
            for span in spans
        ]
        self._write(
            directory / "result.json",
            canonical_json(
                {
                    "request_id": request_id,
                    "packet_sha256": packet_sha,
                    "profile": asdict(self._profile),
                    "provider_model": metadata.get("provider_model"),
                    "response_sha256": metadata.get("response_sha256"),
                    "content_sha256": canonical_hash(result["content"]),
                    "spans": resolved,
                    **rejected,
                    **(
                        {"context_ordering": self._context_order_policy()}
                        if self._position_order
                        else {}
                    ),
                }
            ),
        )
        return {"spans": resolved}

    def _replay_receipt(
        self,
        directory: Path,
        packet: dict[str, Any],
        packet_sha: str,
        request_id: str,
        context_graph: Any = None,
        display_catalog: DisplayCatalog | None = None,
        expected_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Reuse an existing receipt for this exact packet; never re-issue its call.

        A retained receipt means the provider request for this packet was already
        made, so repeating it could be charged twice. The stored packet must be
        byte-identical to this one and its profile must match before anything is
        reused; otherwise the old refusal stands. In order:

        * ``failure.json`` -- the stored failure is raised again, deterministically;
        * ``raw_response.json`` -- required for any model result (missing raw cannot
          claim a model result); quotes are always reconstructed and validated from
          raw provider content;
        * ``result.json`` -- if present, must match identity and equal the
          reconstructed validated spans identically; a forged or mismatched result
          is refused;
        * nothing retained -- raises ``EXTRACTION_RECEIPT_UNSETTLED`` and leaves
          reconciliation to the ledger instead of guessing.

        No provider call, reservation or usage entry is created on this path.
        In context mode the graph is required again and the stored request is
        byte-compared against the recomputed wire first: a changed context
        addresses a different receipt directory already, and any tampering
        with the stored request fails closed here.
        """
        text = self._packet_text(packet)
        if self._display_text_profile:
            request_path = directory / "request.json"
            if (
                expected_body is None
                or not request_path.is_file()
                or request_path.read_text(encoding="utf-8") != canonical_json(expected_body)
            ):
                raise ValueError("EXTRACTION_RECEIPT_EXISTS")
        if self._source_ids:
            self._require_graph(packet, context_graph)
            system_prompt, user_data, recomputed_id = self._source_id_wire(
                packet, text, packet_sha, context_graph, display_catalog
            )
            if recomputed_id != request_id:
                raise ValueError("EXTRACTION_RECEIPT_EXISTS")
            user_json = json.dumps(
                user_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            expected_body = self._context_request_body(system_prompt, user_json, request_id)
            request_path = directory / "request.json"
            if not request_path.is_file() or request_path.read_text(
                encoding="utf-8"
            ) != canonical_json(expected_body):
                raise ValueError("EXTRACTION_RECEIPT_EXISTS")
        elif self._context:
            if context_graph is None:
                raise ValueError("EXTRACTION_CONTEXT_REQUIRED")
            self._validate_context_graph(packet, context_graph)
            system_prompt, user_data, recomputed_id = self._context_wire(
                packet, text, packet_sha, context_graph, display_catalog
            )
            if recomputed_id != request_id:
                raise ValueError("EXTRACTION_RECEIPT_EXISTS")
            user_json = json.dumps(
                user_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            expected_body = self._context_request_body(system_prompt, user_json, request_id)
            request_path = directory / "request.json"
            if not request_path.is_file() or request_path.read_text(
                encoding="utf-8"
            ) != canonical_json(expected_body):
                raise ValueError("EXTRACTION_RECEIPT_EXISTS")
        elif context_graph is not None and not self._display_text_profile:
            raise ValueError("EXTRACTION_CONTEXT_UNEXPECTED")
        failure_path = directory / "failure.json"
        if failure_path.is_file():
            stored = json.loads(failure_path.read_text(encoding="utf-8"))
            if stored.get("packet_sha256") != packet_sha or (
                (self._context or self._source_ids) and stored.get("request_id") != request_id
            ):
                raise ValueError("EXTRACTION_RECEIPT_EXISTS")
            error = stored.get("error")
            from proofops.application.provider_resilience import ISOLATED_CODES

            if getattr(self._probe, "provider_resilience", None) and error in ISOLATED_CODES:
                raise ExtractionOutputError(error)
            if error in {"UPSTAGE_REQUEST_FAILED", "UPSTREAM_UNAVAILABLE"}:
                # A fresh network failure still stops its batch in _fail. On an
                # explicit continuation, retain this source as failed/unknown
                # without repeating its possibly billed call or halting every
                # later source. Budget/auth/integrity stops remain unchanged.
                raise ExtractionOutputError(
                    "PREVIOUS_TRANSPORT_FAILED",
                    failure_code=(
                        stored.get("reason_code") or error if self._failure_diagnostics else None
                    ),
                )
            if error in UPSTAGE_TRANSPORT_STOP_CODES:
                if self._recorded_truncation(directory, request_id, error):
                    raise ExtractionOutputError("MODEL_OUTPUT_TRUNCATED")
                raise ValueError(error)
            raise ExtractionOutputError(
                error or "MODEL_SPAN_OR_SCHEMA_INVALID",
                failure_code=(stored.get("reason_code") if self._failure_diagnostics else None),
            )

        # Missing raw cannot claim model result
        raw_path = directory / "raw_response.json"
        if not raw_path.is_file():
            raise ValueError("EXTRACTION_RECEIPT_UNSETTLED")

        # Validate packet and request identity in both raw/result paths
        stored_packet = directory / "packet.json"
        if not stored_packet.is_file() or stored_packet.read_text(
            encoding="utf-8"
        ) != canonical_json(packet):
            raise ValueError("EXTRACTION_RECEIPT_EXISTS")

        request_path = directory / "request.json"
        if not request_path.is_file():
            raise ValueError("EXTRACTION_RECEIPT_UNSETTLED")
        try:
            stored_req = json.loads(request_path.read_text(encoding="utf-8"))
            if stored_req.get("request_id") != request_id:
                raise ValueError("EXTRACTION_RECEIPT_EXISTS")
        except (ValueError, UnicodeDecodeError):
            raise ValueError("EXTRACTION_RECEIPT_UNSETTLED")

        try:
            metadata = json.loads(raw_path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("EXTRACTION_RECEIPT_UNSETTLED")
        if not isinstance(metadata, dict) or not isinstance(metadata.get("content"), str):
            raise ValueError("EXTRACTION_RECEIPT_UNSETTLED")

        # Reconstruct and validate spans strictly from the raw model response
        text = self._packet_text(packet)
        try:
            payload = json.loads(metadata["content"])
            spans, rejected = self._resolve_payload(
                payload,
                text,
                packet["untrusted_document_data"]["source_id"],
                packet.get("display_text"),
                packet=packet,
                context_graph=context_graph,
            )
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            raise ExtractionOutputError("MODEL_SPAN_OR_SCHEMA_INVALID") from None

        resolved = [
            {
                "char_start": span.char_start,
                "char_end": span.char_end,
                "quote": span.quote,
                "kind": span.kind,
                "reason": span.reason,
                "topic_ids": list(span.topic_ids),
            }
            for span in spans
        ]

        result_path = directory / "result.json"
        if result_path.is_file():
            try:
                stored_result = json.loads(result_path.read_text(encoding="utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise ValueError("EXTRACTION_RECEIPT_EXISTS")
            if (
                stored_result.get("request_id") != request_id
                or stored_result.get("packet_sha256") != packet_sha
                or stored_result.get("profile") != asdict(self._profile)
                or (
                    self._position_order
                    and stored_result.get("context_ordering") != self._context_order_policy()
                )
                or (
                    self._j3
                    and any(
                        stored_result.get(key) != rejected.get(key)
                        for key in (
                            ("j7_refinements", "j7_refinement_rejected")
                            if self._j7
                            else ("j3_refinements", "j3_refinement_rejected")
                        )
                    )
                )
                or not isinstance(stored_result.get("spans"), list)
                or stored_result.get("spans") != resolved
            ):
                raise ValueError("EXTRACTION_RECEIPT_EXISTS")
            return {"spans": resolved}

        try:
            self._write(
                directory / "result.json",
                canonical_json(
                    {
                        "request_id": request_id,
                        "packet_sha256": packet_sha,
                        "profile": asdict(self._profile),
                        "provider_model": metadata.get("provider_model"),
                        "response_sha256": metadata.get("response_sha256"),
                        "content_sha256": canonical_hash(metadata["content"]),
                        "spans": resolved,
                        **rejected,
                        **(
                            {"context_ordering": self._context_order_policy()}
                            if self._position_order
                            else {}
                        ),
                    }
                ),
            )
        except FileExistsError:
            pass
        return {"spans": resolved}

    # Keep the public method surface while sharing one pure wire/resolver implementation.
    _require_graph = wire._require_graph
    _resolve_payload = wire._resolve_payload
    _resolve_sentence_ids = wire._resolve_sentence_ids
    _sentence_index = staticmethod(wire._sentence_index)
    _atomic_entries = wire._atomic_entries
    _row_entries = wire._row_entries
    _source_id_wire = wire._source_id_wire
    _display_wire = wire._display_wire
    _packet_text = wire._packet_text
    _validate_context_graph = staticmethod(wire._validate_context_graph)
    _context_request_body = wire._context_request_body
    _context_wire = wire._context_wire
    _context_order_policy = staticmethod(wire._context_order_policy)
    _context_for = wire._context_for
    _quotes = staticmethod(wire._quotes)
    _locate = staticmethod(wire._locate)

    @staticmethod
    def _write(path: Path, content: str) -> None:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(content)
        path.chmod(0o400)

    def _fail(
        self,
        directory: Path,
        packet_sha: str,
        request_id: str,
        code: str,
        *,
        transport: bool = False,
    ) -> NoReturn:
        if transport:
            error = code if code in UPSTAGE_TRANSPORT_STOP_CODES else "UPSTREAM_UNAVAILABLE"
            from proofops.application.provider_resilience import ISOLATED_CODES

            if getattr(self._probe, "provider_resilience", None) and code in ISOLATED_CODES:
                error = code
        else:
            error = "MODEL_SPAN_OR_SCHEMA_INVALID"
        self._write(
            directory / "failure.json",
            canonical_json(
                {"request_id": request_id, "packet_sha256": packet_sha, "error": error}
                | (
                    {"reason_code": code}
                    if (self._located_table_context or self._failure_diagnostics)
                    and not transport
                    and code
                    in {
                        "MODEL_JSON_INVALID",
                        "MODEL_SCHEMA_INVALID",
                        "MODEL_SELECTOR_INVALID",
                        "MODEL_SPAN_INVALID",
                    }
                    else {}
                )
            ),
        )
        if transport:
            if getattr(self._probe, "provider_resilience", None) and code in ISOLATED_CODES:
                raise ExtractionOutputError(
                    error, failure_code=code if self._failure_diagnostics else None
                )
            if self._recorded_truncation(directory, request_id, error):
                raise ExtractionOutputError(
                    "MODEL_OUTPUT_TRUNCATED",
                    failure_code=code if self._failure_diagnostics else None,
                )
            raise ValueError(error)
        raise ExtractionOutputError(error, failure_code=code if self._failure_diagnostics else None)

    def _recorded_truncation(self, directory: Path, request_id: str, error: str) -> bool:
        if error != "UPSTAGE_RECEIPT_INVALID_RESERVATION_RETAINED":
            return False
        check = getattr(self._probe, "is_recorded_output_truncation", None)
        if check is None:
            return False
        try:
            request = json.loads((directory / "request.json").read_text())
            return check(request, request_id=request_id) is True
        except (OSError, ValueError, TypeError):
            return False


class GraphBoundExtractor:
    """Thin ClaimExtractorPort adapter binding one graph to a context extractor.

    Discovery loops (``discover_atomic_claims``) call ``extract(packet)`` with
    no room for per-call context, so the runner wraps its context-mode
    extractor with the run's own graph once. Only a context-mode
    ``UpstageClaimExtractor`` can be wrapped — anything else fails closed at
    construction, never silently at call time. Profile and usage surface are
    the inner extractor's own.
    """

    def __init__(
        self,
        inner: UpstageClaimExtractor,
        graph: CanonicalDocumentGraph,
        source: bytes | None = None,
        *,
        display_prefetch_workers: int = 1,
        rb1: InputIsolation | None = None,
    ) -> None:
        if not (
            getattr(inner, "_context", False) or getattr(inner, "_display_text_profile", None)
        ) or not callable(getattr(inner, "extract", None)):
            raise ValueError("UPSTAGE_CONTEXT_EXTRACTOR_REQUIRED")
        if type(display_prefetch_workers) is not int or not 1 <= display_prefetch_workers <= 4:
            raise ValueError("DISPLAY_PREFETCH_WORKERS_INVALID")
        self._display_prefetch_workers = display_prefetch_workers
        self._rb1 = rb1
        self._inner = inner
        self._graph = graph
        self.native_figure_receipt = None
        if getattr(inner, "_qc_native_figures", False):
            if source is None:
                raise ValueError("QC_NATIVE_FIGURE_SOURCE_REQUIRED")
            from proofops.adapters.local.h1_native_title import native_figure_candidates

            self._graph, self.native_figure_receipt = native_figure_candidates(graph, source)
            graph = self._graph
        self._display_catalog: DisplayCatalog | None = None
        self._h1_title_catalog: TitleCatalog | None = None
        if getattr(inner, "_h1", False) and source is not None:
            from proofops.adapters.local.h1_native_title import NativeTitleCatalog

            self._h1_title_catalog = NativeTitleCatalog(graph, source)
        if getattr(inner, "_display_text_profile", None) and source is not None:
            from proofops.adapters.local.glyph_display_text import GlyphDisplayCatalog

            self._display_catalog = GlyphDisplayCatalog(graph, source)

    def prefetch(self, packets: list[dict[str, Any]]) -> None:
        if self._display_catalog is None or self._display_prefetch_workers == 1:
            return
        blocks = {b.source_id: b for b in self._graph.blocks}
        selected: set[str] = set()
        for packet in packets:
            # Keep packet and focal identity checks before the optional CPU work.
            self._inner._packet_text(packet)
            self._inner._validate_context_graph(packet, self._graph)
            sid = packet["untrusted_document_data"]["source_id"]
            if self._rb1 is not None and sid in self._rb1.failures:
                continue
            if self._inner._context:
                try:
                    context, _ = self._inner._context_for(packet, self._graph)
                except ValueError as error:
                    # External package helper is untyped; its annotations are outside this scope.
                    if self._rb1 is None or not self._rb1.capture(sid, error):  # type: ignore[no-untyped-call]
                        raise
                    continue
                selected.update(b["source_id"] for b in context)
            selected.add(sid)
        pages = {
            blocks[sid].page_num
            for sid in selected
            if blocks[sid].winner is not None
            and blocks[sid].bbox is not None
            and " " in blocks[sid].raw_text
        }
        self._display_catalog.prefetch_pages(pages, max_workers=self._display_prefetch_workers)

    @property
    def graph(self) -> CanonicalDocumentGraph:
        """Use this derived graph for discovery under the explicit QC profile."""
        return self._graph

    @property
    def profile(self) -> ExtractionProfile:  # ClaimExtractorPort: frozen discovery reads this.
        return self._inner.profile

    def extract(self, packet: dict[str, Any]) -> dict[str, Any]:
        if self._rb1 is not None and self._rb1.active:
            sid = packet["untrusted_document_data"]["source_id"]
            if sid in self._rb1.failures:
                self._inner._packet_text(packet)
                self._inner._validate_context_graph(packet, self._graph)
                # External package helper is untyped; its annotations are outside this scope.
                self._rb1.check(sid)  # type: ignore[no-untyped-call]
        if getattr(self._inner, "_display_text_profile", None) and self._display_catalog is None:
            raise ExtractionOutputError("DISPLAY_SOURCE_UNAVAILABLE")
        try:
            return self._inner.extract(
                packet,
                context_graph=self._graph,
                **cast(
                    TitleCatalogOption,
                    (
                        {"h1_title_catalog": self._h1_title_catalog}
                        if self._h1_title_catalog is not None
                        else {}
                    ),
                ),
                **cast(
                    DisplayCatalogOption,
                    (
                        {"display_catalog": self._display_catalog}
                        if self._display_catalog is not None
                        else {}
                    ),
                ),
            )
        except ValueError as error:
            # External package helper is untyped; its annotations are outside this scope.
            if self._rb1 is not None and self._rb1.capture(  # type: ignore[no-untyped-call]
                packet["untrusted_document_data"]["source_id"], error
            ):
                # External package helper is untyped; its annotations are outside this scope.
                self._rb1.check(packet["untrusted_document_data"]["source_id"])  # type: ignore[no-untyped-call]
            if (
                getattr(self._inner, "_i5_tables", False)
                and getattr(self._inner, "_j8", False)
                and packet.get("untrusted_document_data", {}).get("kind") == "table"
                and str(error) in {"J8_GRID_MISSING", "J8_GRID_INVALID", "J8_GRID_OVERLAP"}
            ):
                # ClaimDiscovery records a failed source and an unknown exclusion;
                # no empty/non-claim result or invented cell/evidence is admitted.
                raise ExtractionOutputError("TABLE_GRID_UNREADABLE") from None
            raise
