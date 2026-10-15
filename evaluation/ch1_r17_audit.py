"""Score printed-label recovery against the frozen, manually inspected R17 units.

Gold is evaluation-only and never imported by the production layout/label readers.
Requires the real original-page lineage check and newly executed QT1 cohort replay.
"""

import argparse
import json
from hashlib import sha256
from pathlib import Path

from proofops.domain.provenance import canonical_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output
    receipt_path = out / "lge-recovery-final.json"
    receipt = json.loads(receipt_path.read_text())
    prior = json.loads((args.lab / "quality/QT1/r17-recovery.json").read_text())
    points = [p | dict(region=r["id"]) for r in receipt["regions"] for p in r["observations"]]
    assert len(points) == 22
    assert all(
        p["eligible_for_scoring"] is False and p["binding_status"] == "unknown" for p in points
    )

    def matched(region, value, unit, year, series):
        return [
            p
            for p in points
            if p["region"] == region
            and p["status"] == "verified"
            and {k: f.get("literal") for k, f in p["fields"].items()}
            == dict(value=value, unit=unit, year=year, series=series)
        ]

    judgments = []
    for i, (year, value, percent) in enumerate(
        [
            (2025, "225", "19%"),
            (2026, "290", "24%"),
            (2027, "376", "30%"),
            (2028, "445", "35%"),
            (2029, "565", "43%"),
            (2030, "826", "62%"),
            (2040, "1,450", "90%"),
            (2050, "1,976", "100%"),
        ],
        22,
    ):
        records = matched("re100", value, "GWh", str(year), "재생전력") + matched(
            "re100", percent, "%", str(year), "재생전력 전환율"
        )
        assert len(records) == 2
        judgments.append(
            dict(
                gold_unit_id=f"lge-p21-miss-{i}",
                original_page=21,
                recovered_printed_labels=True,
                observation_ids=[r["id"] for r in records],
                conflict_preserved=year == 2030,
            )
        )
    for suffix, region, value, series in [
        (19, "iso14001", "100%", "ISO 14001 인증 취득 생산사업장"),
        (20, "iso50001", "73%", "ISO 50001 인증 취득 사업장"),
    ]:
        records = matched(region, value, "%", "2024년", series)
        assert len(records) == 1
        judgments.append(
            dict(
                gold_unit_id=f"lge-p27-miss-{suffix}",
                original_page=27,
                recovered_printed_labels=True,
                observation_ids=[r["id"] for r in records],
            )
        )
    records = matched("cumulative", "402", "만 톤", "2022", "폐전자제품 누적 회수량") + matched(
        "cumulative", "448", "만 톤", "2023", "폐전자제품 누적 회수량"
    )
    assert len(records) == 2
    judgments.append(
        dict(
            gold_unit_id="lge-p31-miss-28",
            original_page=31,
            recovered_printed_labels=True,
            observation_ids=[r["id"] for r in records],
        )
    )
    pending = {
        r["gold"]["gold_unit_id"]
        for r in prior["cases"]["lge"]["rows"]
        if r["status"] == "missing" and r["gold"]["kind"] in {"chart", "table"}
    }
    assert {j["gold_unit_id"] for j in judgments} == pending
    lg_path = out / "lg-recovery-final.json"
    lg = json.loads(lg_path.read_text())
    lg_points = [p for r in lg["regions"] for p in r["observations"]]
    assert len(lg_points) == 3 and all(p["status"] == "verified" for p in lg_points)
    recovered = [
        p
        for p in lg_points
        if p["fields"]["value"]["literal"] == "890"
        and p["fields"]["year"]["literal"] == "2025"
        and p["fields"]["unit"]["literal"] == "만 톤"
    ]
    assert len(recovered) == 1
    assert not any(p["fields"]["year"]["literal"] == "2050" for p in lg_points)
    assert all(
        not p["eligible_for_scoring"] and p["binding_status"] == "unknown" for p in lg_points
    )
    judgments.append(
        dict(
            gold_unit_id="lg-p24-miss-11",
            original_page=24,
            recovered_printed_labels=True,
            observation_ids=[recovered[0]["id"]],
        )
    )
    lineage = json.loads((out / "original-lineage.json").read_text())
    assert len(lineage["pages"]) == 3 and all(p["pixel_identical"] for p in lineage["pages"])
    lg_lineage = json.loads((out / "lg-original-lineage.json").read_text())
    assert lg_lineage["pages"][0]["pixel_identical"]
    scored = json.loads((out / "cohort-replay/cohort-results.json").read_text())
    frozen = json.loads((args.lab / "quality/QT1/cohort-results.json").read_text())
    # Re-execution, not copying a metric claim from the earlier report.
    assert canonical_hash(scored) == canonical_hash(frozen)
    dl4 = [v["after"] for v in scored["dl4"].values() if v["after"]]
    matches = sum(v["one_to_one_matches"] for v in dl4)
    denom = sum(v["gold_denominator"] for v in dl4)
    preds = sum(v["predictions"] for v in dl4)
    holdout = scored["holdout"]["after"]
    report = dict(
        method="frozen R17 omissions; explicit original-page visual self-review; labels only",
        receipt_sha256=sha256(receipt_path.read_bytes()).hexdigest(),
        lg_receipt_sha256=sha256(lg_path.read_bytes()).hexdigest(),
        r17_units=judgments,
        recovered_missing_units=12,
        missing_table_chart_labels_before=dict(lg=3, kakao=5, lge=11),
        missing_table_chart_labels_after=dict(lg=2, kakao=5, lge=0),
        raw_measurements=25,
        complete_four_field_proofs=24,
        newly_recovered_measurements=21,
        observed_false_numeric_transcriptions=0,
        original_pages_reviewed=dict(lge=[21, 27, 31], lg=[24]),
        independent_review=False,
        semantic_binding="unknown for every observation",
        new_scored_claims=0,
        actual_pipeline_claim_recall_delta=0,
        source_conflicts=[
            dict(
                original_page=21,
                year=2030,
                body="60%",
                chart="62%",
                status="preserved; not admitted to scoring",
            )
        ],
        dl4=dict(
            gold=denom,
            predictions=preds,
            matches=matches,
            recall=matches / denom,
            precision=matches / preds,
            ch1_delta=0,
        ),
        holdout={k: v for k, v in holdout.items() if isinstance(v, int | float | str)},
        cohort_replay_equal=True,
        limits=[
            "requires reviewed or model-proposed local layout/legend hints",
            "remaining LG/Kakao narrative-table gaps unchanged",
            "no live inference accuracy, end-to-end grading improvement or UI integration claim",
        ],
    )
    (out / "r17-measurement.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {k: report[k] for k in ("recovered_missing_units", "raw_measurements", "dl4")},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
