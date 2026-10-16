"""O1 bounded paid page OCR evaluation against immutable E2E control artifacts.

Prepare freezes inputs before HTTP. Collection phases are restart-safe and never
retry an uncertain provider call. Evaluation/replay is offline and sends no PDFs.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sqlite3
from collections import Counter
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from proofops.adapters.local.upstage_ocr_page import PageOCRStore, parse_response, render_page
from proofops.adapters.local.upstage_ocr_profile import Reader, claim_source_policy, native_policy
from proofops.adapters.parsing.parser_artifacts import (
    iter_parser_artifacts,
    parser_artifact_path,
    read_parser_json,
)
from proofops.application.evidence.citations import _normalized
from proofops.application.ingest.graph_fusion import (
    QualityIssue,
    candidates_from_snapshot,
    fuse_candidates,
)
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef

CHOICE = {
    "naver": [83, 84, 89, 90, 184, 191, 195],
    "kia": [20, 2, 26, 28, 106, 130],
    "hyundai": [22, 41, 139],
    "posco": [39, 42, 130],
    "samsung": [14, 73],
    "sk": [19, 23, 72],
}


def write(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    path.chmod(0o600)


def stored_inputs(state):
    pilot = json.loads((state / "pilot.json").read_text())
    file = next(iter_parser_artifacts(state / "parser-prepared", "graph.json"))
    manifest = json.loads(file.with_name("manifest.json").read_text())
    for name in ("graph.json", "candidates.json", "quality.json"):
        artifact = parser_artifact_path(file.with_name(name), manifest=manifest)
        assert sha256(artifact.read_bytes()).hexdigest() == manifest["artifacts"][artifact.name]
    graph = fuse_candidates(
        candidates_from_snapshot(read_parser_json(file.with_name("candidates.json"))),
        tenant_id=pilot["tenant_id"],
        fusion_version=manifest["fusion_version"],
    )
    assert graph.to_dict() == read_parser_json(file)
    issues = tuple(
        QualityIssue(**(v | {"source_ids": tuple(v["source_ids"])}))
        for v in json.loads(file.with_name("quality.json").read_text())
    )
    graph = replace(graph, issues=issues)
    source = Path(pilot["source_path"]).read_bytes()
    assert sha256(source).hexdigest() == graph.source_sha256 == pilot["source_sha256"]
    receipts = {}
    with sqlite3.connect((state / "state.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        for rid, value in db.execute(
            "SELECT record_id,value FROM job_records WHERE kind='artifact'"
        ):
            envelope = json.loads(value)
            for key in ("native_paragraph_attestation", "claim_source_attestation"):
                if key in envelope:
                    receipts.setdefault(key, []).append((rid, envelope[key]))
    # Stable complete claim revision: pick the most records, never mix atomic.
    native = max(receipts["native_paragraph_attestation"], key=lambda x: len(x[1]["records"]))
    claim = max(receipts["claim_source_attestation"], key=lambda x: len(x[1]["records"]))
    return pilot, graph, source, native, claim


def prepare(root, out):
    path = out / "sample.json"
    if path.exists():
        raise ValueError("sample already frozen")
    pages = []
    first = []
    rest = []
    for company, selected in CHOICE.items():
        folder = "sprint5/E2E3" if company in {"naver", "kia"} else "sprint6/E2E4"
        state = (
            root
            / "outputs/agent-results/R108-redesign/lab"
            / folder
            / "states"
            / (company + "-attempt3" if folder.startswith("sprint5") else company)
        )
        if (
            not next(iter_parser_artifacts(state / "parser-prepared", "graph.json"), None)
            and company == "posco"
        ):
            state = state.with_name("posco-attempt2")
        pilot, graph, source, native, claim = stored_inputs(state)
        for num in selected:
            image = render_page(source, num)
            entry = dict(
                company=company,
                state=str(state),
                page=num,
                source_path=pilot["source_path"],
                tenant_id=pilot["tenant_id"],
                original_run_id=pilot["run_id"],
                evaluation_run_id=str(uuid4()),
                manifest=image["manifest"],
                graph_sha256=canonical_hash(graph.to_dict()),
                native_receipt_sha256=canonical_hash(native[1]),
                claim_receipt_sha256=canonical_hash(claim[1]),
                features=dict(
                    short_korean=sum(
                        bool(re.search("[가-힣]", b.candidates[b.winner].source.raw_text))
                        and len(b.candidates[b.winner].source.raw_text) < 80
                        for b in graph.blocks
                        if b.page_num == num and b.winner is not None
                    ),
                    long_korean=sum(
                        bool(re.search("[가-힣]", b.candidates[b.winner].source.raw_text))
                        and len(b.candidates[b.winner].source.raw_text) >= 80
                        for b in graph.blocks
                        if b.page_num == num and b.winner is not None
                    ),
                    numbers_percent=sum(
                        bool(re.search(r"\d|%", b.candidates[b.winner].source.raw_text))
                        for b in graph.blocks
                        if b.page_num == num and b.winner is not None
                    ),
                    bullets=sum(
                        bool(re.search("[•·]", b.candidates[b.winner].source.raw_text))
                        for b in graph.blocks
                        if b.page_num == num and b.winner is not None
                    ),
                    small_box=sum(
                        b.candidates[b.winner].bbox[3] - b.candidates[b.winner].bbox[1] < 18
                        for b in graph.blocks
                        if b.page_num == num
                        and b.winner is not None
                        and b.candidates[b.winner].bbox
                    ),
                    unresolved=sum(
                        r["status"] == "unresolved"
                        for r in native[1]["records"]
                        if next(
                            (b.page_num for b in graph.blocks if b.source_id == r["source_id"]),
                            None,
                        )
                        == num
                    ),
                ),
            )
            (first if num == selected[0] else rest).append(entry)
            (out / "pages").mkdir(mode=0o700, exist_ok=True)
            (out / "pages" / f"{company}-{num}.png").write_bytes(image["png"])
    pages = first + rest
    assert (
        len(pages) == 24 and len({(p["manifest"]["source_sha256"], p["page"]) for p in pages}) == 24
    )
    write(
        path,
        dict(
            schema="o1_fixed_sample_v1",
            policy=claim_source_policy(),
            native_policy=native_policy(),
            pages=pages,
            repeat_indices=list(range(6)),
            max_calls=36,
            cap_usd="0.50",
        ),
    )


def collect(out, phase):
    sample = json.loads((out / "sample.json").read_text())
    if sample["policy"] != claim_source_policy():
        raise ValueError("pinned evaluation policy changed")
    db = PageOCRStore.from_env()
    indices = range(6) if phase == "first" else range(6, 24) if phase == "remaining" else range(6)
    for index in indices:
        if (
            phase == "first"
            and sample.get("prior_policy")
            and index < sample.get("prior_attempted", 2)
        ):
            continue  # Initial success/failure are retained; new reads use repeat slots.
        p = sample["pages"][index]
        name = f"{p['company']}-{p['page']}" + ("-repeat" if phase == "repeats" else "")
        target = out / "collections" / (name + ".json")
        if target.exists():
            continue
        image = render_page(Path(p["source_path"]).read_bytes(), p["page"])
        assert image["manifest"] == p["manifest"]
        if phase == "repeats":
            # Mark before force-call; uncertainty forbids retry on resume.
            pending = target.with_suffix(".pending")
            if pending.exists():
                raise ValueError("uncertain repeat cannot be retried")
            pending.parent.mkdir(mode=0o700, exist_ok=True)
            pending.write_text("reserved dispatch\n")
        collection = db.fetch(
            image, tenant_id=p["tenant_id"], run_id=p["evaluation_run_id"], force=phase == "repeats"
        )
        write(target, collection)
        print(
            name,
            collection["request_id"],
            len(parse_response(bytes.fromhex(collection["response_hex"]))["words"]),
            flush=True,
        )
    write(out / "usage.json", db.usage())


def negatives(out):
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject

    from tests.acceptance.test_parsing import TENANT, candidate
    from tests.integration.test_selected_cell_table_verification import grid_pdf

    db = PageOCRStore.from_env()
    cases = [
        ("hidden", "1234", "1234", "tCO2e", "tCO2e"),
        ("overpaint", "1234", "1234", "tCO2e", "tCO2e"),
        ("digit", "1234", "1235", "tCO2e", "tCO2e"),
        ("decimal", "12.34", "12.35", "tCO2e", "tCO2e"),
        ("sign", "-1234", "1234", "tCO2e", "tCO2e"),
        ("unit", "1234", "1234", "tCO2e", "kgCO2e"),
    ]
    fixed = []
    for i, (name, visible, claimed, unit, wrong_unit) in enumerate(cases, 1):
        text = f"Case {i} emissions {visible} {unit}"
        source = grid_pdf([(72, 720, text)])
        if name in {"hidden", "overpaint"}:
            writer = PdfWriter(clone_from=PdfReader(io.BytesIO(source)))
            page = writer.pages[0]
            stream = DecodedStreamObject()
            content = page.get_contents().get_data()
            if name == "hidden":
                content = content.replace(b"BT", b"BT 3 Tr")
            else:
                content += b" 1 1 1 rg 0 0 600 800 re f"
            stream.set_data(content)
            page[NameObject("/Contents")] = writer._add_object(stream)
            buffer = io.BytesIO()
            writer.write(buffer)
            source = buffer.getvalue()
        path = out / "negatives" / (name + ".pdf")
        path.parent.mkdir(mode=0o700, exist_ok=True)
        path.write_bytes(source)
        path.chmod(0o600)
        image = render_page(source, 1)
        (out / "negatives" / (name + ".png")).write_bytes(image["png"])
        fixed.append(
            dict(
                name=name,
                source_path=str(path),
                manifest=image["manifest"],
                expected_raw=f"Case {i} emissions {claimed} {wrong_unit}",
                run_id=str(uuid4()),
                tenant_id=TENANT,
            )
        )
    frozen = out / "negatives-sample.json"
    if frozen.exists():
        fixed = json.loads(frozen.read_text())["cases"]
    else:
        write(frozen, dict(policy=claim_source_policy(), cases=fixed))
    results = []
    for case in fixed:
        path = out / "negatives" / (case["name"] + "-result.json")
        if path.exists():
            results.append(json.loads(path.read_text()))
            continue
        source = Path(case["source_path"]).read_bytes()
        image = render_page(source, 1)
        assert image["manifest"] == case["manifest"]
        try:
            collection = db.fetch(image, tenant_id=TENANT, run_id=case["run_id"])
            write(out / "negatives" / (case["name"] + "-collection.json"), collection)
            batch = replace(
                candidate(
                    case["name"],
                    [("P", "paragraph", case["expected_raw"], (70, 710, 400, 745), ())],
                ),
                source_sha256=sha256(source).hexdigest(),
            )
            graph = fuse_candidates((batch,), tenant_id=TENANT)
            reader = Reader(db, run_id=case["run_id"])
            receipt = reader.attest_native_sources(graph, source, tenant_id=TENANT)
            reader.replay_native_sources(receipt, graph, source, tenant_id=TENANT)
            claim = reader.attest_claim_spans(
                graph, source, (graph.blocks[0].source_ref(),), tenant_id=TENANT
            )
            reader.recompute_claim_receipt(
                claim, graph, source, (graph.blocks[0].source_ref(),), tenant_id=TENANT
            )
            write(out / "negatives" / (case["name"] + "-native.json"), receipt)
            write(out / "negatives" / (case["name"] + "-claim.json"), claim)
            result = dict(
                name=case["name"],
                native_status=receipt["records"][0]["status"],
                claim_status=claim["records"][0]["status"],
                native_reason=receipt["records"][0]["reason"],
                claim_reason=claim["records"][0]["reason"],
            )
        except ValueError as error:
            result = dict(
                name=case["name"],
                native_status="unresolved",
                claim_status="unresolved",
                collection_error=str(error),
            )
        write(path, result)
        results.append(result)
        print(case["name"], result, flush=True)
    write(
        out / "negatives-results.json",
        dict(
            cases=results,
            false_verified=sum(
                r["native_status"] == "verified" or r["claim_status"] == "verified" for r in results
            ),
            usage=db.usage(),
        ),
    )


def distance(a, b):
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        new = [i]
        for j, y in enumerate(b, 1):
            new.append(min(new[-1] + 1, row[j] + 1, row[j - 1] + (x != y)))
        row = new
    return row[-1]


def evaluate(out):
    sample = json.loads((out / "sample.json").read_text())
    db = PageOCRStore.from_env()
    if sample["policy"] != claim_source_policy():
        raise ValueError("pinned evaluation policy changed")
    results = []
    cross = Counter()
    native_cross = Counter()
    numeric_errors = 0
    for company in CHOICE:
        pages = [p for p in sample["pages"] if p["company"] == company]
        pilot, graph, source, old_native, old_claim = stored_inputs(Path(pages[0]["state"]))
        assert canonical_hash(graph.to_dict()) == pages[0]["graph_sha256"]
        assert canonical_hash(old_native[1]) == pages[0]["native_receipt_sha256"]
        assert canonical_hash(old_claim[1]) == pages[0]["claim_receipt_sha256"]
        selected = {p["page"] for p in pages}
        blocks = {b.source_id: b for b in graph.blocks}
        scoped = replace(graph, blocks=tuple(b for b in graph.blocks if b.page_num in selected))
        reader = Reader(db, run_id=pages[0]["evaluation_run_id"])
        # The transport must not be reachable during this phase.
        db.transport = lambda png: (_ for _ in ()).throw(ValueError("OFFLINE_NETWORK_FORBIDDEN"))
        page_collections = []
        for p in pages:
            name = f"{company}-{p['page']}"
            repeated = out / "collections" / (name + "-repeat.json")
            collection = json.loads(
                (
                    repeated if repeated.exists() else out / "collections" / (name + ".json")
                ).read_text()
            )
            db.validate(collection, render_page(source, p["page"]), tenant_id=pilot["tenant_id"])
            page_collections.append(collection)
        modules, seen = reader._modules(scoped, source, pilot["tenant_id"], page_collections)
        native = reader._finish(
            modules["source_verification"].attest_native_sources(
                scoped, source, tenant_id=pilot["tenant_id"], geometry_mode="glyph"
            ),
            seen,
            native=True,
        )
        reader.replay_native_sources(native, scoped, source, tenant_id=pilot["tenant_id"])
        old_n = {r["source_id"]: r for r in old_native[1]["records"]}
        for record in native["records"]:
            if blocks[record["source_id"]].kind == "paragraph":
                native_cross[(old_n[record["source_id"]]["status"], record["status"])] += 1
        refs = tuple(
            SourceRef(**r["ref"])
            for r in old_claim[1]["records"]
            if blocks[r["ref"]["source_id"]].page_num in selected
        )
        modules, seen = reader._modules(scoped, source, pilot["tenant_id"], page_collections)
        claim = reader._finish(
            modules["glyph_alignment_verification"].attest_claim_spans(
                scoped, source, refs, tenant_id=pilot["tenant_id"]
            ),
            seen,
        )
        reader.recompute_claim_receipt(claim, scoped, source, refs, tenant_id=pilot["tenant_id"])
        write(out / "attestations" / (company + "-native.json"), native)
        write(out / "attestations" / (company + "-claim.json"), claim)
        old_by_ref = {canonical_hash(r["ref"]): r for r in old_claim[1]["records"]}
        for r in claim["records"]:
            old = old_by_ref[canonical_hash(r["ref"])]
            cross[(old["status"], r["status"])] += 1
        # Independent block readings: count once per source, not nested copies.
        old_readings = old_claim[1].get("readings", {})
        for record in native["records"]:
            sid = record["source_id"]
            block = blocks[sid]
            if block.kind != "paragraph" or "rendered" not in record:
                continue
            raw = block.candidates[block.winner].source.raw_text
            rendered = record["rendered"]
            text = rendered.get("text", "")
            normalized = _normalized(raw)
            actual = _normalized(text)
            old_rendered = old_n[sid].get("rendered", old_readings.get(sid, {}).get("rendered", {}))
            results.append(
                dict(
                    company=company,
                    page=block.page_num,
                    source_id=sid,
                    bbox=block.candidates[block.winner].bbox,
                    native=raw,
                    apple=old_rendered.get("text"),
                    new=text if rendered["status"] == "read" else None,
                    status=rendered["status"],
                    reason=rendered.get("reason"),
                    raw_exact=raw == text,
                    normalized_exact=normalized == actual,
                    cer=distance(normalized, actual) / max(1, len(normalized))
                    if rendered["status"] == "read"
                    else None,
                    old_verdict=old_n[sid]["status"],
                    new_verdict=record["status"],
                    word_ids=rendered.get("word_ids", []),
                )
            )
    old_verified = sum(n for (old, new), n in cross.items() if old == "verified")
    retained = cross[("verified", "verified")] / max(1, old_verified)
    collections = []
    for p in sample["pages"]:
        name = f"{p['company']}-{p['page']}"
        repeated = out / "collections" / (name + "-repeat.json")
        collections.append(
            json.loads(
                (
                    repeated if repeated.exists() else out / "collections" / (name + ".json")
                ).read_text()
            )
        )
    assigned = {
        (r["company"], r["page"], wid)
        for r in results
        if r["status"] == "read"
        for wid in r["word_ids"]
    }
    numeric_read_errors = sum(
        re.findall(r"[+-]?\d[\d,.]*%?", r["native"]) != re.findall(r"[+-]?\d[\d,.]*%?", r["new"])
        for r in results
        if r["status"] == "read"
    )
    numeric_errors = sum(
        r["new_verdict"] == "verified"
        and re.findall(r"[+-]?\d[\d,.]*%?", r["native"])
        != re.findall(r"[+-]?\d[\d,.]*%?", r["new"])
        for r in results
    )
    comparable = [r for r in results if r["status"] == "read"]
    summary = dict(
        block_readings=len(results),
        raw_exact_rate=sum(r["raw_exact"] for r in results) / max(1, len(results)),
        normalized_exact_rate=sum(r["normalized_exact"] for r in results) / max(1, len(results)),
        mean_cer=sum(r["cer"] for r in comparable) / len(comparable) if comparable else None,
        read_rate=sum(r["status"] == "read" for r in results) / max(1, len(results)),
        assigned_word_count=len(assigned),
        raw_exact_rate_of_read=sum(r["raw_exact"] for r in comparable) / len(comparable)
        if comparable
        else None,
        normalized_exact_rate_of_read=sum(r["normalized_exact"] for r in comparable)
        / len(comparable)
        if comparable
        else None,
        mean_cer_of_read=sum(r["cer"] for r in comparable) / len(comparable)
        if comparable
        else None,
        numeric_read_errors=numeric_read_errors,
        provider_word_count=sum(
            len(parse_response(bytes.fromhex(c["response_hex"]))["words"]) for c in collections
        ),
        claim_cross={f"{a}->{b}": n for (a, b), n in cross.items()},
        native_cross={f"{a}->{b}": n for (a, b), n in native_cross.items()},
        claim_verified_retention=retained,
        numeric_error_promotions=numeric_errors,
        latencies=[c["latency_seconds"] for c in collections],
        usage=db.usage(),
        cache_cost_usd="0",
        gate_retention=retained >= 0.95,
        gate="FAIL_HOLD_LIVE_ROLLOUT" if retained < 0.95 else "pending_image_review_and_negatives",
    )
    write(out / "readings.json", results)
    write(out / "metrics.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k not in {"latencies"}}, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--phase",
        choices=["prepare", "first", "remaining", "repeats", "negatives", "evaluate"],
        required=True,
    )
    args = parser.parse_args()
    args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.phase == "prepare":
        prepare(args.root, args.output)
    elif args.phase == "evaluate":
        evaluate(args.output)
    else:
        key_path = args.root / ".env.upstage.local"
        os.environ["UPSTAGE_API_KEY"] = next(
            line.split("=", 1)[1].strip()
            for line in key_path.read_text().splitlines()
            if line.startswith("UPSTAGE_API_KEY=")
        )
        if args.phase == "negatives":
            negatives(args.output)
        else:
            collect(args.output, args.phase)


if __name__ == "__main__":
    main()
