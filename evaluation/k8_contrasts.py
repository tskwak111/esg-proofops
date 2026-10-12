"""Fictional M1/M4 contrast probes; no production claims or grading authority."""

import argparse
import json
from decimal import Decimal
from uuid import uuid4

from proofops.adapters.local.openai import OpenAIProbe
from proofops.application.tagging.k7_wire import MANAGEMENT_GUIDANCE, MANAGEMENT_GUIDANCE_V2
from proofops_api.hosted_analysis import read_key

from evaluation.k8_live import LAB, ROOT, K8Budget


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("v1", "v2"), default="v1")
    args = parser.parse_args()
    out = LAB / "fix/K8"
    result_path = out / ("contrasts.json" if args.phase == "v1" else "contrasts-v2.json")
    if result_path.exists():
        raise ValueError("K8_FRESH_CONTRAST_OUTPUT_REQUIRED")
    guidance = MANAGEMENT_GUIDANCE if args.phase == "v1" else MANAGEMENT_GUIDANCE_V2
    ledger = out / (
        "contrasts-ledger.sqlite3" if args.phase == "v1" else "contrasts-v2-ledger.sqlite3"
    )
    probe = OpenAIProbe(read_key(str(ROOT / ".env.openai.local"), "OPENAI_API_KEY"), ledger)
    fence = K8Budget(
        LAB / "sprint3/E2E/r108-spend.json",
        {"openai": ledger.resolve()},
        out / "native/paid-calls.jsonl",
    )
    cases = [
        dict(
            id="operation",
            element_id="M1",
            quote="가상기업 이사회는 환경투자 안건을 검토·승인합니다.",
            expected="present",
        ),
        dict(
            id="intent",
            element_id="M1",
            quote="가상기업은 도입을 검토할 예정입니다.",
            expected="unknown",
        ),
        dict(
            id="formation",
            element_id="M4",
            quote="가상기업은 2023년 2월 CCS 사업화 추진반을 구성하여 사업을 추진합니다.",
            expected="present",
        ),
        dict(
            id="plan",
            element_id="M4",
            quote="가상기업은 CCS를 추진할 계획입니다.",
            expected="unknown",
        ),
    ]
    user = json.dumps(
        dict(cases=[{k: v for k, v in c.items() if k != "expected"} for c in cases]),
        ensure_ascii=False,
    )
    system = (
        "Tag each fictional case independently. No grades. Use only that case quote as evidence; "
        'no borrowing between cases. Return JSON {"cases":[{"id":...,"state":"present" or '
        '"unknown","quote":literal supporting substring or null}]}. Intent without actual '
        "operation/implementation remains unknown. Examples are fictional, never real evidence."
        + guidance
    )
    records = []
    invoke = fence.guarded(OpenAIProbe.complete, "openai", lambda *a: Decimal(".02"))
    for replica in (1, 2, 3):
        result = invoke(
            probe, system, user, request_id=str(uuid4()), max_tokens=512, json_mode=True
        )
        parsed = json.loads(result["content"])
        rows = {r["id"]: r for r in parsed["cases"]}
        passed = all(
            rows[c["id"]]["state"] == c["expected"]
            and (
                (rows[c["id"]]["quote"] and rows[c["id"]]["quote"] in c["quote"])
                if c["expected"] == "present"
                else rows[c["id"]]["quote"] is None
            )
            for c in cases
        )
        records.append(dict(replica=replica, passed=passed, response=result))
    result_path.write_text(
        json.dumps(
            dict(
                synthetic=True,
                rule_credit=False,
                cases=cases,
                records=records,
                passed=all(r["passed"] for r in records),
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print("contrasts", [r["passed"] for r in records])


if __name__ == "__main__":
    main()
