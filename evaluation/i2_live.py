"""Authorized two-page I2 model canary, one run at a time, workers16, USD0.30 total."""

from evaluation.i1_live import main

if __name__ == "__main__":
    result = main(
        claim_pages=dict(naver=[88], kia=[26]),
        workers=16,
        budget="0.3",
        event_id="I2-USD0.3",
    )
    raise SystemExit(
        0 if all(r["status"] == "completed" for r in result["results"].values()) else 1
    )
