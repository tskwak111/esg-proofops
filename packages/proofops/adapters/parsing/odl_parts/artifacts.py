"""Immutable artifact publication and stored-output revalidation.

Fresh evidence creation and replay validation deliberately remain distinct paths.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

from proofops.adapters.local.claim_source_policies import PAGE_OCR_PROFILES
from proofops.adapters.parsing.odl_parts.candidates import _with_quality_issues
from proofops.adapters.parsing.odl_parts.common import ParseFailure, _json
from proofops.adapters.parsing.odl_parts.policies import _local_pages
from proofops.application.ingest.graph_fusion import (
    CanonicalDocumentGraph,
    ParserProfile,
    QualityIssue,
    SourceArtifact,
    candidates_from_snapshot,
    fuse_candidates,
)


def publish(
    work: Path,
    final: Path,
    source: SourceArtifact,
    profile: ParserProfile,
    graph: CanonicalDocumentGraph,
    *,
    tenant_id: str,
    profile_hash: str,
    runtime: str,
    selected,
    fusion_version: int,
    vision_metrics,
    upstage_output,
    routing,
    page_reader,
    table_verifier,
) -> CanonicalDocumentGraph:
    """Write fresh evidence and atomically publish its original manifest format."""
    if routing is not None:
        (work / "page-routing.json").write_bytes(_json(routing))
    (work / "graph.json").write_bytes(_json(graph.to_dict()))
    (work / "quality.json").write_bytes(_json([issue.to_dict() for issue in graph.issues]))
    (work / "candidates.json").write_bytes(_json([asdict(batch) for batch in graph.candidates]))
    if vision_metrics is not None:
        (work / "vision.json").write_bytes(_json(vision_metrics))
    if upstage_output is not None:
        (work / "upstage.json").write_bytes(_json(upstage_output))
    returned_graph = graph
    if profile.table_source_policy_sha256 is not None:
        verifier = table_verifier(profile)
        if getattr(verifier, "PROFILE", None) in PAGE_OCR_PROFILES:
            if page_reader is None:
                raise ParseFailure("OCR_RUN_REQUIRED")
            verifier = page_reader
        from proofops.adapters.local import s3_table_replay as parse_table_cache

        receipt = parse_table_cache.attest(verifier, graph, source.content, tenant_id=tenant_id)
        (work / "table-source.json").write_bytes(_json(receipt))
        returned_graph = parse_table_cache.replay(
            verifier, receipt, graph, source.content, tenant_id=tenant_id
        )
    (work / "source.pdf").unlink()
    (work / "request.json").unlink()
    artifacts = {
        path.name: sha256(path.read_bytes()).hexdigest()
        for path in work.iterdir()
        if path.is_file()
    }
    from importlib.resources import files

    jar = files("opendataloader_pdf").joinpath("jar", "opendataloader-pdf-cli.jar")
    manifest = dict(
        schema_version="1",
        fusion_version=fusion_version,
        tenant_id=tenant_id,
        document_id=source.document_id,
        document_version_id=source.document_version_id,
        parse_manifest_id=profile.parse_manifest_id,
        source_sha256=source.sha256,
        object_version_id=source.object_version_id,
        synthetic_source=source.synthetic,
        local_synthetic_storage=True,
        parser_version="2.5.7",
        parser_profile_sha256=profile_hash,
        parser_config_sha256=profile.config_hash(),
        parser_config=profile.config_snapshot(),
        parser_profile=profile.invocation_snapshot(),
        java_version=runtime.splitlines()[0],
        jar_sha256=sha256(jar.read_bytes()).hexdigest(),
        selected_physical_pages=selected,
        validation_profile="fast_preview",
        vision_status="not_run" if vision_metrics is None else "candidate_only",
        vision_parse=vision_metrics,
        upstage_parse=None
        if upstage_output is None
        else dict(
            profile=upstage_output["profile"],
            page_receipts=[
                dict(pages=r["pages"], receipt=r["receipt"], cache_hit=r["cache_hit"])
                for r in upstage_output["page_records"]
            ],
            failed_batches=upstage_output["failed_batches"],
        )
        if profile.failure_policy in {"partial-v5", "partial-v6", "s3_partial-v7"}
        else dict(
            standard=dict(
                upstage_output["standard"]["metrics"],
                cost_usd=(upstage_output["standard"]["receipt"] or {}).get(
                    "cost_with_vat_reserve_usd"
                ),
                duration_seconds=(upstage_output["standard"]["receipt"] or {}).get(
                    "duration_seconds"
                ),
                response_sha256=(upstage_output["standard"]["receipt"] or {}).get(
                    "response_sha256"
                ),
                cache_hit=upstage_output["standard"]["cache_hit"],
            ),
            enhanced=[
                dict(
                    item["metrics"],
                    cost_usd=item["receipt"].get("cost_with_vat_reserve_usd"),
                    duration_seconds=item["receipt"].get("duration_seconds"),
                    response_sha256=item["receipt"]["response_sha256"],
                    cache_hit=item["cache_hit"],
                )
                for item in upstage_output["enhanced"]
            ],
            enhanced_deferred_pages=upstage_output["enhanced_deferred_pages"],
            fallback_pages=upstage_output["fallback_pages"],
        ),
        artifacts=artifacts,
        parser_runs=[
            dict(
                parser_run_id=b.parser_run_id,
                parser_name=b.parser_name,
                parser_version=b.parser_version,
                parser_family=b.parser_family,
                config_hash=b.config_hash,
            )
            for b in graph.candidates
        ],
    )
    if routing is not None:
        from proofops.adapters.parsing.mixed_routing import provenance

        manifest["page_parser_provenance"] = provenance(routing, graph.candidates, selected)
    if profile.output_policy == "rb2-output-v1":
        from proofops.adapters.parsing.rb2_output import ARTIFACT, GRAPH_ARTIFACT, compact

        receipt = compact(work, profile, manifest_bytes=len(_json(manifest)))
        if receipt is not None:
            artifacts.pop("candidates.json")
            artifacts[ARTIFACT] = sha256((work / ARTIFACT).read_bytes()).hexdigest()
            if receipt.get("graph") is not None:
                artifacts.pop("graph.json")
                artifacts[GRAPH_ARTIFACT] = sha256((work / GRAPH_ARTIFACT).read_bytes()).hexdigest()
            manifest["rb2_output"] = receipt
    (work / "manifest.json").write_bytes(_json(manifest))
    if sum(path.stat().st_size for path in work.iterdir()) > profile.max_output_bytes:
        raise ParseFailure("PARSER_OUTPUT_LIMIT")
    for path in work.iterdir():
        path.chmod(0o400)
    try:
        os.rename(work, final)
    except OSError:
        raise ParseFailure("PARSE_MANIFEST_EXISTS") from None
    return returned_graph


def load_verified(
    artifact_root: Path,
    source: SourceArtifact,
    profile: ParserProfile,
    *,
    tenant_id: str,
    manifest_sha256: str | None = None,
    table_verifier,
) -> CanonicalDocumentGraph:
    """Reuse immutable output only after identity, config and every artifact hash agree."""
    if source.tenant_id != tenant_id:
        raise ParseFailure("NOT_FOUND")
    if sha256(source.content).hexdigest() != source.sha256:
        raise ParseFailure("SOURCE_INTEGRITY_MISMATCH")
    directory = artifact_root / tenant_id / source.document_version_id / profile.parse_manifest_id
    try:
        if directory.is_symlink():
            raise ValueError("symlink")
        manifest_path = directory / "manifest.json"
        if manifest_path.is_symlink() or manifest_path.stat().st_size > profile.max_output_bytes:
            raise ValueError("unsafe manifest")
        raw_manifest = manifest_path.read_bytes()
        if manifest_sha256 is not None and sha256(raw_manifest).hexdigest() != manifest_sha256:
            raise ValueError("manifest hash")
        manifest = json.loads(raw_manifest)
        expected = dict(
            schema_version="1",
            tenant_id=tenant_id,
            document_id=source.document_id,
            document_version_id=source.document_version_id,
            parse_manifest_id=profile.parse_manifest_id,
            source_sha256=source.sha256,
            object_version_id=source.object_version_id,
            synthetic_source=source.synthetic,
            local_synthetic_storage=True,
            parser_version="2.5.7",
            parser_profile_sha256=sha256(_json(profile.invocation_snapshot())).hexdigest(),
            parser_profile=json.loads(_json(profile.invocation_snapshot())),
            parser_config_sha256=profile.config_hash(),
            parser_config=profile.config_snapshot(),
            validation_profile="fast_preview",
            vision_status="not_run" if profile.vision_parse == "off" else "candidate_only",
        )
        if any(manifest.get(key) != value for key, value in expected.items()):
            raise ValueError("manifest identity")
        artifacts = manifest["artifacts"]
        required = {
            "graph.json",
            "quality.json",
            "candidates.json",
            "geometry.json",
            "source.json",
            "source.md",
        }
        from proofops.adapters.parsing.rb2_output import (
            ARTIFACT,
            GRAPH_ARTIFACT,
            read_candidates,
        )

        compacted = manifest.get("rb2_output")
        if compacted is not None:
            if (
                not isinstance(compacted, dict)
                or profile.output_policy != "rb2-output-v1"
                or "candidates.json" in artifacts
            ):
                raise ValueError("unconfigured candidate compaction")
            required.remove("candidates.json")
            required.add(ARTIFACT)
            if compacted.get("graph") is not None:
                if "graph.json" in artifacts:
                    raise ValueError("duplicate compacted graph")
                required.remove("graph.json")
                required.add(GRAPH_ARTIFACT)
            elif GRAPH_ARTIFACT in artifacts:
                raise ValueError("unconfigured graph compaction")
        elif ARTIFACT in artifacts:
            raise ValueError("unconfigured candidate compaction")
        elif GRAPH_ARTIFACT in artifacts:
            raise ValueError("unconfigured graph compaction")
        if profile.table_auxiliary:
            required.add("auxiliary.json")
        if profile.source_recovery is not None:
            required.add("source-recovery.json")
        elif "source-recovery.json" in artifacts:
            raise ValueError("unconfigured source recovery")
        if profile.table_structure_repair is not None:
            required.update({"source-repaired.json", "table-repair.json"})
        elif {"source-repaired.json", "table-repair.json"} & artifacts.keys():
            raise ValueError("unconfigured table repair")
        if profile.table_source_policy_sha256 is not None:
            required.add("table-source.json")
        elif "table-source.json" in artifacts:
            raise ValueError("unconfigured table attestation")
        if profile.vision_parse != "off":
            required.add("vision.json")
        if profile.parser_mode in ("upstage", "mixed-v1"):
            required.add("upstage.json")
        if profile.parser_mode == "mixed-v1":
            required.add("page-routing.json")
        elif "page-routing.json" in artifacts or "page_parser_provenance" in manifest:
            raise ValueError("unconfigured mixed routing")
        if profile.local_resource_policy == "selected-pdf-h1-v1":
            required.update({"local-selected.pdf", "local-selected.json", "local-page-map.json"})
        elif profile.local_resource_policy in {"selected-pdf-h6-v1", "selected-pdf-h6-v2"}:
            required.add("h6-local.json")
        elif {
            "local-selected.pdf",
            "local-selected.json",
            "local-page-map.json",
        } & artifacts.keys():
            raise ValueError("unconfigured local page mapping")
        if not required <= artifacts.keys():
            raise ValueError("missing artifacts")
        values = {}
        total = len(raw_manifest)
        for name, digest in artifacts.items():
            path = directory / name
            if Path(name).name != name or path.is_symlink():
                raise ValueError("unsafe artifact path")
            total += path.stat().st_size
            if total > profile.max_output_bytes:
                raise ValueError("artifact limit")
            data = path.read_bytes()
            if sha256(data).hexdigest() != digest:
                raise ValueError("artifact hash")
            if name == ARTIFACT:
                values["candidates.json"] = read_candidates(data, profile, compacted)
            if name == GRAPH_ARTIFACT:
                values["graph.json"] = read_candidates(data, profile, compacted["graph"])
            if (
                profile.local_resource_policy in {"selected-pdf-h6-v1", "selected-pdf-h6-v2"}
                and name.endswith(".json")
            ) or name in {
                "graph.json",
                "quality.json",
                "candidates.json",
                "source-recovery.json",
                "table-source.json",
                "vision.json",
                "upstage.json",
                "page-routing.json",
                "source.json",
                "local-selected.json",
                "local-page-map.json",
            }:
                values[name] = json.loads(data)
        if profile.local_resource_policy in {"selected-pdf-h6-v1", "selected-pdf-h6-v2"}:
            validate = _local_pages(profile).validate

            validate(
                values["h6-local.json"],
                values,
                artifacts,
                source,
                manifest["selected_physical_pages"],
            )
        elif profile.local_resource_policy is not None:
            from proofops.adapters.parsing.h1_local_pages import POLICY, restore_pages
            from proofops.domain.provenance import canonical_hash

            page_map = values["local-page-map.json"]
            raw_subset = values["local-selected.json"]
            if (
                page_map["policy"] != POLICY
                or page_map["policy_sha256"] != canonical_hash(POLICY)
                or page_map["source_sha256"] != source.sha256
                or page_map["subset_sha256"] != artifacts["local-selected.pdf"]
                or page_map["raw_json_sha256"] != canonical_hash(raw_subset)
                or page_map["physical_page_map"] != manifest["selected_physical_pages"]
                or restore_pages(
                    raw_subset, page_map["physical_page_map"], page_map["original_page_count"]
                )
                != values["source.json"]
            ):
                raise ValueError("local page mapping mismatch")
        upstage_output = values.get("upstage.json")
        if profile.parser_mode in ("upstage", "mixed-v1"):
            from proofops.domain.provenance import canonical_hash

            if profile.failure_policy in {"partial-v5", "partial-v6", "s3_partial-v7"}:
                from proofops.application.ingest.page_recovery_policy import (
                    CLAIM_LAYOUT_POLICY,
                    POLICY,
                    S3_CLAIM_LAYOUT_POLICY,
                )

                recovery_policy = (
                    S3_CLAIM_LAYOUT_POLICY
                    if profile.failure_policy == "s3_partial-v7"
                    else CLAIM_LAYOUT_POLICY
                    if profile.failure_policy == "partial-v6"
                    else POLICY
                )
                if (
                    not isinstance(upstage_output, dict)
                    or upstage_output.get("profile") != recovery_policy
                ):
                    raise ValueError("HX6 parser policy mismatch")
                for record in upstage_output["page_records"]:
                    if (
                        canonical_hash(record["raw_batches"])
                        != record["receipt"]["response_sha256"]
                    ):
                        raise ValueError("upstage response mismatch")
            else:
                if not isinstance(upstage_output, dict) or not isinstance(
                    upstage_output.get("standard"), dict
                ):
                    raise ValueError("upstage artifact missing")
                for record in [upstage_output["standard"], *upstage_output.get("enhanced", [])]:
                    if record["receipt"] is None and profile.failure_policy in {
                        "partial-v1",
                        "partial-v2",
                        "partial-v3",
                        "partial-v4",
                        "partial-v5",
                        "partial-v6",
                        "s3_partial-v7",
                    }:
                        if record.get("raw_batches") != [] or not any(
                            f["mode"] == "standard" and f["error_code"] == record.get("error_code")
                            for f in upstage_output["failed_batches"]
                        ):
                            raise ValueError("invalid failed parser artifact")
                        continue
                    if (
                        canonical_hash(record["raw_batches"])
                        != record["receipt"]["response_sha256"]
                    ):
                        raise ValueError("upstage response mismatch")
        vision_metrics = values.get("vision.json")
        if profile.vision_parse != "off":
            from proofops.adapters.parsing.gemini_vision import MODEL, PROMPT_HASH

            if (
                vision_metrics != manifest.get("vision_parse")
                or vision_metrics.get("mode")
                != (
                    "all"
                    if profile.parser_mode in ("upstage", "mixed-v1")
                    else profile.vision_parse
                )
                or vision_metrics.get("model") != MODEL
                or vision_metrics.get("prompt_sha256") != PROMPT_HASH
            ):
                raise ValueError("vision manifest mismatch")
        candidates = candidates_from_snapshot(values["candidates.json"])
        if profile.source_recovery is not None:
            recovery = values.get("source-recovery.json", {})
            if (
                recovery.get("profile") != profile.source_recovery
                or recovery.get("source_sha256") != source.sha256
            ):
                raise ValueError("source recovery manifest mismatch")
        # Existing immutable manifests predate fusion versioning.
        fusion_version = manifest.get("fusion_version", 1)
        if type(fusion_version) is not int or fusion_version not in (1, 2, 3, 4, 5):
            raise ValueError("unsupported fusion version")
        if fusion_version == 5 and profile.parser_mode != "mixed-v1":
            raise ValueError("unconfigured mixed fusion version")
        graph = fuse_candidates(
            candidates,
            tenant_id=tenant_id,
            fusion_version=fusion_version,
            mixed_parser=profile.parser_mode == "mixed-v1",
        )
        if graph.to_dict() != values["graph.json"] or (
            graph.document_version_id,
            graph.parse_manifest_id,
            graph.source_sha256,
        ) != (source.document_version_id, profile.parse_manifest_id, source.sha256):
            raise ValueError("graph identity")
        if any(batch.config_hash != expected["parser_profile_sha256"] for batch in candidates):
            raise ValueError("candidate configuration")
        selected = manifest["selected_physical_pages"]
        if profile.physical_pages and selected != list(profile.physical_pages):
            raise ValueError("page selection")
        if profile.parser_mode == "mixed-v1":
            from proofops.adapters.parsing.mixed_routing import provenance

            routing = values["page-routing.json"]
            if profile.failure_policy in {"partial-v5", "partial-v6", "s3_partial-v7"}:
                from proofops.adapters.parsing.hx6_upstage import provenance as hx6_provenance

                groups = [routing[k] for k in ("local_pages", "provider_pages", "unreadable_pages")]
                if (
                    routing["version"] != "mixed-hx6-v1"
                    or routing["claim_pages"] != list(profile.claim_physical_pages)
                    or any(g != sorted(set(g)) for g in groups)
                    or sorted(p for g in groups for p in g) != selected
                    or manifest["page_parser_provenance"]
                    != hx6_provenance(routing, candidates, selected)
                ):
                    raise ValueError("mixed routing provenance mismatch")
            else:
                claims, local, rejected, ocr = (
                    routing[k]
                    for k in (
                        "claim_pages",
                        "local_pages",
                        "rejected_native_pages",
                        "ocr_pages",
                    )
                )
                if (
                    claims != list(profile.claim_physical_pages)
                    or any(x != sorted(set(x)) for x in (claims, local, rejected, ocr))
                    or set(claims) & (set(local) | set(rejected))
                    or set(local) & set(rejected)
                    or set(claims + local + rejected) != set(selected)
                    or not set(ocr) <= set(rejected[: profile.mixed_ocr_max_pages])
                    or manifest["page_parser_provenance"]
                    != provenance(routing, candidates, selected)
                ):
                    raise ValueError("mixed routing provenance mismatch")
        if any(block.page_num not in selected for block in graph.blocks):
            raise ValueError("unselected block")
        issues = tuple(
            QualityIssue(**{**issue, "source_ids": tuple(issue["source_ids"])})
            for issue in values["quality.json"]
        )
        restored = _with_quality_issues(
            graph,
            selected,
            profile,
            () if vision_metrics is None else vision_metrics["pages_routed"],
        )
        if profile.local_resource_policy in {"selected-pdf-h6-v1", "selected-pdf-h6-v2"}:
            failures = _local_pages(profile).failures
            from proofops.adapters.parsing.mixed_routing import with_failures

            restored = with_failures(restored, failures(values["h6-local.json"]))
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

            restored = with_failures(restored, upstage_output["failed_batches"])
        if restored.issues != issues:
            raise ValueError("quality issue mismatch")
        from importlib.resources import files

        jar = files("opendataloader_pdf").joinpath("jar", "opendataloader-pdf-cli.jar")
        if manifest["jar_sha256"] != sha256(jar.read_bytes()).hexdigest():
            raise ValueError("parser binary mismatch")
        expected_parsers = {"opendataloader": ("2.5.7", "opendataloader")}
        if profile.table_auxiliary:
            expected_parsers["pdfplumber"] = (version("pdfplumber"), "pdfminer")
        if profile.vision_parse != "off":
            from proofops.adapters.parsing.gemini_vision import MODEL

            expected_parsers["gemini_vision"] = (MODEL, "vision")
        if profile.parser_mode in ("upstage", "mixed-v1"):
            from proofops.adapters.parsing.upstage_document import MODEL as UPSTAGE_MODEL

            if profile.failure_policy not in {"partial-v5", "partial-v6", "s3_partial-v7"} or (
                isinstance(upstage_output, dict) and upstage_output.get("page_records")
            ):
                expected_parsers["upstage_async_standard"] = (
                    UPSTAGE_MODEL,
                    "upstage-document-parse",
                )
            if upstage_output is not None and upstage_output.get("enhanced"):
                expected_parsers["upstage_async_enhanced"] = (
                    UPSTAGE_MODEL,
                    "upstage-document-parse",
                )
        if {
            batch.parser_name: (batch.parser_version, batch.parser_family) for batch in candidates
        } != expected_parsers or any(batch.synthetic for batch in candidates):
            raise ValueError("parser identity mismatch")
        if manifest["parser_runs"] != [
            dict(
                parser_run_id=b.parser_run_id,
                parser_name=b.parser_name,
                parser_version=b.parser_version,
                parser_family=b.parser_family,
                config_hash=b.config_hash,
            )
            for b in candidates
        ]:
            raise ValueError("parser run mismatch")
        if profile.table_source_policy_sha256 is not None:
            verifier = table_verifier(profile)
            from proofops.adapters.local import s3_table_replay as parse_table_cache
            from proofops.adapters.local.receipt_environment_compat import (
                record_table_read,
            )

            restored = parse_table_cache.replay(
                verifier,
                values["table-source.json"],
                restored,
                source.content,
                tenant_id=tenant_id,
                compatible=True,
            )
            record_table_read(values["table-source.json"], restored)
        return restored
    except (OSError, ValueError, KeyError, TypeError):
        raise ParseFailure("PARSER_ARTIFACT_INTEGRITY_MISMATCH") from None
