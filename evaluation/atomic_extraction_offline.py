"""Offline candidate-only evaluation; never imports credentials or invokes a provider.

Generation reads saved parser/native inputs before looking at provisional gold.
Use the unchanged DEC-13 matcher; parent-source support is a separate diagnostic,
not atomic recall or an independent human accuracy measurement.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from proofops.adapters.parsing.parser_artifacts import (
    iter_parser_artifacts,
    parser_artifact_path,
    read_parser_json,
)
from proofops.application.claims import ExtractionOutputError, validate_extraction_response
from proofops.application.ingest.atomic_candidates import PROFILE, atomic_candidates
from proofops.application.ingest.graph_fusion import candidates_from_snapshot, fuse_candidates
from proofops.domain.sentences import sentence_spans
from proofops_agent.upstage_extraction import UpstageClaimExtractor


class NoProvider:
    def complete(self, *args, **kwargs):
        raise AssertionError("OFFLINE_PROVIDER_FORBIDDEN")


def read(path):
    return read_parser_json(path)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def loss_diagnostic(scorer, gold, claims, matched):
    """Classify source-catalog loss, not human semantic correctness."""
    peers = [c for c in claims if (c["_company"], c["_page"]) == (gold["_company"], gold["_page"])]
    strict = max(
        (
            max(
                scorer.sim(gold.get("atomic_proposition"), c["_quote"]),
                scorer.sim(gold["_quote"], c["_quote"]),
            )
            for c in peers
        ),
        default=0.0,
    )
    parent = max(peers, key=lambda c: scorer.sim(gold["_quote"], c["parent_quote"]), default=None)
    support = scorer.sim(gold["_quote"], parent["parent_quote"]) if parent else 0.0
    siblings = [
        c
        for c in peers
        if parent
        and (c["source_id"], c["parent_quote"]) == (parent["source_id"], parent["parent_quote"])
    ]
    siblings.sort(key=lambda c: c["char_start"])
    preserved = bool(parent) and scorer.norm(
        " ".join(c["_quote"] for c in siblings)
    ) == scorer.norm(parent["parent_quote"])
    bad_purpose = any(
        re.search(r"\b(?:및|and)$", c["_quote"].strip())
        and re.search(
            r"(?:을|를|기)\s*위해|(?:을|를)\s*위한|목적으로",
            " ".join(s["_quote"] for s in siblings if s["char_start"] > c["char_start"]),
        )
        for c in siblings
    )
    category = None
    if not matched:
        if strict >= 0.82:
            category = "one_to_one_competition"
        elif support < 0.82:
            category = "candidate_loss"
        elif bad_purpose or not preserved or len(siblings) < 2:
            category = "incorrect_split"
        else:
            category = "preserved_after_split"
    return {
        "strict_matched": matched,
        "category": category,
        "best_strict_similarity": strict,
        "best_parent_similarity": support,
        "literal_parent_reconstructed": preserved,
        "closest_atoms": [c["_quote"] for c in siblings],
    }


def compare_losses(scorer, gold, catalogs, baseline, output, baseline_sha256):
    old = [scorer.normalize_claim(c) for c in baseline["graph_legacy_catalog"]]
    before = [scorer.normalize_claim(c) for c in baseline["graph_atomic_v2"]]
    after = [scorer.normalize_claim(c) for c in catalogs["graph_atomic_v2"]]
    legacy_match, _ = scorer.align(gold, old)
    before_match, _ = scorer.align(gold, before)
    after_match, _ = scorer.align(gold, after)
    rows = []
    for i in sorted(
        (set(legacy_match) - set(before_match)) | (set(legacy_match) - set(after_match))
    ):
        g = gold[i]
        b = loss_diagnostic(scorer, g, before, i in before_match)
        a = loss_diagnostic(scorer, g, after, i in after_match)
        # This post-generation probe diagnoses the 15 advisor losses; never feeds
        # gold into either saved-source candidate construction or matching.
        standalone = atomic_candidates(g["_quote"]) if b["category"] == "candidate_loss" else ()
        rows.append(
            {
                "claim_id": g["claim_id"],
                "company": g["_company"],
                "page": g["_page"],
                "quote": g["_quote"],
                "before": b,
                "after": a,
                "standalone_candidate_recovered": bool(standalone),
            }
        )
    categories = (
        "candidate_loss",
        "preserved_after_split",
        "incorrect_split",
        "one_to_one_competition",
    )
    slices = {}
    for name, companies in (
        ("designated_unexposed_3", {"sk", "hyundai", "posco"}),
        ("samsung", {"samsung"}),
    ):
        selected = [r for r in rows if r["company"] in companies]
        lost = [r for r in selected if r["before"]["category"] == "candidate_loss"]
        slices[name] = {
            stage: {
                category: sum(r[stage]["category"] == category for r in selected)
                for category in categories
            }
            for stage in ("before", "after")
        }
        slices[name]["candidate_loss_recovery"] = {
            "baseline_count": len(lost),
            "standalone_recovered": sum(r["standalone_candidate_recovered"] for r in lost),
            "strict_recovered": sum(r["after"]["strict_matched"] for r in lost),
            "parent_supported": sum(r["after"]["best_parent_similarity"] >= 0.82 for r in lost),
        }
    result = {
        "gold": "provisional AI draft, not human reviewed",
        "threshold": 0.82,
        "baseline_candidates_sha256": baseline_sha256,
        "slices": slices,
        "rows": rows,
        ("limitations"): (
            "split preservation is literal source reconstruct"
            "ion with AI case inspection, not semantic certif"
            "ication"
        ),
    }
    (output / "loss-diagnostics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    lines = [
        "# P3b 탈락 행 진단 — 임시 정답(AI) 기준",
        "DEC-13 회사/물리쪽·0.82·일대일 유지. 원문 보존≠의미 인증.",
        "| ID | 쪽 | 수정 전 4분류 | 수정 후 4분류/복구 | parent 지원 |",
        "|---|---:|---|---|---|",
    ]
    labels = {
        "candidate_loss": "후보 소실",
        "preserved_after_split": "분해 후 보존",
        "incorrect_split": "잘못된 분해",
        "one_to_one_competition": "일대일 경쟁",
        None: "strict 복구",
    }
    lines.extend(
        f"| {r['claim_id']} | {r['page']} | {labels[r['before']['category']]} | "
        f"{labels[r['after']['category']]} | {r['after']['best_parent_similarity']:.3f} |"
        for r in rows
    )
    lines.append("삼성 개발 노출 분리. 지정 3사도 진단에 노출되어 독립 holdout이 아니다.")
    (output / "loss-diagnostics.md").write_text("\n".join(lines) + "\n")
    return result


def evaluate(lab_root: Path, output: Path, *, baseline: Path | None = None) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    catalogs: dict[str, list[dict]] = {
        "graph_legacy_catalog": [],
        "graph_atomic_v2": [],
        "native_legacy_catalog": [],
        "native_atomic_v2": [],
    }
    inputs, deferred, rejected = [], [], []
    gate_diagnostics = []
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
        paths = list(iter_parser_artifacts(state / "parser-prepared", "graph.json"))
        if len(paths) != 1:
            raise ValueError("AMBIGUOUS_SAVED_GRAPH")
        path = paths[0]
        manifest = read(path.parent / "manifest.json")
        for name in ("graph.json", "candidates.json"):
            source = parser_artifact_path(path.parent / name, manifest=manifest)
            if digest(source) != manifest["artifacts"][source.name]:
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
                counts: dict[str, int] = {}
                entries = extractor._atomic_entries(packet, text, contexts, diagnostics=counts)
            except ExtractionOutputError as error:
                deferred.append({**base, "profile": PROFILE, "reason": str(error)})
                continue
            gate_diagnostics.append({**base, "profile": "graph_atomic_v2", **counts})
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
                            "context_dependent": entry["context_dependent"],
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
                counts = {}
                native_atoms = atomic_candidates(text, diagnostics=counts)
                gate_diagnostics.append({**base, "profile": "native_atomic_v2", **counts})
                for profile, spans in (
                    ("native_legacy_catalog", [(s, e, text[s:e]) for s, e in sentence_spans(text)]),
                    (
                        "native_atomic_v2",
                        [
                            (c.start, c.end, text[c.parent_start : c.parent_end])
                            for c in native_atoms
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
        "gate_diagnostics": gate_diagnostics,
        "candidate_kinds": {
            name: dict(Counter(c["source_kind"] for c in rows)) for name, rows in catalogs.items()
        },
    }
    if baseline is not None:
        result["loss_diagnostics"] = compare_losses(
            scorer, gold, catalogs, read(baseline), output, digest(baseline)
        )
    (output / "candidates.json").write_text(
        json.dumps(catalogs, ensure_ascii=False, indent=2) + "\n"
    )
    (output / "scores.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-candidates", type=Path)
    args = parser.parse_args()
    result = evaluate(args.lab_root, args.output, baseline=args.baseline_candidates)
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
