"""K9 bounded focal pages under one USD .40 task fence; no hosted changes."""

from decimal import Decimal

from proofops.application.analysis_profile import FINALS_K9_POLICY

from evaluation.i5_live import I5Budget
from evaluation.k8_authorization import fresh_grants


class K9Budget(I5Budget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.task, self.limit_usd = "K9-v7fix", Decimal(".4")


def main():
    from evaluation import k8_authorization, k8_live_v3

    original_grants = fresh_grants

    def grants(snapshot: dict) -> dict:
        return original_grants(
            snapshot, approved_by="authorized-local-operator:fix-K9.md-and-R5-six-elements"
        )

    k8_authorization.fresh_grants = grants
    k8_live_v3.K8Budget = K9Budget
    k8_live_v3.FINALS_K8_V3_POLICY = FINALS_K9_POLICY
    return k8_live_v3.main()


if __name__ == "__main__":
    raise SystemExit(main())
