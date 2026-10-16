"""Recompute saved source proofs; diagnose early-page packet lineage without calls."""

import argparse
import json
import os
import socket
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path


def main():
    from proofops.adapters.local.claim_source_policies import attest_claims, publication_reader
    from proofops.adapters.local.claim_source_verification import discovery_refs
    from proofops.adapters.local.claim_store import (
        _RecordedExtractor,
        claim_scope,
        extraction_profile,
    )
    from proofops.adapters.local.native_replay_cache import replay_claims_cached
    from proofops.adapters.local.openai import OpenAIProbe
    from proofops.adapters.local.upstage_parse import UpstageParseProbe
    from proofops.application.claims import discover_atomic_claims
    from proofops.domain.provenance import canonical_hash
    from proofops_api.hosted_ocr import ReplayOCRStore, reader_scope
    from proofops_worker.composition import build_composition

    from evaluation.pa3_replay import fixture

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-profile", default="exact-verified-read-v5")
    parser.add_argument("--page", action="store_true")
    args = parser.parse_args()
    tenant, run = fixture(args.source.resolve(), args.output.resolve(), "tag")
    root = args.output.resolve()
    os.environ.update(
        APP_ENV="local",
        MODEL_ADAPTER="synthetic",
        LOCAL_EXTRACTION_MODE="upstage_probe",
        LOCAL_TAGGING_MODE="upstage_local",
        LOCAL_LLM_PROVIDER="openai",
        LOCAL_DATABASE_PATH=str(root / "state.sqlite3"),
        LOCAL_PARSER_PROFILE_PATH=str(root / "parser.json"),
        LOCAL_RUN_SETTINGS_PATH=str(root / "settings.json"),
        PROOFOPS_VERIFIED_READ_CACHE=args.cache_profile,
    )

    def deny(*a, **k):
        raise AssertionError("W3_OFFLINE_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.create_connection = deny
    worker = build_composition(
        stage="extract",
        provider_factories={
            "llm": lambda key, ledger, **kw: OpenAIProbe("offline", ledger, **kw),
            "parse": lambda ledger: UpstageParseProbe("offline", ledger),
        },
        provider_ledgers=(root / "upstage.sqlite3", root / "offline.sqlite3"),
    )
    snapshot = worker.store.snapshot(tenant, run)
    worker.clock = (
        lambda: datetime.fromisoformat(
            snapshot["runtime"]["approved_at"].replace("Z", "+00:00")
        ).timestamp()
        + 600
    )
    try:
        with reader_scope(ReplayOCRStore(root / "upstage.sqlite3")):
            envelope, _, graph = worker.claims.load_evidence(tenant, run, for_extraction=True)
            profile = extraction_profile(snapshot)
            discovery = discover_atomic_claims(
                graph,
                claim_scope(snapshot, graph),
                extractor=_RecordedExtractor(profile, envelope["discovery"]["receipts"]),
            )
            reader = publication_reader(snapshot["claim_source_policy"])
            source = worker.uploads.read_original(tenant, graph.document_version_id)
            if args.page:
                page = min(c.source_refs[0].page_num for c in discovery.claims)
                discovery = replace(
                    discovery,
                    claims=tuple(c for c in discovery.claims if c.source_refs[0].page_num == page),
                )
            began = time.monotonic()
            receipt = attest_claims(
                reader=reader,
                graph=graph,
                source=source,
                refs=discovery_refs(discovery),
                tenant_id=tenant,
                run_id=run,
                cache=True,
            )
            checked, scoped = replay_claims_cached(
                reader=reader,
                policy=snapshot["claim_source_policy"],
                receipt=receipt,
                graph=graph,
                source=source,
                discovery=discovery,
                tenant_id=tenant,
            )
            result = dict(
                seconds=time.monotonic() - began,
                source_policy=snapshot["claim_source_policy"],
                refs=len(discovery_refs(discovery)),
                claims=len(checked.claims),
                verified=sum(c.source_quality == "verified" for c in checked.claims),
                full_receipt_equal=(
                    canonical_hash(receipt) == canonical_hash(envelope["claim_source_attestation"])
                ),
                receipt_sha256=canonical_hash(receipt),
                graph_sha256=canonical_hash(asdict(scoped)),
                original_graph_sha256=canonical_hash(asdict(graph)),
                live_provider_calls=0,
                paid_usd="0",
                page_only=args.page,
            )
            saved_pins = set()
            ids = {c.claim_id for c in checked.claims}
            for path in (args.source / "tagging-receipts").rglob("request.json"):
                artifact = json.loads(path.read_text())
                request = artifact.get("request", artifact)
                if request.get("claim_id") in ids:
                    raw = artifact.get("wire_user_json") or request.get("user_json")
                    wire = json.loads(raw)
                    if wire.get("graph_sha256"):
                        saved_pins.add(wire["graph_sha256"])
            result["retained_graph_pins"] = sorted(saved_pins)
            result["early_wire_graph_equal"] = saved_pins == {result["graph_sha256"]}
            (root / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False))
            (root / "measurement.json").write_text(json.dumps(result, indent=2))
            print(json.dumps({k: v for k, v in result.items() if k != "source_policy"}))
    finally:
        worker.uploads.close()
        worker.uploads.registry.close()


if __name__ == "__main__":
    main()
