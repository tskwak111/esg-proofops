"""Offline SDI extraction replay from read-only server artifacts, without new votes.

Restore the receipt-pinned parse graph and replay retained, validated model spans
through the production QT1/discovery boundary. This is candidate extraction, not
fresh source attestation or grading. Missing responses never dispatch a provider.
"""

import argparse
import json
import socket
import sqlite3
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from proofops.adapters.local.claim_store import (
    DEFERRED_LIMIT_REASON,
    claim_scope,
    deferred_payload,
    extraction_outcome,
)
from proofops.adapters.local.h1_native_title import native_figure_candidates
from proofops.adapters.local.verified_read_cache import _project_parse
from proofops.adapters.parsing.parser_artifacts import read_parser_json
from proofops.application.claims import ExtractionOutputError, discover_atomic_claims
from proofops.application.ingest.graph_fusion import (
    QualityIssue,
    candidates_from_snapshot,
    fuse_candidates,
)
from proofops.application.rb1_input_isolation import InputIsolation
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import UpstageClaimExtractor
from proofops_worker.extract_runner import select_stable_paragraph_sources

from evaluation.tb1_retained_graph import _identity, _receipt
from evaluation.w7_sentence_replay import NoTransport

PIN = "f29385d0c74d1520350deb06eaa9e11b72c5829dfaefeb2417c4e8ac0fed4ebd"


def read(path):
    return json.loads(path.read_bytes())


def replay(root, output):
    directory = root / "sdi"
    database = next((root / "analysis").rglob("state.sqlite3"))
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        snapshot = json.loads(db.execute("SELECT payload FROM run_snapshots").fetchone()[0])
        (row,) = db.execute("SELECT value FROM job_records WHERE kind='artifact'").fetchall()
        parse = json.loads(row[0])
    assert canonical_hash(snapshot["analysis_profile_policy"]) == PIN
    assert snapshot["analysis_profile_policy_sha256"] == PIN
    manifest = next((directory / "parser-prepared").rglob("manifest.json"))
    assert sha256(manifest.read_bytes()).hexdigest() == parse["manifest_sha256"]
    meta = read(manifest)
    quality = manifest.with_name("quality.json")
    assert sha256(quality.read_bytes()).hexdigest() == meta["artifacts"][quality.name]
    graph = fuse_candidates(
        candidates_from_snapshot(read_parser_json(manifest.with_name("candidates.json"))),
        tenant_id=meta["tenant_id"],
        fusion_version=meta["fusion_version"],
        mixed_parser=True,
    )
    graph = replace(
        graph,
        issues=tuple(
            QualityIssue(**item | dict(source_ids=tuple(item["source_ids"])))
            for item in read(quality)
        ),
    )
    for key, native in (
        ("native_paragraph_attestation", True),
        ("evidence_source_attestation", False),
    ):
        receipt = parse[key]
        _receipt(receipt)
        _identity(graph, receipt["input_graph_sha256"])
        graph = _project_parse(receipt, graph, native=native)
    _identity(graph, parse["graph_sha256"])
    source = next(root.glob("*.prepared.pdf")).read_bytes()
    assert sha256(source).hexdigest() == graph.source_sha256
    graph, _ = native_figure_candidates(graph, source)
    settings = read(directory / "settings.json")
    flags = {
        key: value
        for key, value in settings.items()
        if key.startswith("extraction_") and type(value) is bool
    }
    flags.update(
        position_order=False, display_text_profile=settings["display_text_policy"]["profile"]
    )
    rb1 = InputIsolation(snapshot["analysis_profile_policy"])
    scope = claim_scope(snapshot, graph)
    window = select_stable_paragraph_sources(
        graph,
        scope,
        100,
        extraction_table_rows=True,
        extraction_k3=True,
        extraction_qt1=True,
        rb1=rb1,
    )
    packets, results, failures = {}, {}, {}
    # Model receipts take precedence over the preliminary PB1 attempt for the same table.
    paths = sorted(
        (directory / "extraction-receipts").glob("*/packet.json"),
        key=lambda p: p.with_name("raw_response.json").exists(),
    )
    for path in paths:
        packet = read(path)
        sid = packet["untrusted_document_data"]["source_id"]
        packets[sid] = packet
        result_path, failure_path = path.with_name("result.json"), path.with_name("failure.json")
        if failure_path.exists():
            failure = read(failure_path)
            assert failure["packet_sha256"] == canonical_hash(packet)
            failures[sid] = failure["reason_code"]
        if result_path.exists():
            result = read(result_path)
            if path.with_name("raw_response.json").exists():
                raw = read(path.with_name("raw_response.json"))
                assert result["packet_sha256"] == canonical_hash(packet)
                assert result["content_sha256"] == canonical_hash(raw["content"])
                assert result["response_sha256"] == raw["response_sha256"]
                assert result["profile"] == snapshot["extraction_profile"]
            results[sid] = result["spans"]
    assert window <= results.keys() | failures.keys()

    class RetainedExtractor(UpstageClaimExtractor):
        def _extract(self, packet, **kwargs):
            sid = packet["untrusted_document_data"]["source_id"]
            rb1.check(sid)
            if sid in packets:
                saved = packets[sid]
                for key in packet:
                    assert packet[key] == saved[key]
            if sid in failures:
                raise ExtractionOutputError(failures[sid], failure_code=failures[sid])
            if sid in results:
                payload = {"spans": results[sid]}
                self._validate_spans(payload, packet["untrusted_document_data"]["text"])
                return payload
            return deferred_payload(
                packet["untrusted_document_data"]["text"], DEFERRED_LIMIT_REASON
            )

    with TemporaryDirectory(prefix="fx6-replay-") as temporary:
        extractor = RetainedExtractor(NoTransport(), temporary, **flags)
        assert asdict(extractor.profile) == snapshot["extraction_profile"]

        class Bound:
            profile = extractor.profile

            def extract(self, packet):
                return extractor.extract(packet, context_graph=graph)

        discovery = discover_atomic_claims(graph, scope, extractor=Bound())
    outcome = extraction_outcome(
        graph, discovery, claim_pages=scope.selected_pages, include_source_failures=True
    )
    assert discovery.claims
    assert any(f["failure_code"] == "TABLE_QT1_SPAN_INVALID" for f in outcome["failed_sources"])
    summary = dict(
        policy_sha256=PIN,
        parse_graph_sha256=parse["graph_sha256"],
        source_sha256=graph.source_sha256,
        candidate_claims=len(discovery.claims),
        provider_calls=0,
        fresh_source_attestation="not_run",
        outcome=outcome,
    )
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    def deny(*args, **kwargs):
        raise AssertionError("FX6_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    replay(args.input.resolve(), args.output)


if __name__ == "__main__":
    main()
