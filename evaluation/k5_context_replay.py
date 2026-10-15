"""Offline context replay over frozen I4 and H1 atoms, with unchanged G1/A scoring."""

import argparse
import importlib.util
import json
import socket
from collections import Counter
from hashlib import sha256
from pathlib import Path
from time import monotonic

from proofops.adapters.parsing.parser_artifacts import (
    iter_parser_artifacts,
    parser_artifact_path,
    read_parser_json,
)
from proofops.application.analysis_profile import FINALS_I4_POLICY, FINALS_K5_POLICY
from proofops.application.ingest.graph_fusion import candidates_from_snapshot, fuse_candidates
from proofops.application.ingest.k5_context import sentence_context
from proofops.domain.provenance import canonical_hash

import evaluation
from evaluation.pa9_source_gate import discovery_from_record, fixture


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--root", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    lab = root / "outputs/agent-results/R108-redesign/lab"
    output.mkdir(parents=True, exist_ok=True)
    started, hashes = monotonic(), {}

    def read(path):
        path = parser_artifact_path(path)
        hashes[str(path)] = sha256(path.read_bytes()).hexdigest()
        return read_parser_json(path)

    def write(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    scorer_path = root / ".local/g1-gold/evaluation/dl4_gold.py"
    hashes[str(scorer_path)] = sha256(scorer_path.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location("k5_frozen_g1", scorer_path)
    scorer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scorer)
    gold = read(lab / "fix/G1/DL4-gold.json")["golds"]
    dl4_before, dl4_after, projections = [], [], {}
    for company in ("naver", "kia", "lgchem"):
        pp = read(lab / f"perf/I4/stage-A-v4/{company}-after.json")
        after = json.loads(json.dumps(pp))  # no quote/selection/verification changes
        before_key = Counter((p["page"], p["quote"]) for p in pp)
        assert before_key == Counter((p["page"], p["quote"]) for p in after)
        projections[company] = dict(
            rows=len(pp),
            duplicate_multiplicity_preserved=True,
            focal_loss=0,
            pages=sorted({p["page"] for p in pp}),
        )
        if company != "lgchem":
            dl4_before.extend(dict(p, company=company) for p in pp)
            dl4_after.extend(dict(p, company=company) for p in after)
    before, after = scorer.evaluate(gold, dl4_before), scorer.evaluate(gold, dl4_after)
    assert before == after and before["matches"] == 100 and before["predictions"] == 102
    assert after["precision"] >= 0.9804 - 0.005 and after["recall"] >= before["recall"]
    write(
        "dl4-scores.json",
        dict(
            before=before,
            after=after,
            projections=projections,
            lgchem_absolute_score=(
                "not_run: G1 returned gold does not include LG; 111 focal atoms unchanged"
            ),
            uncovered_gold_pages=sorted(
                set(g["page"] for g in gold) - {p["page"] for p in dl4_after}
            ),
        ),
    )

    # Actual I4 parser identity for B-NAVER (derived physical p2 -> original p88).
    directory = lab / "perf/I4/native-final/stage-B/naver"
    path = next(iter_parser_artifacts(directory, "candidates.json"))
    batches = candidates_from_snapshot(read(path))
    manifest = read(path.parent / "manifest.json")
    graph = fuse_candidates(
        batches,
        tenant_id=batches[0].tenant_id,
        fusion_version=manifest["fusion_version"],
        mixed_parser=True,
    )
    discovery = discovery_from_record(read(directory / "extract-checkpoint.json")["discovery"])
    targets = []
    for index in (1, 2, 21):
        claim = discovery.claims[index]
        context = sentence_context(claim, graph)
        assert context is not None
        targets.append(
            dict(
                case_id=f"B-NAVER-{index:02d}",
                before=claim.quote,
                after=context["text"],
                focal_identity_unchanged=True,
                sentence_context=context,
            )
        )

    evaluation.__path__.append(str(root / ".local/a-holdout/evaluation"))
    from evaluation.a_score import audit_sources
    from evaluation.a_score import scorer as a_scorer

    holdout_scorer = a_scorer()
    hashes[str(root / ".local/a-holdout/evaluation/a_score.py")] = sha256(
        (root / ".local/a-holdout/evaluation/a_score.py").read_bytes()
    ).hexdigest()
    holdout_gold = read(lab / "fix/A/paid-dec26/v1-gold-atoms.json")
    cases = {
        "SK하이닉스": ["SK하이닉스"],
        "현대자동차": ["현대자동차-p22", "현대자동차-p41"],
        "POSCO홀딩스": ["POSCO홀딩스"],
        "삼성전자": ["삼성전자"],
    }
    holdout_before, holdout_after, audit, companies = [], [], [], {}
    for company, states in cases.items():
        pp = read(lab / f"fix/H1/h1-final/{company}/predictions.json")
        new = json.loads(json.dumps(pp))
        for state_name in states:
            state = lab / "fix/A/paid-dec26/states" / state_name
            g, source, _, _, _ = fixture(state)
            hashes[str(state / "state.sqlite3")] = sha256(
                (state / "state.sqlite3").read_bytes()
            ).hexdigest()
            for candidate_path in iter_parser_artifacts(
                state / "parser-prepared", "candidates.json"
            ):
                read(candidate_path)
            disc_path = lab / f"fix/H1/h1-final/{company}/{state_name}/discovery.json"
            claims = discovery_from_record(read(disc_path)).claims
            by_id = {c.claim_id: c for c in claims}
            for p in new:
                if p["id"] in by_id:
                    p["sentence_context"] = sentence_context(by_id[p["id"]], g)
            source_path = Path(read(state / "pilot.json")["source_path"])
            hashes[str(source_path)] = sha256(source).hexdigest()
            audit.extend(audit_sources([p for p in new if p["id"] in by_id], g, source_path))
        stripped = [{k: v for k, v in p.items() if k != "sentence_context"} for p in new]
        assert stripped == pp, "K5_FOCAL_OR_TAG_OR_SOURCE_CHANGE"
        gg = [g for g in holdout_gold if g["company"] == company]
        b, a = holdout_scorer.evaluate(gg, pp), holdout_scorer.evaluate(gg, new)
        assert b == a
        companies[company] = dict(
            before=b,
            after=a,
            focal_loss=0,
            context_count=sum(p.get("sentence_context") is not None for p in new),
        )
        write(f"{company}-predictions.json", new)
        for index in {"SK하이닉스": (2, 23), "POSCO홀딩스": (0, 8, 14)}.get(company, ()):
            context = new[index]["sentence_context"]
            assert context is not None
            targets.append(
                dict(
                    case_id=f"H1-{company}-{index:02d}",
                    before=new[index]["quote"],
                    after=context["text"],
                    focal_identity_unchanged=True,
                    sentence_context=context,
                )
            )
        holdout_before.extend(pp)
        holdout_after.extend(new)
    before, after = (
        holdout_scorer.evaluate(holdout_gold, holdout_before),
        holdout_scorer.evaluate(holdout_gold, holdout_after),
    )
    assert before == after and after["matches"] == 77 and after["predictions"] == 83
    false_verified = sum(a["native_audit_mismatch"] for a in audit)
    assert false_verified == 0
    write(
        "holdout-scores.json",
        dict(
            before=before,
            after=after,
            companies=companies,
            false_verified=false_verified,
            audit_uncheckable=sum(a["uncheckable"] for a in audit),
        ),
    )
    write("source-audit.json", audit)
    write("cases-before-after.json", targets)
    all_contexts = [p["sentence_context"] for p in holdout_after if p.get("sentence_context")] + [
        t["sentence_context"] for t in targets[:3]
    ]
    assert all(c["rule_credit"] is False for c in all_contexts)
    assert all(sha256(Path(p).read_bytes()).hexdigest() == h for p, h in hashes.items())
    summary = dict(
        schema="K5-context-replay-v1",
        policy=FINALS_K5_POLICY,
        policy_sha256=canonical_hash(FINALS_K5_POLICY),
        previous_policy_sha256=canonical_hash(FINALS_I4_POLICY),
        target_cases=len(targets),
        semantic_improvement=(
            "8/8 literal parent-context restored; AI source review, not model accuracy"
        ),
        focal_loss=0,
        false_verified=false_verified,
        new_verified_refs=sum(
            r["verification_state"] == "verified" for c in all_contexts for r in c["source_refs"]
        ),
        model_calls=0,
        paid_usd="0",
        live_tagging="not_run",
        aws="not_run",
        input_hashes=hashes,
        elapsed_seconds=round(monotonic() - started, 3),
        dl4=dict(matches=100, predictions=102, gold=131, precision=100 / 102, recall=100 / 131),
        holdout=dict(matches=77, predictions=83, gold=160, precision=77 / 83, recall=77 / 160),
    )
    write("measurement.json", summary)
    print(
        {
            k: summary[k]
            for k in (
                "target_cases",
                "focal_loss",
                "false_verified",
                "new_verified_refs",
                "elapsed_seconds",
                "dl4",
                "holdout",
            )
        }
    )


if __name__ == "__main__":

    def deny(*args, **kwargs):
        raise AssertionError("K5_REPLAY_NETWORK_FORBIDDEN")

    setattr(socket.socket, "connect", deny)
    setattr(socket.socket, "connect_ex", deny)
    socket.create_connection = deny
    main()
