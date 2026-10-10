"""SY1 local candidate veto replay; read-only SQLite, no model or runtime clients."""

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import replace
from pathlib import Path

from proofops.application.evidence.relation_attribution import (
    LEGACY_POLICY as POLICY,
)
from proofops.application.evidence.relation_attribution import (
    literal_scope_rejection,
    role_rejection,
)
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import _source_ref_from_dict


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def artifacts(path):
    before = digest(path)
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        rows = [
            (key, raw, json.loads(raw))
            for key, raw in db.execute(
                "SELECT record_id,value FROM job_records WHERE kind='artifact' ORDER BY rowid"
            )
        ]
    assert digest(path) == before
    return rows, before


def saved_blocks(state):
    blocks, pins = {}, []
    for manifest in (state / "parser-prepared").rglob("manifest.json"):
        meta = read(manifest)
        graph_path = manifest.with_name("graph.json")
        assert digest(graph_path) == meta["artifacts"]["graph.json"]
        graph = read(graph_path)
        for block in graph["blocks"]:
            assert (
                hashlib.sha256(block["raw_text"].encode()).hexdigest() == block["raw_text_sha256"]
            )
            blocks[block["source_id"]] = block
        pins.append(
            dict(path=str(manifest), sha256=digest(manifest), graph_file_sha256=digest(graph_path))
        )
    return blocks, pins


def veto(targets, ref, role, blocks):
    block = blocks.get(ref.source_id)
    text = block["raw_text"] if block else None
    scope = literal_scope_rejection(targets, ref, text)
    if block is not None and (
        ref.raw_text_sha256 != block["raw_text_sha256"]
        or ref.page_num != block["page_num"]
        or text[ref.char_start : ref.char_end] != ref.quote
    ):
        return "RELATION_SAVED_LITERAL_MISMATCH"
    if scope is not None:
        return scope
    return role_rejection(text, ref.char_start, ref.char_end, role)


def counts(rows):
    rejected = [r for r in rows if r["rejection"] is not None]
    return dict(
        candidates_before=len(rows),
        candidates_after=len(rows) - len(rejected),
        attribution_rejected=len(rejected),
        refusal_state="unknown",
        rejection_codes=dict(Counter(r["rejection"] for r in rejected)),
        stages={
            stage: dict(
                before=sum(r["stage"] == stage for r in rows),
                after=sum(r["stage"] == stage and r["rejection"] is None for r in rows),
            )
            for stage in sorted({r["stage"] for r in rows})
        },
    )


def state_replay(path):
    rows, before = artifacts(path)
    blocks, graph_pins = saved_blocks(path.parent)
    discovery = {}
    latest = {}
    for key, raw, data in rows:
        for claim in data.get("discovery", {}).get("claims", []):
            discovery[claim["claim_id"]] = claim
        if data.get("schema") == "local_tag_checkpoint_v1":
            latest[data["run_id"]] = (key, raw, data)
    candidates, checkpoint_pins, verdicts = [], [], Counter()
    for key, raw, envelope in latest.values():
        checkpoint_pins.append(dict(record_id=key, sha256=hashlib.sha256(raw).hexdigest()))
        for item in envelope["claims"]:
            cid = item["claim_id"]
            review = item.get("review_inputs") or {}
            packet = item.get("original_packet") or review.get("original_packet") or {}
            claim = review.get("claim") or discovery.get(cid)
            targets = [
                _source_ref_from_dict(r)
                for r in (claim or {}).get("source_refs", packet.get("claim_source_refs", []))
            ]
            verdicts["decided" if item.get("decision") else "undecided"] += 1
            seen = set()
            for stage, records in (
                ("preliminary_luna_quote", item.get("preliminary_records", [])),
                ("relation_span_or_quote", item.get("relation_records", [])),
            ):
                for record in records:
                    values = record.get("values") or {}
                    groups = (
                        [values.get("dimensions", {})]
                        if stage.startswith("preliminary")
                        else [v for v in values.values() if isinstance(v, dict)]
                    )
                    for dimensions in groups:
                        for role, value in dimensions.items():
                            if (
                                value is None
                                or not isinstance(value, dict)
                                or "source_id" not in value
                            ):
                                continue
                            ref = _source_ref_from_dict(value)
                            identity = (stage, role, canonical_hash(value))
                            if identity in seen:
                                continue
                            seen.add(identity)
                            candidates.append(
                                dict(
                                    claim_id=cid,
                                    stage=stage,
                                    role=role,
                                    source_id=ref.source_id,
                                    page=ref.page_num,
                                    quote=ref.quote,
                                    char_start=ref.char_start,
                                    char_end=ref.char_end,
                                    rejection=veto(targets, ref, role, blocks),
                                )
                            )
    assert digest(path) == before
    return dict(
        path=str(path),
        sha256_before=before,
        sha256_after=digest(path),
        checkpoint_pins=checkpoint_pins,
        graph_pins=graph_pins,
        **counts(candidates),
        stored_judgments=dict(verdicts),
        stored_judgments_unchanged=True,
        candidates=candidates,
    )


def reviewed_replay(ad):
    source_file = ad / "lab/sprint1/S/candidates.json"
    catalog = read(source_file)
    gold_file = (
        ad
        / "lab/gold-return/20261010/raw/정답셋_최종반납_20261010"
        / "20261007묶음review_AI_Claude_20261010.json"
    )
    reviewed = [r for r in read(gold_file)["sheets"]["3_후보확인"] if r["종류"] == "relation"]
    archive = catalog["archives"]["kia"]
    data, before = artifacts(Path(archive["db"]))
    pin = archive["pins"]["tag"]
    _, raw, checkpoint = next(r for r in data if r[0] == pin["record_id"])
    assert hashlib.sha256(raw).hexdigest() == pin["sha256"]
    claims = {c["claim_id"]: c for c in checkpoint["claims"]}
    cases = {c["claim_id"]: c for c in catalog["relation_cases"]}
    records = []
    for row in reviewed:
        case = cases[row["사례ID"]]
        candidate = next(c for c in case["candidates"] if c["span_id"] == row["후보ID"])
        request_path, response_path = Path(case["request_path"]), Path(case["response_path"])
        assert digest(request_path) == case["request_file_sha256"]
        assert digest(response_path) == case["response_file_sha256"]
        assert row["입력_SHA256"] == digest(source_file)
        text = candidate["context_quote"]
        assert (
            text == row["전체 문맥"]
            and text[candidate["raw_start"] : candidate["raw_end"]] == row["후보 인용"]
        )
        packet = claims[row["사례ID"]]["original_packet"]
        targets = tuple(_source_ref_from_dict(r) for r in packet["claim_source_refs"])
        original = _source_ref_from_dict(case["original_ref"])
        ref = replace(
            original,
            char_start=candidate["raw_start"],
            char_end=candidate["raw_end"],
            quote=candidate["quote"],
        )
        rejection = literal_scope_rejection(targets, ref, text)
        role_code = role_rejection(text, ref.char_start, ref.char_end, row["역할"])
        records.append(
            dict(
                row_id=row["ID"],
                candidate_id=row["후보ID"],
                claim_id=row["사례ID"],
                stage="legacy_luna_quote_then_offline_occurrences",
                claim_page=row["주장쪽"],
                source_page=row["물리쪽"],
                role=row["역할"],
                quote=ref.quote,
                rejection=rejection or role_code,
                role_rejection=role_code,
                reviewed_ownership=row["귀속 확인"],
                request_path=str(request_path),
                request_sha256=digest(request_path),
                response_path=str(response_path),
                response_sha256=digest(response_path),
                state_after="unknown" if rejection or role_code else "candidate",
            )
        )
    assert len(records) == 27
    return dict(
        source_candidates_sha256=digest(source_file),
        review_file_sha256=digest(gold_file),
        archive_sha256_before=before,
        archive_sha256_after=digest(Path(archive["db"])),
        **counts(records),
        reviewed_wrong_removed=sum(
            r["reviewed_ownership"] == "틀림" and bool(r["rejection"]) for r in records
        ),
        reviewed_correct_retained=sum(
            r["reviewed_ownership"] == "맞음" and not r["rejection"] for r in records
        ),
        reviewed_correct_withheld=[
            r["row_id"] for r in records if r["reviewed_ownership"] == "맞음" and r["rejection"]
        ],
        rows=records,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ad", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    worktree = Path(__file__).resolve().parents[1]
    states = {
        f"E2E8/{arm}/{company}": args.ad / f"lab/sprint6/E2E8/states/{arm}/{company}/state.sqlite3"
        for arm in ("control", "candidate")
        for company in ("naver", "kia")
    }
    for rehearsal in ("rb3", "rb4"):
        states.update(
            {
                f"{rehearsal}/{p.parent.name}": p
                for p in (worktree / f".local/{rehearsal}/data/payloads").rglob("state.sqlite3")
            }
        )
    result = dict(
        policy=POLICY,
        policy_sha256=canonical_hash(POLICY),
        paid_calls=0,
        paid_usd="0",
        method=(
            "SQLite mode=ro/query_only; saved literal candidate veto; no new source attestation, "
            "model inference, grade recomputation or revision writes"
        ),
        limitations=[
            "Same-page explicit table/block-group exceptions need the verified runtime graph; "
            "this offline replay uses stored raw blocks only.",
            "Reviewed set is AI draft + AI comparison + domain sample/dispute adjudication; "
            "not independently authored human gold.",
            "relation-10-01 is reviewed correct but cross-page, "
            "and is withheld by the requested strict policy.",
        ],
        reviewed_27=reviewed_replay(args.ad),
        states={name: state_replay(path) for name, path in states.items()},
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            dict(
                reviewed=counts(result["reviewed_27"]["rows"]),
                states={
                    name: {
                        k: v
                        for k, v in item.items()
                        if k
                        in {
                            "candidates_before",
                            "candidates_after",
                            "attribution_rejected",
                            "stages",
                        }
                    }
                    for name, item in result["states"].items()
                },
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
