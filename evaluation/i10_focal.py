"""Five focal pages and Kakao R6 pages under the shared I10 USD0.80 fence."""

import sys
from decimal import Decimal
from pathlib import Path

from proofops.adapters.local.openai import OpenAIProbe
from proofops.application.analysis_profile import FINALS_I10_POLICY

from evaluation import k8_authorization, k8_live_v3
from evaluation.i1_live import main as live_main
from evaluation.i5_live import I5Budget


class I10Budget(I5Budget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.task, self.limit_usd = "I10-integration", Decimal("0.8")


def main():
    original_grants = k8_authorization.fresh_grants

    def grants(snapshot):
        return original_grants(snapshot, approved_by="authorized-local-operator:int-I10.md")

    k8_authorization.fresh_grants = grants
    if sys.argv[1] != "kakao":
        if sys.argv[1] != "B":
            raise ValueError("I10_LEGACY_PRODUCT_HELPER_UNSUPPORTED_USE_FROZEN_FOCAL_PROBE")
        k8_live_v3.K8Budget = I10Budget
        k8_live_v3.FINALS_K8_V3_POLICY = FINALS_I10_POLICY
        return k8_live_v3.main()
    sys.argv.pop(1)
    root = Path(sys.argv[sys.argv.index("--root") + 1])
    out = Path(sys.argv[sys.argv.index("--output") + 1])
    lab = root / "outputs/agent-results/R108-redesign/lab"
    original = OpenAIProbe.complete

    def guarded(probe, *args, **kwargs):
        fence = I10Budget(
            lab / "sprint3/E2E/r108-spend.json",
            {"openai": probe.ledger.resolve()},
            out.parent / "paid-calls.jsonl",
        )
        return fence.guarded(original, "openai", lambda *args: Decimal(".02"))(
            probe, *args, **kwargs
        )

    OpenAIProbe.complete = guarded
    result = live_main(
        claim_pages={"kakao": [3, 5, 6, 7, 8, 9]},
        source_states={"kakao": lab / "perf/S4/live-inputs/kakao"},
        workers=16,
        requests_per_second=8,
        budget="0.8",
        event_id="I10-kakao",
        integration_policy=FINALS_I10_POLICY,
        extraction_batch_calls=100,
        local_grant_factory=grants,
    )
    return 0 if result["results"]["kakao"]["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
