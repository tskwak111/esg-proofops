"""Explicit K4 two-page canary; retained parser, shared USD .30 upper bound."""

from proofops.application.analysis_profile import FINALS_K4_POLICY

from evaluation.i1_live import main

if __name__ == "__main__":
    result = main(
        claim_pages=dict(naver=[88], kia=[106]),
        workers=8,
        budget="0.3",
        event_id="K4-USD0.3",
        integration_policy=FINALS_K4_POLICY,
    )
    raise SystemExit(
        0 if all(r["status"] == "completed" for r in result["results"].values()) else 1
    )
