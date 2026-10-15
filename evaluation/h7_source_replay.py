"""USD0 H6/H7 original-byte census, bounded-render comparison and hostile replay."""

import argparse
import json
import socket
from collections import Counter
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from proofops.adapters.local import evidence_source_h6 as h6
from proofops.adapters.local import evidence_source_h7 as h7
from proofops.adapters.local import evidence_source_verification_v1 as original_resolution
from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
from proofops.adapters.parsing.parser_artifacts import parser_artifact_path
from proofops.application.ingest.graph_fusion import ParserProfile, SourceArtifact, fuse_candidates


def deny(*a, **k):
    raise AssertionError("H7_PAID_OR_NETWORK_DISPATCH_FORBIDDEN")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def falsify(graph, ids):
    """Change one sensitive digit (otherwise one letter), keeping physical location."""
    blocks = {b.source_id: b for b in graph.blocks}
    batches = []
    for sid in ids:
        block = blocks[sid]
        candidate = block.candidates[block.winner]
        text = candidate.source.raw_text
        index = next((i for i, c in enumerate(text) if c.isdecimal()), None)
        if index is None:
            index = next(i for i, c in enumerate(text) if c.isalpha())
        char = str((int(text[index]) + 1) % 10) if text[index].isdecimal() else "X"
        text = text[:index] + char + text[index + 1 :]
        batch = next(b for b in graph.candidates if candidate in b.blocks)
        forged = replace(candidate, source=replace(candidate.source, raw_text=text))
        batches.append(replace(batch, blocks=(forged,), edges=()))
    return batches


def measure(graph, source, pages, out, *, downscale_pixels=None):
    old = h6.Reader(SimpleNamespace(fetch=deny), run_id="h7-usd0-baseline")
    before, after, forced = [], [], []
    for number in pages:
        baseline_reader = (
            old
            if downscale_pixels is None and out.name in {"lge", "report-806950b4e4"}
            else original_resolution
        )
        baseline = baseline_reader.attest_evidence_sources(
            graph, source, tenant_id=graph.tenant_id, physical_pages=(number,)
        )
        receipt = h7.attest_evidence_sources(
            graph, source, tenant_id=graph.tenant_id, physical_pages=(number,), run_id="h7-usd0"
        )
        checked = h7.replay_evidence_sources(receipt, graph, source, tenant_id=graph.tenant_id)
        assert all(
            r.source_id in {b.source_id for b in graph.blocks} for r in checked.verified_spans
        )
        write(out / f"page-{number}-before.json", baseline)
        write(out / f"page-{number}-after.json", receipt)
        before.extend(baseline["records"])
        after.extend(receipt["records"])
        if downscale_pixels is not None:
            small = h7.attest_evidence_sources(
                graph,
                source,
                tenant_id=graph.tenant_id,
                physical_pages=(number,),
                run_id="h7-forced",
                max_pixels=downscale_pixels,
            )
            write(out / f"page-{number}-forced.json", small)
            forced.extend(small["records"])
        print(
            out.name,
            number,
            dict(Counter(r["reason"] or "verified" for r in receipt["records"])),
            flush=True,
        )
    ids = {r["source_id"] for r in after if r["status"] == "verified"}
    prior = {r["source_id"] for r in before if r["status"] == "verified"}
    false_verified = 0
    adversarial = falsify(graph, sorted(ids))
    for batch in adversarial:
        altered = fuse_candidates((batch,), tenant_id=graph.tenant_id, mixed_parser=True)
        proof = h7.attest_evidence_sources(altered, source, tenant_id=graph.tenant_id)
        false_verified += sum(r["status"] == "verified" for r in proof["records"])
    result = dict(
        source_sha256=graph.source_sha256,
        pages=list(pages),
        blocks=len(after),
        before_verified=len(prior),
        after_verified=len(ids),
        lost_verified=sorted(prior - ids),
        false_verified=false_verified,
        adversarial_cases=len(adversarial),
        false_verified_definition="changed literal at unchanged original page/bbox",
        reasons=dict(Counter(r["reason"] or "verified" for r in after)),
        replay_equal=True,
        paid_calls=0,
        cost_usd="0",
        network="denied",
    )
    if forced:
        small_ids = {r["source_id"] for r in forced if r["status"] == "verified"}
        result["forced_downscale"] = dict(
            max_pixels=downscale_pixels,
            verified=len(small_ids),
            baseline_verified=len(ids),
            retained=len(ids & small_ids),
            lost=sorted(ids - small_ids),
            verified_agreement=len(ids & small_ids) / len(ids) if ids else None,
        )
    write(out / "summary.json", result)
    assert not prior - ids, "H7_NORMAL_SOURCE_REGRESSION"
    assert false_verified == 0, "H7_FALSE_SOURCE_ADMISSION"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mode", choices=("targets", "normal"), required=True)
    args = parser.parse_args()
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    lab = args.root / "outputs/agent-results/R108-redesign/lab"
    result = {}
    if args.mode == "targets":
        inputs = json.loads((lab / "fix/H5/manifest.json").read_text())["reports"]
        saved = json.loads((lab / "fix/H6/repro/local-reproduction.json").read_text())["reports"]
        for slug in ("lge", "report-806950b4e4"):
            report = next(r for r in inputs if r["slug"] == slug)
            item = next(r for r in saved if r["slug"] == slug)
            folder = Path(item["manifest"])
            manifest = json.loads((folder / "manifest.json").read_bytes())
            content = Path(report["pdf"]).read_bytes()
            assert sha256(content).hexdigest() == report["source_sha256"]
            artifact = SourceArtifact(
                manifest["tenant_id"],
                manifest["document_id"],
                manifest["document_version_id"],
                manifest["source_sha256"],
                manifest["object_version_id"],
                content,
                synthetic=manifest["synthetic_source"],
            )
            profile = ParserProfile(
                **(
                    item["profile"]
                    | dict(
                        physical_pages=tuple(item["profile"]["physical_pages"]),
                        claim_physical_pages=tuple(item["profile"]["claim_physical_pages"]),
                    )
                )
            )
            graph = OpenDataLoaderParser(folder.parents[2]).load_verified(
                artifact, profile, tenant_id=artifact.tenant_id
            )
            hashes = {
                parser_artifact_path(folder / name).name: sha256(
                    parser_artifact_path(folder / name).read_bytes()
                ).hexdigest()
                for name in ("manifest.json", "graph.json", "candidates.json", "quality.json")
            }
            result[slug] = measure(graph, content, item["selected_pages"], args.out / slug)
            assert hashes == {
                name: sha256((folder / name).read_bytes()).hexdigest() for name in hashes
            }
            assert sha256(Path(report["pdf"]).read_bytes()).hexdigest() == graph.source_sha256
            result[slug].update(
                input_hashes=hashes, saved_parse_replay_equal=True, original_pdf=report["pdf"]
            )
            write(args.out / "targets.json", result)
    else:
        from evaluation.pa9_source_gate import fixture

        states = dict(
            lg13=args.root / ".local/w7-inputs/lgchem-server",
            dl4_naver=lab / "perf/PA9/naver-server",
            dl4_kia=lab / "perf/PA9/kia-server",
        )
        for name, state in states.items():
            graph, source, discovery, _, _ = fixture(state)
            # Include every returned-draft DL4 physical page, even when an old
            # extraction omitted its claims. Retain the original subset mapping.
            if name == "lg13":
                pages = sorted({b.page_num for b in graph.blocks})
            else:
                golds = json.loads((lab / "fix/G1/DL4-gold.json").read_text())["golds"]
                company = name.removeprefix("dl4_")
                gold_pages = {g["page"] for g in golds if g["company"] == company}
                page_map = json.loads((state / "result-1.json").read_text())["page_map"]
                pages = [i + 1 for i, p in enumerate(page_map) if p in gold_pages]
                assert len(pages) == len(gold_pages), "H7_DL4_ORIGINAL_PAGE_MAPPING_MISSING"
            result[name] = measure(
                graph,
                source,
                pages,
                args.out / name,
                downscale_pixels=3_000_000 if name == "lg13" else None,
            )
            write(args.out / "normal.json", result)


if __name__ == "__main__":
    main()
