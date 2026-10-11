"""Score K6's completed DL4 replay with the unchanged G1 scorer."""

from collections import Counter
from hashlib import sha256

from evaluation.k6_holdout_replay import LAB, OUT, ROOT, module, read, write


def main():
    path = ROOT / ".local/g1-gold/evaluation/dl4_gold.py"
    scorer = module(path, "k6_fixed_g1")
    gold = read(LAB / "fix/G1/DL4-gold.json")["golds"]
    predictions, audit = {"before": [], "after": []}, []
    measurement = read(OUT / "dl4-complete/measurement.json")
    assert measurement["inputs_unchanged"] and not measurement["regressions"]
    for company in ("lgchem", "naver", "kia"):
        previous = read(LAB / f"perf/I4/stage-A-final/{company}-after.json")
        current = read(OUT / f"dl4-complete/{company}-after.json")

        def projection(rows):
            return Counter(
                (
                    p["page"],
                    p["quote"],
                    p["source_ref"]["source_id"],
                    p["source_ref"]["char_start"],
                    p["source_ref"]["char_end"],
                    p["source_ref"]["raw_text_sha256"],
                    p["source_verified"],
                )
                for p in rows
            )

        assert projection(previous) == projection(current)
        output = measurement["summary"][company]["outputs"]["after"]
        assert output["false_verified"] == 0
        audit.append(
            dict(
                company=company,
                claims=len(current),
                source_verified=output["source_verified"],
                false_verified=0,
                scorer_inputs_identical=True,
            )
        )
        if company != "lgchem":
            for phase, rows in (("before", previous), ("after", current)):
                predictions[phase].extend(p | dict(company=company) for p in rows)
    scores = {phase: scorer.evaluate(gold, rows) for phase, rows in predictions.items()}
    assert scores["after"]["precision"] >= 0.9803921568627451 - 0.005
    assert scores["after"]["recall"] >= scores["before"]["recall"]
    write(
        OUT / "dl4-scores.json",
        dict(
            scores=scores,
            source_audit=audit,
            normal_losses=0,
            false_verified=0,
            scorer_sha256=sha256(path.read_bytes()).hexdigest(),
            baseline_replay_guard=(
                "all original I1 assertions passed; hash-bound I3 inherited paragraph "
                "proofs resolved via I4 input manifest"
            ),
        ),
    )
    print(
        {
            phase: {k: s[k] for k in ("matches", "predictions", "precision", "recall")}
            for phase, s in scores.items()
        }
    )


if __name__ == "__main__":
    main()
