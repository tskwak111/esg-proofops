"""Authorized NAVER p88/Kia p106 canary; shared USD .30 cap, workers16."""

from evaluation.i1_live import main

if __name__ == "__main__":
    result = main(
        claim_pages=dict(naver=[88], kia=[106]),
        workers=16,
        budget="0.3",
        event_id="I3-USD0.3",
    )
    raise SystemExit(
        0 if all(r["status"] == "completed" for r in result["results"].values()) else 1
    )
