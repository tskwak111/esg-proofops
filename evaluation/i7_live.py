"""I7 five focal pages and original LG/Kakao scopes under one USD1 task fence."""

import sys
from decimal import Decimal

from proofops.application.analysis_profile import FINALS_I7_POLICY

from evaluation.i5_live import I5Budget
from evaluation.k8_authorization import fresh_grants


class I7Budget(I5Budget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.task, self.limit_usd = "I7-integration", Decimal("1.0")


def grants(snapshot):
    return fresh_grants(snapshot, approved_by="authorized-local-operator:int-I7.md")


def main():
    case = sys.argv[1]
    if case in {"lgchem", "kakao"}:
        from evaluation.f1_live import run

        return run(
            integration_policy=FINALS_I7_POLICY,
            task="I7-integration",
            limit="1.0",
            local_grant_factory=grants,
        )
    from evaluation import k8_live_v3

    k8_live_v3.K8Budget = I7Budget
    k8_live_v3.FINALS_K8_V3_POLICY = FINALS_I7_POLICY
    k8_live_v3.fresh_grants = grants
    # The K8 module imports the grant locally; use the authorized I7 identity.
    from evaluation import k8_authorization

    original_grants = k8_authorization.fresh_grants

    def i7_grants(snapshot: dict) -> dict:
        return original_grants(snapshot, approved_by="authorized-local-operator:int-I7.md")

    k8_authorization.fresh_grants = i7_grants
    return k8_live_v3.main()


if __name__ == "__main__":
    raise SystemExit(main())
