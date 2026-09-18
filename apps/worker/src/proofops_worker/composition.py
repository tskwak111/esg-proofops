"""Explicit local parser composition; no runtime discovery or synthetic model result."""

from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path

from proofops.adapters.local.run_store import LocalSQLiteRunStore
from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
from proofops.application.claims import ClaimExtractorPort
from proofops.application.ingest.graph_fusion import ParserProfile
from proofops.application.registry import Registry
from proofops.application.telemetry import Telemetry
from proofops.application.uploads import UploadService
from proofops.composition import build_composition as build_proofops_composition

from proofops_worker.extract_runner import LocalExtractRunner
from proofops_worker.local_runner import LocalParserRunner
from proofops_worker.tag_runner import LocalTagRunner


def build_composition(
    *, stage: str = "parse", review_table_notes: bool = False
) -> LocalParserRunner | LocalExtractRunner | LocalTagRunner:
    if type(review_table_notes) is not bool or (review_table_notes and stage != "parse"):
        raise ValueError("NOTE_REVIEWS_REQUIRE_PARSE_STAGE")
    if stage not in {"parse", "extract", "tag"}:
        raise ValueError("STAGE_INVALID")
    if stage == "extract" and os.environ.get("LOCAL_EXTRACTION_MODE") not in {
        "local_synthetic",
        "upstage_probe",
    }:
        raise ValueError("EXPLICIT_LOCAL_SYNTHETIC_EXTRACTION_REQUIRED")
    build_proofops_composition(
        app_env=os.environ.get("APP_ENV", "local"),
        model_adapter=os.environ.get("MODEL_ADAPTER", "synthetic"),
    )
    config_path = os.environ.get("LOCAL_PARSER_PROFILE_PATH")
    if not config_path:
        raise ValueError("PARSER_CONFIG_REQUIRED")
    config = json.loads(Path(config_path).read_text())
    profile = ParserProfile(parse_manifest_id="00000000-0000-4000-8000-000000000000", **config)
    if profile.config_snapshot() != config:
        raise ValueError("PARSER_CONFIG_INVALID")
    database = Path(os.environ.get("LOCAL_DATABASE_PATH", ".local/state.sqlite3"))
    database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    registry = Registry.sqlite(database)
    uploads = UploadService(database, database.parent / "objects", registry)
    note_ledger = Path(__file__).resolve().parents[4] / ".local/upstage/budget.sqlite3"
    note_client = None
    if review_table_notes:
        from proofops.adapters.local.upstage import UpstageProbe

        if not note_ledger.is_file():
            raise ValueError("SHARED_BUDGET_LEDGER_REQUIRED")
        note_client = UpstageProbe(os.environ.get("UPSTAGE_API_KEY", ""), note_ledger)
    runner = LocalParserRunner(
        LocalSQLiteRunStore(database),
        uploads,
        OpenDataLoaderParser(database.parent / "parser-prepared"),
        profile=profile,
        note_client=note_client,
        note_ledger=note_ledger,
        telemetry=Telemetry(
            service="worker", env="local", stream=sys.stdout, hash_key=secrets.token_bytes(32)
        ),
    )

    if stage == "tag":
        from proofops_agent.synthetic_tagging import SyntheticTaggingTransport

        return LocalTagRunner(
            runner.store,
            runner.uploads,
            runner.parser,
            telemetry=runner.telemetry,
            transport=SyntheticTaggingTransport()
            if os.environ.get("LOCAL_TAGGING_MODE") == "local_synthetic"
            else None,
        )
    if stage == "extract":
        from proofops_agent.extraction import SyntheticClaimExtractor

        extractor: ClaimExtractorPort = SyntheticClaimExtractor()
        if os.environ.get("LOCAL_EXTRACTION_MODE") == "upstage_probe":
            from proofops.adapters.local.upstage import MODEL, MODEL_PRO4, UpstageProbe
            from proofops_agent.upstage_extraction import UpstageClaimExtractor, _profile

            # The existing user-authorized ledger must exist; never mint another allowance.
            ledger = Path(__file__).resolve().parents[4] / ".local/upstage/budget.sqlite3"
            if not ledger.is_file():
                raise ValueError("SHARED_BUDGET_LEDGER_REQUIRED")
            settings_path = os.environ.get("LOCAL_RUN_SETTINGS_PATH")
            if not settings_path:
                raise ValueError("LOCAL_RUN_SETTINGS_REQUIRED")
            settings = json.loads(Path(settings_path).read_text())
            maximum = settings.get("extraction_limits", {}).get("max_output_tokens")
            if type(maximum) is not int or not 1 <= maximum <= 1024:
                raise ValueError("LOCAL_RUNTIME_CONFIG_INVALID")
            frozen_profile = settings.get("extraction_profile")
            if not isinstance(frozen_profile, dict):
                raise ValueError("EXTRACTION_PROFILE_MISMATCH")
            frozen_model_hash = frozen_profile.get("model_sha256")
            model = next(
                (m for m in (MODEL, MODEL_PRO4) if _profile(m).model_sha256 == frozen_model_hash),
                None,
            )
            if model is None:
                raise ValueError("EXTRACTION_PROFILE_MISMATCH")
            extractor = UpstageClaimExtractor(
                UpstageProbe(os.environ.get("UPSTAGE_API_KEY", ""), ledger, model=model),
                database.parent / "extraction-receipts",
                max_tokens=maximum,
            )
        return LocalExtractRunner(
            runner.store,
            runner.uploads,
            runner.parser,
            extractor=extractor,
            telemetry=runner.telemetry,
        )
    return runner
