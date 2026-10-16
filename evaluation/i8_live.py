"""I8 focal pages and original LG/Kakao scopes share one USD .80 task fence."""

import sys
from decimal import Decimal

from proofops.application.analysis_profile import FINALS_I8_POLICY

from evaluation.i5_live import I5Budget
from evaluation.k8_authorization import fresh_grants


class I8Budget(I5Budget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.task, self.limit_usd = "I8-integration", Decimal(".8")


def grants(snapshot):
    return fresh_grants(snapshot, approved_by="authorized-local-operator:int-I8.md")


def main():
    if sys.argv[1] in {"lgchem", "kakao"}:
        from evaluation.f1_live import run

        return run(
            integration_policy=FINALS_I8_POLICY,
            task="I8-integration",
            limit=".8",
            local_grant_factory=grants,
        )
    from evaluation import k8_authorization, k8_live_v3

    k8_authorization.fresh_grants = grants
    k8_live_v3.K8Budget = I8Budget
    k8_live_v3.FINALS_K8_V3_POLICY = FINALS_I8_POLICY
    return k8_live_v3.main()


if __name__ == "__main__":
    raise SystemExit(main())
