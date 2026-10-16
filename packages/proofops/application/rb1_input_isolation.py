"""Opt-in candidate-local grid failures; no relaxed validation or absence credit."""

from proofops.application.claims import ExtractionOutputError
from proofops.application.input_failures import TABLE_ERRORS
from proofops.domain.provenance import canonical_hash

POLICY = dict(
    profile="rb1_input_isolation_v1",
    extraction="candidate-routing-context-prefetch-and-dispatch; invalid-source-unknown",
    tagging="claim-local-input-validation-and-projection; invalid-claim-held",
    diagnostics="allowlisted-code-source-id-page-and-offsets; no-source-text",
    integrity="identity-policy-authorization-accounting-and-replay-errors-remain-fatal",
)


class InputIsolation:
    """Run-local state shared by routing, prefetch and the extraction adapter."""

    def __init__(self, policy):
        value = policy.get("rb1_input_isolation")
        pin = policy.get("rb1_input_isolation_sha256")
        if (value is not None or pin is not None) and (
            value != POLICY or pin != canonical_hash(POLICY)
        ):
            raise ValueError("RB1_INPUT_POLICY_MISMATCH")
        self.active = value == POLICY
        self.failures: dict[str, str] = {}

    def capture(self, source_id, error):
        if not self.active or str(error) not in TABLE_ERRORS:
            return False
        self.failures[source_id] = "TABLE_RB1_" + str(error)
        return True

    def check(self, source_id):
        code = self.failures.get(source_id)
        if code:
            raise ExtractionOutputError(code, failure_code=code)


def tag_input_code(error):
    """Only identified content/structure errors, never arbitrary exception text."""
    if isinstance(error, KeyError | TypeError):
        return "TAG_INPUT_INVALID"
    code = str(error)
    return (
        code
        if isinstance(error, ValueError)
        and code
        in TABLE_ERRORS
        | {"SENTENCE_CONTEXT_TOO_LARGE", "TAGGING_INPUT_COUNT_INVALID", "TAG_INPUT_INVALID"}
        else None
    )


def held_claim(claim, error):
    from proofops.application.tagging.unattended import empty_provisional, source_status

    return dict(
        claim_id=claim.claim_id,
        status="needs_review",
        stage="input_validation",
        reason="TAG_INPUT_INVALID",
        reason_display="입력 검증 실패 — 해당 주장 보류",
        source_status=source_status(claim),
        tag_runs=[],
        decision=None,
        review_inputs=None,
        provisional_grade=empty_provisional("TAG_INPUT_INVALID")
        | dict(display="판정 보류", display_type="hold", hold_reasons=["입력 검증 실패"]),
        rb1_input_hold=dict(
            code="TAG_INPUT_INVALID",
            cause=tag_input_code(error),
            state="unknown",
            locations=[
                dict(
                    source_id=r.source_id,
                    physical_page=r.page_num,
                    char_start=r.char_start,
                    char_end=r.char_end,
                )
                for r in claim.source_refs
            ],
        ),
    )
