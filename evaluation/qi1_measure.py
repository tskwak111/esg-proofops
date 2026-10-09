"""Compare QI1 with identical MP1/INT2 source selections, without provider calls."""

import json
from collections import Counter

from evaluation import int2_measure
from evaluation.qi1_live import OUT, ROOT


def measure(company):
    int2_measure.OUT = OUT
    result = int2_measure.measure(company)
    snapshot, checkpoints = int2_measure.checkpoints(OUT / "states" / company)
    extract = checkpoints["local_extract_checkpoint_v2"]
    claims = checkpoints["local_tag_checkpoint_v1"]["claims"]
    assert "page_tag_pipeline" not in extract
    assert snapshot["analysis_profile_policy"]["stage_overlap"] is False
    baseline = next(
        r
        for r in json.loads(
            (
                ROOT / "outputs/agent-results/R108-redesign/lab/integ/INT2/measurements.json"
            ).read_text()
        )
        if r["company"] == company
    )
    mp1 = next(
        r
        for r in json.loads(
            (
                ROOT / "outputs/agent-results/R108-redesign/lab/parse/MP1/measurements.json"
            ).read_text()
        )
        if r["company"] == company
    )

    def all_unknown(rows):
        return sum(
            bool(r["provisional_grade"]["elements"])
            and all(e["state"] == "unknown" for e in r["provisional_grade"]["elements"])
            for r in rows
        )

    _, prior = int2_measure.checkpoints(
        ROOT
        / "outputs/agent-results/R108-redesign/lab/integ/INT2/states"
        / (company if company == "samsung" else "kepco-recovery")
    )
    result.update(
        all_unknown=all_unknown(claims),
        elements_not_entered=sum(not r["provisional_grade"]["elements"] for r in claims),
        int2_all_unknown=all_unknown(prior["local_tag_checkpoint_v1"]["claims"]),
        int2_seconds=baseline["seconds"],
        int2_numeric=sum(baseline["numeric_grades"].values()),
        mp1_numeric=44 if company == "samsung" else 34,
        numeric_recovery_met=sum(result["numeric_grades"].values())
        >= (44 if company == "samsung" else 34),
        hold_reasons=dict(
            Counter(
                reason for r in claims for reason in r["provisional_grade"].get("hold_reasons", [])
            )
        ),
        prompt_sha256s=sorted({run["prompt_sha256"] for r in claims for run in r["tag_runs"]}),
        mp1_cost=mp1.get("report_usd"),
    )
    (OUT / (company + "-measurements.json")).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    return result


if __name__ == "__main__":
    import sys

    result = [measure(company) for company in sys.argv[1:] or ["samsung", "kepco"]]
    if len(result) == 2:
        (OUT / "measurements.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
