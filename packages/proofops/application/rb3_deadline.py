"""Opt-in admission cutoff; completed work still uses the normal sealed publication.

The parent supplies its monotonic hard deadline. These reserves leave room for
source replay, in-flight work and publication; they never extend the hard cap.
No saved result or environment flag can enable this policy on a historical run.
"""

import math
import os
import time
from threading import Lock

POLICY = dict(
    profile="rb3_deadline_v1",
    hard_cap_seconds=1800,
    extract_reserve_seconds=1000,
    tag_reserve_seconds=600,
    unprocessed="TIME_BUDGET",
    inflight="finish-with-normal-verification",
    publication="unchanged-source-tenant-fence-and-anonymous-fd",
)
POLICY_V2 = POLICY | dict(
    profile="rb3_deadline_v2",
    hard_cap_seconds=2700,
    extract_reserve_seconds=1200,
    tag_reserve_seconds=300,
)
DEADLINE_ENV = "PROOFOPS_RB3_HARD_DEADLINE"


class Deadline:
    def __init__(self, hard_deadline, *, policy=POLICY, clock=time.monotonic):
        configured(dict(rb3_deadline=policy))
        if not math.isfinite(hard_deadline) or hard_deadline < 0:
            raise ValueError("RB3_DEADLINE_INVALID")
        self.clock = clock
        self.policy = dict(policy)
        self.hard_deadline = min(hard_deadline, clock() + self.policy["hard_cap_seconds"])
        self.stopped = set()
        self.lock = Lock()

    def admit(self, stage):
        reserve = self.policy[stage + "_reserve_seconds"]
        with self.lock:
            if self.clock() >= self.hard_deadline - reserve:
                self.stopped.add(stage)
            return stage not in self.stopped

    def summary(self):
        with self.lock:
            return dict(policy=dict(self.policy), stopped_stages=sorted(self.stopped))


def configured(policy):
    if "rb3_deadline" not in policy:
        return False
    if policy["rb3_deadline"] not in (POLICY, POLICY_V2):
        raise ValueError("RB3_DEADLINE_POLICY_MISMATCH")
    return True


def from_parent(policy):
    if not configured(policy):
        return None
    try:
        return Deadline(float(os.environ[DEADLINE_ENV]), policy=policy["rb3_deadline"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("RB3_DEADLINE_REQUIRED") from None


def admit(runner, snapshot, stage):
    if not configured(snapshot.get("analysis_profile_policy", {})):
        return True
    budget = getattr(runner, "rb3_deadline", None)
    if not isinstance(budget, Deadline):
        raise ValueError("RB3_DEADLINE_REQUIRED")
    if budget.policy != snapshot["analysis_profile_policy"]["rb3_deadline"]:
        raise ValueError("RB3_DEADLINE_POLICY_MISMATCH")
    return budget.admit(stage)


def held_claim(claim):
    from proofops.application.tagging.unattended import empty_provisional, source_status

    return dict(
        claim_id=claim.claim_id,
        status="needs_review",
        stage="preliminary",
        reason="TIME_BUDGET",
        reason_display="처리 시간 한도로 미분석 · 판정 보류",
        source_status=source_status(claim),
        tag_runs=[],
        decision=None,
        review_inputs=None,
        provisional_grade=empty_provisional("TIME_BUDGET")
        | dict(
            display_type="hold",
            display="처리 시간 한도 · 판정 보류",
            hold_reasons=["TIME_BUDGET"],
            evidence_note="처리를 완료하지 못했으며 원문의 근거 부재를 뜻하지 않습니다.",
        ),
    )
