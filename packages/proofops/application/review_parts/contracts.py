"""Stable review errors and honest provenance labels."""


class ReviewRejected(ValueError):
    def __init__(self, code: str, status: int = 422):
        super().__init__(code)
        self.code, self.status = code, status


# Honest provenance labels for the additive AI-delegated route. Reuses the
# rulepack-activation prefix pattern (``ai-delegated-review:<operator>``) so a
# machine-driven revision can never be mistaken for an independent human
# confirmation. Old ``human``/``consensus`` rows stay valid and immutable.
#
# a bounded correction for a safe-harbor category the tagging headers agree
# on but the reviewed source does not support. v1 REMOVES a wrong non-null
# category only; adding or replacing one would assert a regulatory
# classification the reviewed refs do not establish, so it is refused as
# unsupported until a concrete need exists. The policy name states the scope.
CATEGORY_POLICY_V1 = "claim_category_removal_v1"
AI_DELEGATED_ORIGIN = "ai_delegated"
AI_DELEGATED_REVIEW_STATUS = "ai_delegated_confirmed"
AI_DELEGATED_REVIEWER_PREFIX = "ai-delegated-review:"
AI_DELEGATED_REVIEW_ORIGIN = "ai_project_interpretation"
HUMAN_ORIGIN = "human"
HUMAN_REVIEW_STATUS = "human_confirmed"
