"""Fresh KIA 238.6 classification/elements only, on the same two-page USD .30 event."""

from proofops.application.analysis_profile import FINALS_K4_POLICY
from proofops_worker.live_tagging import LiveTaggingRuntime

from evaluation.i1_live import main

TARGET = "국내 천tCO2eq 266.0 244.6 238.6"

if __name__ == "__main__":
    original = LiveTaggingRuntime.preliminary

    def targeted(self, claim, graph):
        if " ".join(claim.quote.split()) != TARGET:
            return None  # Deliberately not measured; never a negative element vote.
        return original(self, claim, graph)

    setattr(LiveTaggingRuntime, "preliminary", targeted)
    result = main(
        claim_pages=dict(kia=[106]),
        workers=1,
        budget="0.3",
        event_id="K4-USD0.3",
        integration_policy=FINALS_K4_POLICY,
    )
    raise SystemExit(0 if result["results"]["kia"]["status"] == "completed" else 1)
