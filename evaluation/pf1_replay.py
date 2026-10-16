"""Network-free comparison of original PDF display mappings for saved extraction packets."""

import json
import os
import socket
import sqlite3
import time
from pathlib import Path

from proofops.adapters.local.glyph_display_text import GlyphDisplayCatalog
from proofops.domain.provenance import canonical_hash

ROOT = Path("/path/to/ESG_ProofOps")
OUT = ROOT / "outputs/agent-results/R108-redesign/lab/perf/PF1"


def deny(*args, **kwargs):
    raise RuntimeError("PF1_OFFLINE_NETWORK_FORBIDDEN")


def replay(name, state):
    meta = json.loads((state / "pilot.json").read_text())
    source = Path(meta["source_path"]).read_bytes()
    from proofops.adapters.local.run_artifacts import load_run_graph
    from proofops.adapters.local.run_store import LocalSQLiteRunStore
    from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
    from proofops.application.registry import Registry
    from proofops.application.uploads import UploadService

    target = OUT / (name + "-offline-state")
    target.mkdir(exist_ok=True)
    database = target / "state.sqlite3"
    if not database.exists():
        with sqlite3.connect((state / "state.sqlite3").as_uri() + "?mode=ro", uri=True) as old:
            with sqlite3.connect(database) as fresh:
                old.backup(fresh)
    for folder in ("objects", "parser-prepared"):
        if not (target / folder).exists():
            (target / folder).symlink_to(state / folder, target_is_directory=True)
    store = LocalSQLiteRunStore(database)
    uploads = UploadService(database, target / "objects", Registry.sqlite(database))
    os.environ["PROOFOPS_RECEIPT_READ_PROFILE"] = "receipt-env-drift-v1"
    if name == "skino":
        # The seed pilot is queued; use the published two-page run, never invent a checkpoint.
        meta["run_id"] = "3f4f63c5-253a-472a-9628-6c97487c2c8f"
    graph = load_run_graph(
        store,
        uploads,
        OpenDataLoaderParser(target / "parser-prepared"),
        tenant_id=meta["tenant_id"],
        run_id=meta["run_id"],
    )
    packets = [
        json.loads(p.read_text()) for p in (state / "extraction-receipts").glob("*/packet.json")
    ]
    packets = [p for p in packets if p["parse_manifest_id"] == graph.parse_manifest_id]
    assert packets, "saved packets required"
    pins = [
        pin
        for packet in packets
        for pin in [packet["display_text"], *packet.get("display_text_context", [])]
    ]
    source_ids = sorted({pin["identity"]["source_id"] for pin in pins})
    pages = sorted({pin["identity"]["page_num"] for pin in pins})
    outcomes = []
    for workers in (1, 4):
        catalog = GlyphDisplayCatalog(graph, source)
        began = time.monotonic()
        catalog.prefetch_pages(pages, max_workers=workers)
        results = [catalog.block_pin(sid) for sid in source_ids]
        elapsed = time.monotonic() - began
        # Graph quality hashes can differ from the stored native-replayed graph;
        # display geometry itself is compared byte-for-byte against saved mappings.
        normalized = []
        for result in results:
            result["identity"].pop("graph_sha256")
            normalized.append(result)
        outcomes.append(
            dict(
                workers=workers,
                seconds=elapsed,
                mapping_hash=canonical_hash(normalized),
                mappings=normalized,
            )
        )
        print(name, workers, round(elapsed, 3), flush=True)
    assert outcomes[0]["mappings"] == outcomes[1]["mappings"]
    by_id = {r["identity"]["source_id"]: r for r in outcomes[0]["mappings"]}
    stored_checks = 0
    for pin in pins:
        saved = json.loads(json.dumps(pin))
        saved["identity"].pop("graph_sha256")
        assert saved == by_id[saved["identity"]["source_id"]]
        stored_checks += 1
    for result in outcomes:
        result.pop("mappings")
    record = dict(
        company=name,
        pages=pages,
        source_ids=len(source_ids),
        packet_count=len(packets),
        saved_pin_checks=stored_checks,
        outcomes=outcomes,
        mapping_equal=True,
        stored_mapping_equal=True,
        model_calls=0,
        scope="Display mappings only; saved votes, decisions and publication unchanged.",
    )
    (OUT / f"{name}-replay.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main():
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    states = dict(
        naver=ROOT / "outputs/agent-results/R108-redesign/lab/decision/RH5/states/control/naver",
        skino=ROOT / ".local/r108-rh2-v2.90m7m22v/live",
    )
    for name, state in states.items():
        replay(name, state)


if __name__ == "__main__":
    main()
