"""Immutable parser orchestration and compatible isolated-child entrypoint.

ODL/pdfplumber run in a bounded subprocess. Candidate conversion, stored
artifacts and the child implementation live in ``odl_parts``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import replace
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from typing import Any
from uuid import uuid4

from proofops.adapters.parsing.odl_parts import artifacts, candidates, child, runtime
from proofops.adapters.parsing.odl_parts.candidates import (
    _geometry as _geometry,
)
from proofops.adapters.parsing.odl_parts.candidates import (
    _node_text as _node_text,
)
from proofops.adapters.parsing.odl_parts.candidates import (
    _transform_box as _transform_box,
)
from proofops.adapters.parsing.odl_parts.candidates import (
    _with_quality_issues as _with_quality_issues,
)
from proofops.adapters.parsing.odl_parts.common import (
    ParseFailure as ParseFailure,
)
from proofops.adapters.parsing.odl_parts.common import (
    _json as _json,
)
from proofops.adapters.parsing.odl_parts.common import (
    _output_bytes as _output_bytes,
)
from proofops.adapters.parsing.odl_parts.policies import (
    _local_pages as _local_pages,
)
from proofops.adapters.parsing.odl_parts.policies import (
    _locates_auxiliary_cells as _locates_auxiliary_cells,
)
from proofops.adapters.parsing.odl_parts.policies import (
    _table_verifier as _table_verifier,
)
from proofops.adapters.parsing.odl_parts.runtime import (
    _check_limits as _check_limits,
)
from proofops.adapters.parsing.odl_parts.runtime import (
    _child_environment as _child_environment,
)
from proofops.adapters.parsing.odl_parts.runtime import (
    _child_limits as _child_limits,
)
from proofops.adapters.parsing.odl_parts.runtime import (
    _cleanup_parser_work as _cleanup_parser_work,
)
from proofops.adapters.parsing.odl_parts.runtime import (
    _parser_work_directory as _parser_work_directory,
)
from proofops.adapters.parsing.windows_isolation import kill_and_reap, process_isolation
from proofops.application.ingest.graph_fusion import (
    CandidateBatch,
    CanonicalDocumentGraph,
    ParserProfile,
    SourceArtifact,
    fuse_candidates,
)
from proofops.application.ingest.graph_fusion import (
    candidates_from_snapshot as candidates_from_snapshot,
)
from proofops.application.ports.parsing import ParserPort
from proofops.application.uploads_security import PdfLimits, QuarantinedPdf, verify_quarantined_pdf
from proofops.domain.errors import DomainValidationError


def _batch(
    raw: dict,
    geometries: dict,
    source: SourceArtifact,
    profile: ParserProfile,
    config_hash: str,
    *,
    auxiliary=False,
) -> CandidateBatch:
    # Retain the run-ID hook used by existing deterministic replay tools.
    return candidates._batch(
        raw,
        geometries,
        source,
        profile,
        config_hash,
        auxiliary=auxiliary,
        run_id=str(uuid4()),
    )


def _profile_table_verifier(profile):
    from proofops.adapters.parsing import spp_execution

    if spp_execution.enabled(profile):
        return spp_execution.table_verifier(profile.table_source_policy_sha256)
    return _table_verifier(profile.table_source_policy_sha256)


class OpenDataLoaderParser(ParserPort):
    def __init__(self, artifact_root: Path, *, upstage_probe=None):
        self.artifact_root = Path(artifact_root)
        self.upstage_probe = upstage_probe

    def parse(
        self, source: SourceArtifact, profile: ParserProfile, *, tenant_id: str, page_reader=None
    ) -> CanonicalDocumentGraph:
        if source.tenant_id != tenant_id:
            raise ParseFailure("NOT_FOUND")
        if len(source.content) > profile.max_bytes:
            raise ParseFailure("PARSER_INPUT_LIMIT")
        if sha256(source.content).hexdigest() != source.sha256:
            raise ParseFailure("SOURCE_INTEGRITY_MISMATCH")
        if version("opendataloader-pdf") != "2.5.7":
            raise ParseFailure("PARSER_VERSION_UNSUPPORTED")
        final = (
            self.artifact_root / tenant_id / source.document_version_id / profile.parse_manifest_id
        )
        if final.exists():
            raise ParseFailure("PARSE_MANIFEST_EXISTS")
        java = shutil.which(profile.java_executable)
        if not java:
            raise ParseFailure("JAVA_21_REQUIRED")
        try:
            runtime = subprocess.run(
                [java, "-version"], capture_output=True, timeout=profile.timeout_seconds, check=True
            ).stderr.decode(errors="replace")
        except (OSError, subprocess.SubprocessError):
            raise ParseFailure("JAVA_21_REQUIRED") from None
        if re.search(r'version "21\.', runtime) is None:
            raise ParseFailure("JAVA_21_REQUIRED")
        verified = verify_quarantined_pdf(
            QuarantinedPdf(
                tenant_id,
                source.document_version_id,
                source.object_version_id,
                source.content,
                len(source.content),
                source.sha256,
            ),
            PdfLimits(**source.upload_security_limits)
            if source.upload_security_limits is not None
            else PdfLimits(max_bytes=profile.max_bytes, timeout_seconds=profile.timeout_seconds),
            tenant_id=tenant_id,
        )
        selected = profile.physical_pages or tuple(range(1, verified.page_count + 1))
        if any(page > verified.page_count for page in selected):
            raise ParseFailure("PAGE_SELECTION_INVALID")
        if profile.parser_mode == "mixed-v1" and (
            len(selected) > 30 or not set(profile.claim_physical_pages) <= set(selected)
        ):
            raise ParseFailure("MIXED_PAGE_SELECTION_INVALID")
        profile_hash = sha256(_json(profile.invocation_snapshot())).hexdigest()
        final.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with _parser_work_directory(final.parent) as work:
            (work / "source.pdf").write_bytes(source.content)
            (work / "request.json").write_bytes(
                _json(
                    dict(
                        profile=profile.invocation_snapshot(),
                        selected=selected,
                        upload_security_profile=(source.upload_security_limits or {}).get(
                            "policy_profile", "strict-v1"
                        ),
                    )
                )
            )
            env = _child_environment(java, work, profile)
            command = [sys.executable, "-I", str(Path(__file__).resolve()), str(work)]
            from proofops.adapters.parsing import spp_execution

            spp_requests = None
            if spp_execution.enabled(profile):
                if profile.parser_mode == "mixed-v1":
                    if self.upstage_probe is None:
                        raise ParseFailure("UPSTAGE_RUNTIME_REQUIRED")
                    spp_requests = spp_execution.PageRequests(
                        source,
                        profile,
                        selected,
                        self.artifact_root / "upstage-cache" / tenant_id,
                        self.upstage_probe,
                    )
            if profile.local_resource_policy in {"selected-pdf-h6-v1", "selected-pdf-h6-v2"}:
                execute = _local_pages(profile).execute
                if spp_requests is not None:
                    spp_requests.execute_local(
                        lambda: execute(command, work, env, profile, self._execute)
                    )
                else:
                    execute(command, work, env, profile, self._execute)
            else:
                self._execute(command, work, env, profile)
            try:
                geometries = json.loads((work / "geometry.json").read_bytes())
                raw = json.loads((work / "source.json").read_bytes())
                if raw.get("number of pages") != verified.page_count:
                    raise ParseFailure("PARSER_PAGE_MAPPING_INVALID")
                if profile.table_structure_repair is not None:
                    raw = json.loads((work / "source-repaired.json").read_bytes())
                candidates = [_batch(raw, geometries, source, profile, profile_hash)]
                if profile.table_auxiliary:
                    auxiliary = json.loads((work / "auxiliary.json").read_bytes())
                    candidates.append(
                        _batch(auxiliary, geometries, source, profile, profile_hash, auxiliary=True)
                    )
                recovery_references = tuple(candidates)
                fusion_version = (
                    5
                    if profile.parser_mode == "mixed-v1"
                    else 4
                    if profile.table_structure_repair == "odl_header_v2"
                    else 3
                )
                vision_metrics = None
                upstage_output: dict[str, Any] | None = None
                fallback_pages = tuple(selected)
                routing = None
                paid_pages = tuple(selected)
                if profile.parser_mode == "mixed-v1":
                    from proofops.adapters.parsing.mixed_routing import plan

                    routing = plan(source, profile, selected, candidates)
                    paid_pages = tuple(sorted(set(routing["claim_pages"] + routing["ocr_pages"])))
                if profile.parser_mode in ("upstage", "mixed-v1"):
                    if self.upstage_probe is None:
                        raise ParseFailure("UPSTAGE_RUNTIME_REQUIRED")
                    from threading import Lock

                    from proofops.adapters.parsing.upstage_document import (
                        MODEL as UPSTAGE_MODEL,
                    )
                    from proofops.adapters.parsing.upstage_document import (
                        candidate_batch,
                        selected_pdf,
                    )
                    from proofops.domain.provenance import canonical_hash

                    subset_lock = Lock()

                    def upstage_call(pages, mode):
                        h6 = profile.local_resource_policy in {
                            "selected-pdf-h6-v1",
                            "selected-pdf-h6-v2",
                        }
                        subset = _local_pages(profile).subset

                        if h6 and profile.failure_policy not in {
                            "partial-v5",
                            "partial-v6",
                            "s3_partial-v7",
                        }:
                            # A repaired parser derivative cannot ground provider text
                            # against an unreadable original. Avoid a useless paid call.
                            import io

                            import pdfplumber
                            from pdfplumber.utils.exceptions import PdfminerException

                            subset = _local_pages(profile).subset

                            try:
                                with pdfplumber.open(io.BytesIO(source.content)):
                                    pass
                            except PdfminerException:
                                raise ValueError("PARSER_NATIVE_TEXT_UNREADABLE") from None
                        cache_dir = self.artifact_root / "upstage-cache" / tenant_id
                        cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                        key = sha256(
                            _json(
                                dict(
                                    source_sha256=source.sha256,
                                    pages=pages,
                                    model=UPSTAGE_MODEL,
                                    mode=mode,
                                    **({"subset_policy": "selected-pdf-h6-v1"} if h6 else {}),
                                )
                            )
                        ).hexdigest()
                        path = cache_dir / (key + ".json")
                        if path.exists():
                            result = json.loads(path.read_bytes())
                            if canonical_hash(result["raw_batches"]) != result["response_sha256"]:
                                raise ParseFailure("UPSTAGE_CACHE_INTEGRITY_MISMATCH")
                            return result, True
                        # A s3_partial-v7 wave overlaps HTTP only. PDFium subset handles
                        # are created and closed under one lock; grounding follows the wave.
                        with subset_lock:
                            payload = (
                                subset(source.content, pages)
                                if h6
                                else selected_pdf(source.content, pages)
                            )
                        result = self.upstage_probe.parse_async(
                            payload,
                            request_id=str(uuid4()),
                            mode=mode,
                        )
                        temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
                        temporary.write_bytes(_json(result))
                        os.replace(temporary, path)
                        return result, False

                    if profile.failure_policy in {"partial-v5", "partial-v6", "s3_partial-v7"}:
                        from proofops.adapters.parsing.hx6_upstage import recover

                        candidates, routing, upstage_output = recover(
                            source,
                            profile,
                            selected,
                            candidates,
                            spp_requests if spp_requests is not None else upstage_call,
                            config_hash=profile_hash,
                            claim_layout=profile.failure_policy in {"partial-v6", "s3_partial-v7"},
                            page_workers=4 if profile.failure_policy == "s3_partial-v7" else 1,
                        )
                        fallback_pages = ()
                    else:
                        standard_failure = None
                        try:
                            standard, standard_hit = upstage_call(paid_pages, "standard")
                        except ValueError as exc:
                            if profile.failure_policy in {
                                "partial-v1",
                                "partial-v2",
                                "partial-v3",
                                "partial-v4",
                                "partial-v5",
                                "partial-v6",
                                "s3_partial-v7",
                            } and (
                                str(exc).startswith("UPSTAGE_")
                                or str(exc).endswith("BUDGET_EXHAUSTED")
                                or (
                                    profile.failure_policy
                                    in {
                                        "partial-v3",
                                        "partial-v4",
                                        "partial-v5",
                                        "partial-v6",
                                        "s3_partial-v7",
                                    }
                                    and str(exc)
                                    in {
                                        "PARSER_SUBSET_PDF_INVALID",
                                        "PARSER_NATIVE_TEXT_UNREADABLE",
                                    }
                                )
                            ):
                                standard_failure = dict(
                                    mode="standard", pages=list(paid_pages), error_code=str(exc)
                                )
                                # Explicit failure artifact, not a provider receipt.
                                standard = dict(raw_batches=[], error_code=str(exc))
                                standard_hit = False
                            elif (
                                routing is None
                                or not routing["ocr_pages"]
                                or not str(exc).endswith("BUDGET_EXHAUSTED")
                            ):
                                raise
                            else:
                                routing["ocr_pages"] = []
                                paid_pages = tuple(routing["claim_pages"])
                                standard, standard_hit = upstage_call(paid_pages, "standard")
                        if standard_failure is None:
                            upstage_batch, standard_metrics = candidate_batch(
                                source,
                                profile,
                                paid_pages,
                                standard["raw_batches"],
                                mode="standard",
                                config_hash=profile_hash,
                            )
                        else:
                            upstage_batch = replace(
                                candidates[0],
                                blocks=(),
                                edges=(),
                                parser_name="upstage_async_standard",
                                parser_version=UPSTAGE_MODEL,
                                parser_family="upstage-document-parse",
                                parser_run_id=str(uuid4()),
                            )
                            standard_metrics = dict(
                                selected_pages=list(paid_pages),
                                html_failed_pages=[],
                                low_grounding_pages=[],
                                gemini_pages=[],
                            )
                        from proofops.adapters.parsing.gemini_vision import fragment

                        local_prose = [
                            block.source.raw_text
                            for batch in candidates
                            for block in batch.blocks
                            if block.kind == "paragraph" and block.source.physical_page in selected
                        ]
                        standard_metrics["fragment_rate_local"] = sum(
                            map(fragment, local_prose)
                        ) / max(1, len(local_prose))
                        upstage_batches = [upstage_batch]
                        enhanced_records = []
                        failed_batches = [] if standard_failure is None else [standard_failure]
                        enhanced_pages = sorted(
                            set(standard_metrics["html_failed_pages"])
                            | set(standard_metrics["low_grounding_pages"])
                        )
                        completed_enhanced_pages: set[int] = set()
                        for start in range(0, len(enhanced_pages), 30):
                            pages = tuple(enhanced_pages[start : start + 30])
                            try:
                                enhanced, enhanced_hit = upstage_call(pages, "enhanced")
                            except ValueError as exc:
                                if profile.failure_policy in {
                                    "partial-v1",
                                    "partial-v2",
                                    "partial-v3",
                                    "partial-v4",
                                    "partial-v5",
                                    "partial-v6",
                                    "s3_partial-v7",
                                } and (
                                    str(exc).startswith("UPSTAGE_")
                                    or str(exc).endswith("BUDGET_EXHAUSTED")
                                ):
                                    # Optional enhancement: preserve standard output.
                                    # No paid retries; uncertain charge stays reserved.
                                    failed_batches.append(
                                        dict(
                                            mode="enhanced", pages=list(pages), error_code=str(exc)
                                        )
                                    )
                                    continue
                                if str(exc) != "BUDGET_EXHAUSTED" and not (
                                    profile.parser_mode == "mixed-v1"
                                    and str(exc).endswith("BUDGET_EXHAUSTED")
                                ):
                                    raise
                                break
                            improved, metrics = candidate_batch(
                                source,
                                profile,
                                pages,
                                enhanced["raw_batches"],
                                mode="enhanced",
                                config_hash=profile_hash,
                            )
                            upstage_batches.append(improved)
                            completed_enhanced_pages.update(pages)
                            enhanced_records.append(
                                dict(
                                    receipt={
                                        k: v for k, v in enhanced.items() if k != "raw_batches"
                                    },
                                    metrics=metrics,
                                    cache_hit=enhanced_hit,
                                    raw_batches=enhanced["raw_batches"],
                                )
                            )
                        if completed_enhanced_pages:
                            kept = tuple(
                                block
                                for block in upstage_batch.blocks
                                if block.source.physical_page not in completed_enhanced_pages
                            )
                            ids = {block.source.source_native_id for block in kept}
                            upstage_batches[0] = replace(
                                upstage_batch,
                                blocks=kept,
                                edges=tuple(
                                    edge
                                    for edge in upstage_batch.edges
                                    if edge.source_native_id in ids and edge.target_native_id in ids
                                ),
                            )
                        fallback_pages = tuple(
                            sorted(
                                (set(standard_metrics["gemini_pages"]) - completed_enhanced_pages)
                                | {
                                    p
                                    for record in enhanced_records
                                    for p in record["metrics"]["gemini_pages"]
                                }
                            )
                        )
                        upstage_output = dict(
                            standard=dict(
                                receipt=(
                                    {k: v for k, v in standard.items() if k != "raw_batches"}
                                    if standard_failure is None
                                    else None
                                ),
                                metrics=standard_metrics,
                                cache_hit=standard_hit,
                                raw_batches=standard["raw_batches"],
                            ),
                            enhanced=enhanced_records,
                            enhanced_deferred_pages=sorted(
                                set(enhanced_pages) - completed_enhanced_pages
                            ),
                            fallback_pages=fallback_pages,
                        )
                        if profile.failure_policy in {
                            "partial-v1",
                            "partial-v2",
                            "partial-v3",
                            "partial-v4",
                            "partial-v5",
                            "partial-v6",
                            "s3_partial-v7",
                        }:
                            upstage_output["failed_batches"] = failed_batches
                            if standard_failure is not None:
                                upstage_output["standard"]["error_code"] = standard_failure[
                                    "error_code"
                                ]
                        if routing is None:
                            candidates = [
                                replace(batch, blocks=(), edges=()) for batch in candidates
                            ]
                        else:
                            from proofops.adapters.parsing.mixed_routing import keep

                            candidates = [
                                keep(batch, routing["local_pages"]) for batch in candidates
                            ]
                        candidates.extend(upstage_batches)
                if profile.vision_parse != "off":
                    from proofops.adapters.parsing.gemini_vision import parse_pages

                    local_graph = fuse_candidates(
                        tuple(candidates),
                        tenant_id=tenant_id,
                        fusion_version=fusion_version,
                        mixed_parser=profile.parser_mode == "mixed-v1",
                    )
                    vision_profile = (
                        replace(profile, vision_parse="all")
                        if profile.parser_mode in ("upstage", "mixed-v1")
                        else profile
                    )
                    vision, vision_metrics = parse_pages(
                        source,
                        vision_profile,
                        local_graph,
                        fallback_pages,
                        self.artifact_root / "vision-cache",
                        key=os.environ.get("OPENROUTER_API_KEY"),
                    )
                    if vision is not None:
                        retained = []
                        for batch in candidates:
                            kept = tuple(
                                block
                                for block in batch.blocks
                                if block.source.physical_page not in vision_metrics["pages_routed"]
                            )
                            ids = {block.source.source_native_id for block in kept}
                            retained.append(
                                replace(
                                    batch,
                                    blocks=kept,
                                    edges=tuple(
                                        edge
                                        for edge in batch.edges
                                        if edge.source_native_id in ids
                                        and edge.target_native_id in ids
                                    ),
                                )
                            )
                        candidates = retained
                        candidates.append(replace(vision, config_hash=profile_hash))
                if routing is not None:
                    from proofops.adapters.parsing.mixed_routing import annotate

                    candidates = [annotate(batch) for batch in candidates]
                if profile.source_recovery is not None:
                    from proofops.adapters.parsing.source_recovery import recover_sources

                    if profile.source_recovery == "native-continuation-k8-v1":
                        from proofops.adapters.parsing.k8_source_recovery import recover_sources

                    from pdfplumber.utils.exceptions import PdfminerException

                    try:
                        recovered, recovery = recover_sources(
                            source, tuple(candidates), references=recovery_references
                        )
                    except PdfminerException:
                        if profile.failure_policy not in {
                            "partial-v3",
                            "partial-v4",
                            "partial-v5",
                            "partial-v6",
                            "s3_partial-v7",
                        }:
                            raise
                        recovered = tuple(candidates)
                        recovery = dict(
                            profile=profile.source_recovery,
                            source_sha256=source.sha256,
                            status="unreadable",
                            reason="PARSER_NATIVE_TEXT_UNREADABLE",
                        )
                    candidates = list(recovered)
                    (work / "source-recovery.json").write_bytes(_json(recovery))
                graph = fuse_candidates(
                    tuple(candidates),
                    tenant_id=tenant_id,
                    fusion_version=fusion_version,
                    mixed_parser=profile.parser_mode == "mixed-v1",
                )
            except DomainValidationError:
                raise ParseFailure("PARSER_GEOMETRY_INVALID") from None
            except (KeyError, TypeError, json.JSONDecodeError):
                raise ParseFailure("PARSER_SCHEMA_INVALID") from None
            graph = _with_quality_issues(
                graph,
                selected,
                profile,
                () if vision_metrics is None else vision_metrics["pages_routed"],
            )
            if profile.local_resource_policy in {"selected-pdf-h6-v1", "selected-pdf-h6-v2"}:
                failures = _local_pages(profile).failures
                from proofops.adapters.parsing.mixed_routing import with_failures

                graph = with_failures(
                    graph, failures(json.loads((work / "h6-local.json").read_bytes()))
                )
            if (
                profile.failure_policy
                in {
                    "partial-v1",
                    "partial-v2",
                    "partial-v3",
                    "partial-v4",
                    "partial-v5",
                    "partial-v6",
                    "s3_partial-v7",
                }
                and upstage_output is not None
            ):
                from proofops.adapters.parsing.mixed_routing import with_failures

                graph = with_failures(graph, upstage_output["failed_batches"])
            return artifacts.publish(
                work,
                final,
                source,
                profile,
                graph,
                tenant_id=tenant_id,
                profile_hash=profile_hash,
                runtime=runtime,
                selected=selected,
                fusion_version=fusion_version,
                vision_metrics=vision_metrics,
                upstage_output=upstage_output,
                routing=routing,
                page_reader=page_reader,
                table_verifier=_profile_table_verifier,
            )

    def load_verified(
        self,
        source: SourceArtifact,
        profile: ParserProfile,
        *,
        tenant_id: str,
        manifest_sha256: str | None = None,
    ) -> CanonicalDocumentGraph:
        return artifacts.load_verified(
            self.artifact_root,
            source,
            profile,
            tenant_id=tenant_id,
            manifest_sha256=manifest_sha256,
            table_verifier=_profile_table_verifier,
        )

    @staticmethod
    def _execute(command, work, env, profile):
        return runtime.execute(
            command,
            work,
            env,
            profile,
            isolate=process_isolation,
            check_limits=_check_limits,
            reap=kill_and_reap,
        )


def _child(work: Path) -> None:
    child.run(work, child_body=_child_body)


def _child_body(work: Path, page_cache=None) -> None:
    child.run_body(
        work,
        page_cache,
        apply_limits=_child_limits,
        locates_auxiliary_cells=_locates_auxiliary_cells,
    )


if __name__ == "__main__":
    _child(Path(sys.argv[1]))
