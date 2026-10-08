"""Offline candidate-only evaluation; never imports credentials or invokes a provider.

Generation reads saved parser/native inputs before looking at provisional gold.
Use the unchanged DEC-13 matcher; parent-source support is a separate diagnostic,
not atomic recall or an independent human accuracy measurement.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from proofops.application.claims import ExtractionOutputError, validate_extraction_response
from proofops.application.ingest.atomic_candidates import PROFILE, atomic_candidates
from proofops.application.ingest.graph_fusion import candidates_from_snapshot, fuse_candidates
from proofops.domain.sentences import sentence_spans
from proofops_agent.upstage_extraction import UpstageClaimExtractor


class NoProvider:
    def complete(self, *args, **kwargs):
        raise AssertionError("OFFLINE_PROVIDER_FORBIDDEN")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def evaluate(lab_root: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    catalogs: dict[str, list[dict]] = {
        "graph_legacy_catalog": [],
        "graph_atomic_v2": [],
        "native_legacy_catalog": [],
        "native_atomic_v2": [],
    }
    inputs, deferred, rejected = [], [], []
    extractor = UpstageClaimExtractor(
        NoProvider(),
        output / "catalog-receipts",
        extraction_source_ids=True,
        extraction_atomic=True,
        extraction_context=True,
        extraction_table_context=True,
    )
    for company in ("sk", "hyundai", "posco", "samsung"):
        state = lab_root / "sprint5/E2E3/states" / f"{company}-attempt3"
        pilot = read(state / "pilot.json")
        pages = set(pilot["claim_pages"])
        paths = list((state / "parser-prepared").glob("*/*/*/graph.json"))
        if len(paths) != 1:
            raise ValueError("AMBIGUOUS_SAVED_GRAPH")
        path = paths[0]
        manifest = read(path.parent / "manifest.json")
        for name in ("graph.json", "candidates.json"):
            source = path.parent / name
            if digest(source) != manifest["artifacts"][name]:
                raise ValueError("SAVED_INPUT_HASH_MISMATCH")
            inputs.append({"path": str(source), "sha256": digest(source)})
        graph = fuse_candidates(
            candidates_from_snapshot(read(path.parent / "candidates.json")),
            tenant_id=pilot["tenant_id"],
            fusion_version=manifest.get("fusion_version", 1),
        )
        if graph.to_dict() != read(path):
            raise ValueError("SAVED_GRAPH_RECONSTRUCTION_MISMATCH")
        for b in graph.blocks:
            if b.page_num not in pages or not b.normalized_text.strip():
                continue
            if b.winner is None or b.quality not in ("verified", "unverified"):
                deferred.append({"company": company, "source_id": b.source_id, "reason": b.quality})
                continue
            text = b.normalized_text
            packet = {
                "tenant_id": graph.tenant_id,
                "document_version_id": graph.document_version_id,
                "parse_manifest_id": graph.parse_manifest_id,
                "source_sha256": graph.source_sha256,
                "untrusted_document_data": {
                    "source_id": b.source_id,
                    "text": text,
                    "kind": b.kind,
                    "page_num": b.page_num,
                },
            }
            base = {
                "company_id": company,
                "physical_page": b.page_num,
                "source_id": b.source_id,
                "source_kind": b.kind,
                "verification_state": "candidate",
            }
            try:
                old = extractor._sentence_index(text, b.source_id)
            except ExtractionOutputError as error:
                deferred.append({**base, "profile": "legacy", "reason": str(error)})
            else:
                for sid, (start, end) in old:
                    catalogs["graph_legacy_catalog"].append(
                        {
                            **base,
                            "claim_id": sid,
                            "quote": text[start:end],
                            "char_start": start,
                            "char_end": end,
                        }
                    )
            contexts = extractor._context_for(packet, graph)[0]
            try:
                entries = extractor._atomic_entries(packet, text, contexts)
            except ExtractionOutputError as error:
                deferred.append({**base, "profile": PROFILE, "reason": str(error)})
                continue
            for entry in entries:
                span = {
                    "char_start": entry["char_start"],
                    "char_end": entry["char_end"],
                    "quote": entry["text"],
                    "kind": "claim",
                    "reason": None,
                    "topic_ids": ["environment"],
                }
                try:
                    validate_extraction_response(
                        {"spans": [span]}, text, reject_unclosed_quotations=True
                    )
                except ValueError as error:
                    rejected.append({**base, "quote": entry["text"], "reason": str(error)})
                else:
                    catalogs["graph_atomic_v2"].append(
                        {
                            **base,
                            "claim_id": entry["sentence_id"],
                            "quote": entry["text"],
                            "parent_quote": entry["parent_quote"],
                            "char_start": entry["char_start"],
                            "char_end": entry["char_end"],
                        }
                    )
        native_path = lab_root / "gold-v1/native" / f"{company}.json"
        inputs.append({"path": str(native_path), "sha256": digest(native_path)})
        for page in read(native_path):
            if page["physical_page"] not in pages:
                continue
            for block in page["blocks"]:
                if block["type"] != 0:
                    continue
                text = "\n".join(
                    "".join(s["text"] for s in line["spans"]) for line in block["lines"]
                )
                base = {
                    "company_id": company,
                    "physical_page": page["physical_page"],
                    "source_id": f"native:{block['number']}",
                    "source_kind": "native_text",
                    "verification_state": "candidate",
                }
                for profile, spans in (
                    ("native_legacy_catalog", [(s, e, text[s:e]) for s, e in sentence_spans(text)]),
                    (
                        "native_atomic_v2",
                        [
                            (c.start, c.end, text[c.parent_start : c.parent_end])
                            for c in atomic_candidates(text)
                        ],
                    ),
                ):
                    for start, end, parent in spans:
                        catalogs[profile].append(
                            {
                                **base,
                                "claim_id": (
                                    f"{company}:{page['physical_page']}:"
                                    f"{block['number']}:{start}:{end}"
                                ),
                                "quote": text[start:end],
                                "parent_quote": parent,
                                "char_start": start,
                                "char_end": end,
                            }
                        )
    # No gold-driven candidate construction, thresholds or metric/unit rules.
    gold_path = lab_root / "gold-v1/draft.json"
    scorer_path = lab_root / "sprint4/SC/score_r108.py"
    spec = importlib.util.spec_from_file_location("dec13_scorer", scorer_path)
    assert spec and spec.loader
    scorer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scorer)
    gold, _ = scorer.normalize_gold(read(gold_path))
    scores = {}
    for profile, claims in catalogs.items():
        rows = [scorer.normalize_claim(c) for c in claims]
        slices = {}
        for company in ("sk", "hyundai", "posco", "samsung", "designated_unexposed_3"):
            companies = (
                {"sk", "hyundai", "posco"} if company == "designated_unexposed_3" else {company}
            )
            g = [c for c in gold if c["_company"] in companies]
            r = [c for c in rows if c["_company"] in companies]
            gm, rm = scorer.align(g, r)
            # This many-to-one source-support check deliberately reports only
            # quoted-source coverage. Repeated gold quotes are not atomic successes.
            supported = [
                c["claim_id"]
                for c in g
                if any(
                    c["_page"] == p["_page"]
                    and c["_company"] == p["_company"]
                    and scorer.sim(c["_quote"], p.get("parent_quote", p["_quote"])) >= 0.82
                    for p in r
                )
            ]
            slices[company] = {
                "matched": len(gm),
                "gold_count": len(g),
                "candidate_count": len(r),
                "precision": len(rm) / len(r) if r else None,
                "recall": len(gm) / len(g) if g else None,
                "source_support_count_many_to_one": len(supported),
                "matched_gold_ids": [g[i]["claim_id"] for i in sorted(gm)],
                "unmatched_gold_ids": [c["claim_id"] for i, c in enumerate(g) if i not in gm],
                "unmatched_candidates": [c["claim_id"] for i, c in enumerate(r) if i not in rm],
            }
        scores[profile] = slices
    result = {
        "profile": PROFILE,
        "provisional_gold": True,
        "human_reviewed": False,
        "provider_calls": 0,
        "actual_usd": 0,
        "llm_prompt_effect": "not_run",
        "gold_sha256": digest(gold_path),
        "scorer_sha256": digest(scorer_path),
        "matcher": "unchanged DEC-13 same-company/page greedy one-to-one similarity >=0.82",
        "limitations": [
            "candidate catalog precision is agreement with an incomplete AI draft",
            "candidate recall is not model-selected or verified end-to-end recall",
            "shared parent support is not atomic detection recall",
            "native blocks are kept separate; disconnected chart axes are not guessed",
            "graph is reconstructed pre-attestation; source quality is never promoted",
        ],
        "extraction_profile": asdict(extractor.profile),
        "inputs": inputs,
        "scores": scores,
        "deferred": deferred,
        "validator_rejected": rejected,
        "candidate_kinds": {
            name: dict(Counter(c["source_kind"] for c in rows)) for name, rows in catalogs.items()
        },
    }
    (output / "candidates.json").write_text(
        json.dumps(catalogs, ensure_ascii=False, indent=2) + "\n"
    )
    (output / "scores.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.lab_root, args.output)
    for profile, scores in result["scores"].items():
        print(
            profile,
            {
                company: {
                    k: v
                    for k, v in row.items()
                    if k in ("matched", "gold_count", "candidate_count", "precision", "recall")
                }
                for company, row in scores.items()
            },
        )


if __name__ == "__main__":
    main()
