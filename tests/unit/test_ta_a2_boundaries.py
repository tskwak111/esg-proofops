"""WP-A2 baseline: real source guards, rules and SQLite; synthetic model receipts.

Golden SHA-256/length pairs pin the complete canonical tag/decision bytes before
SQLite adds its wall-clock timestamp. Prior stored revision bytes are compared
verbatim, including timestamps. No clock or price guard is patched.
"""

import copy
import hashlib
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from uuid import UUID

import pytest
from proofops.adapters.local.job_store import LocalSQLiteJobStore
from proofops.adapters.local.review_store import LocalSQLiteReviewStore
from proofops.application.reviews import ReviewInputs, ReviewRejected, ReviewService
from proofops.domain.rulepacks import canonical_json

from tests.acceptance.test_citations import RUN, TENANT
from tests.acceptance.test_reviews import workspace
from tests.integration.test_ai_delegated_review import _actor
from tests.integration.test_applicability_review import applicability, management_workspace
from tests.integration.test_c2_receipt_lifecycle import inputs_for
from tests.integration.test_category_review import category_review, category_workspace
from tests.integration.test_safe_harbor_review import checklist_review, safe_harbor_workspace

# Captured from 09ebf426 before moving the implementation. Each entry includes
# all tag/decision fields and the rule engine's own semantic decision hash.
GOLDENS = {
    "human": [
        (
            7366,
            "13bf7eb950791ca166d27cbbb20857fb630ab272b0a9e1d7e4cd25a3f04926a6",
            "fc43b065ade8e2553929f9d5df30eadbb82a4876e618ae3edd2516cd99f4cd94",
        )
    ],
    "ai": [
        (
            7527,
            "d6783c3a775b949b205865daa240d4c35491e7fb87d4a901cec7fd57a6d86018",
            "fc43b065ade8e2553929f9d5df30eadbb82a4876e618ae3edd2516cd99f4cd94",
        )
    ],
    "applicability": [
        (
            15157,
            "9bae8d71d2fcb7616d36466049604f3f84c8e8e225e63c07a2d0d51f4a7306b6",
            "fa8528f235d9fb7314ef0cc0d228e41db854bf5340fb318197ac4f306e5e6dbf",
        ),
        (
            15173,
            "19e1faf75ee8867184473f83d8bd97d411deadeba4f31b7abccd02159738ce45",
            "672746b53720643698aadc4a5373cdc6027ec9d0e2ffea4f3c8196437891f42d",
        ),
        (
            15173,
            "1f8ca5d5d02864bb57dc7e5a59c7f5990f2f7a1e97f9e34d8d51b1a0fb67b887",
            "cf35a549a00c71dc84769e976d409b0f61339ff6ffac56f5bdec2c2bbe3afd43",
        ),
    ],
    "safe_harbor": [
        (
            12887,
            "718f0ea5199a87dffd59771b2a84fb2d4febf9f001a029edc18a418e27c883f6",
            "c47be58aee466841a8437b8db8c6a1f4b524ce1f21db321c86661302030ae3bb",
        ),
        (
            12903,
            "a48678158ea4e1f3fe20e9bb214d4e65a4c1db0b2115af5f97043e71e3c4bb6e",
            "e32692ffd0a6bbd93bc83dbd42cf2efc006766797cfb8dcf8b2d38d9c819b905",
        ),
        (
            12903,
            "e99f920a865356753272267332ce5e49e52fced2f034e8e2361e40bb52775176",
            "65a8de60c1e2cd7332108b165cbff9ec048b107ea5476928aff8b7ff71b5469b",
        ),
    ],
    "category": [
        (
            11740,
            "488edecf4bc40a44f63b1e23f6475e93a1bb1c8d8565e4a2abaa745fd576d37d",
            "95b247fa0647bf7faa6999581e9111b480587a1da2c3a37682b419fd9a479bb9",
        ),
        (
            11756,
            "cc9771c29a96c0eb4037ae1397967d709a70cdd825ec18224eef5cf3ed942528",
            "383d6c8ca6316434fe48bd40ff2cd881bc87f9ca3798aaafee262db9b8cbd076",
        ),
        (
            11756,
            "17eea0e0261fa04917ee77213c95e5911bccbca544f1b673319d828bd15d4bda",
            "fc9b893bb2ff589e12e94e0672ea011f1f67f8288473764877e5fd76c31055b1",
        ),
    ],
}


def revision_bytes(store):
    with sqlite3.connect(store.jobs.path) as db:
        return {
            (kind, key): bytes(value) if isinstance(value, bytes) else value.encode()
            for kind, key, value in db.execute(
                "SELECT kind, record_id, value FROM job_records "
                "WHERE kind IN ('tag_revision', 'decision_revision', 'review_revision')"
            )
        }


def capture_builder(store, monkeypatch):
    original_resolve = store.resolve
    built = []

    def resolve(actor, review_id, body, expected, key, build, *, reopen=False):
        def capture(*args):
            tag, decision = build(*args)
            payload = canonical_json(dict(tag=tag, decision=decision)).encode("ascii")
            built.append((len(payload), hashlib.sha256(payload).hexdigest(), decision["decision"]))
            return tag, decision

        return original_resolve(actor, review_id, body, expected, key, capture, reopen=reopen)

    monkeypatch.setattr(store, "resolve", resolve)
    return built


@pytest.mark.parametrize("case", ["human", "ai", "applicability", "safe_harbor", "category"])
def test_revision_bytes_semantic_hash_retry_and_ancestry(tmp_path, monkeypatch, case):
    options = {}
    if case == "applicability":
        ws = management_workspace(tmp_path, monkeypatch)
        options["applicability_review"] = applicability(ws)
    elif case == "safe_harbor":
        # The derived fixture pack normally allocates a random identity.
        monkeypatch.setattr("scripts.review_rulepack.uuid4", lambda: UUID(int=20261023))
        ws = safe_harbor_workspace(tmp_path, monkeypatch)
        options["safe_harbor_review"] = checklist_review(ws, ("present", "absent"))
    elif case == "category":
        ws = category_workspace(tmp_path, monkeypatch)
        options["category_review"] = category_review(ws)
    else:
        ws = workspace(tmp_path)
    _, service, inputs, review, body, *_ = ws
    before = revision_bytes(service.store)
    built = capture_builder(service.store, monkeypatch)
    resolve = service.resolve_review if case == "human" else service.resolve_ai_delegated_review
    if case != "human":
        options.update(delegated_reviewer="review-operator", delegation_authority="WP-A2 fixture")
    args = (_actor(), review["review_id"], body, '"1"', "a2-byte-baseline-0001")
    response = resolve(*args, **options)
    after = revision_bytes(service.store)
    assert all(after[key] == value for key, value in before.items())
    assert len(after) == len(before) + 3
    assert resolve(*args, **options) == response
    assert revision_bytes(service.store) == after
    assert len(built) == 1  # retries replay stored bytes without a new approval
    history = service.store.history(TENANT, RUN, review["claim_id"])
    first_tag = history["tags"][-1]
    assert first_tag["origin"] == ("human" if case == "human" else "ai_delegated")
    assert ("delegated_reviewer" in first_tag) == (case != "human")
    assert canonical_json(inputs.snapshot()) == canonical_json(history["tags"][0]["inputs"])

    if case in ("applicability", "safe_harbor", "category"):
        receipt_name = case + "_review"
        changed = copy.deepcopy(options)
        changed[receipt_name]["source_authority"] += " changed"
        with pytest.raises(ReviewRejected) as conflict:
            resolve(*args, **changed)
        assert (conflict.value.status, conflict.value.code) == (409, "IDEMPOTENCY_CONFLICT")
        assert revision_bytes(service.store) == after
        assert len(built) == 1
        for revision in (2, 3):
            prior = revision_bytes(service.store)
            service.resolve_review(
                _actor(),
                review["review_id"],
                body | {"base_tag_revision": revision},
                f'"{revision}"',
                f"a2-carry-baseline-{revision:04}",
                reopen=True,
            )
            current = revision_bytes(service.store)
            assert all(current[key] == value for key, value in prior.items())
            carried = service.store.history(TENANT, RUN, review["claim_id"])["tags"][-1]
            assert carried["origin"] == "human"
            assert "delegated_reviewer" not in carried
            assert carried[receipt_name]["request"] == first_tag[receipt_name]["request"]
            assert carried[receipt_name]["carried_from"] == {
                key: first_tag[key]
                for key in ("origin", "reviewer_sub", "review_origin", "delegated_reviewer")
            }
    observed = [(size, digest, decision["semantic_hash"]) for size, digest, decision in built]
    assert observed == GOLDENS[case], (case, observed)


@pytest.mark.parametrize(
    "fault,status,code",
    [
        ("forbidden", 403, "FORBIDDEN"),
        ("if_match", 400, "IF_MATCH_REQUIRED"),
        ("key", 400, "IDEMPOTENCY_KEY_INVALID"),
        ("extra_body", 422, "VALIDATION_ERROR"),
        ("source", 422, "SOURCE_REJECTED"),
        ("stale", 412, "STALE_REVIEW_REVISION"),
        ("missing_input", 409, "REVIEW_INPUT_UNAVAILABLE"),
        ("changed_input", 409, "REVIEW_INPUT_MISMATCH"),
    ],
)
def test_error_codes_and_no_revision_writes(tmp_path, monkeypatch, fault, status, code):
    _, service, inputs, review, body, *_ = workspace(tmp_path)
    before = revision_bytes(service.store)
    actor, match, key = _actor(), '"1"', "a2-error-baseline-0001"
    if fault == "forbidden":
        actor = None
    elif fault == "if_match":
        match = "1"
    elif fault == "key":
        key = "short"
    elif fault == "extra_body":
        body = body | {"origin": "human"}
    elif fault == "source":
        body = copy.deepcopy(body)
        body["elements"][0]["evidence_refs"][0]["quote"] = "999%"
    elif fault == "stale":
        match = '"2"'
    elif fault == "missing_input":

        def missing(*args):
            raise KeyError("unavailable")

        service.load_inputs = missing
    elif fault == "changed_input":
        original_snapshot = ReviewInputs.snapshot
        monkeypatch.setattr(
            ReviewInputs, "snapshot", lambda self: original_snapshot(self) | {"run_id": "changed"}
        )
    with pytest.raises(ReviewRejected) as rejected:
        service.resolve_review(actor, review["review_id"], body, match, key)
    assert (rejected.value.status, rejected.value.code) == (status, code)
    assert revision_bytes(service.store) == before


def test_input_loading_outside_writer_and_validation_inside_transaction(tmp_path, monkeypatch):
    _, service, inputs, review, body, *_ = workspace(tmp_path)
    transaction = service.store.jobs._transaction
    validate = ReviewInputs.validate
    active = []
    events = []

    @contextmanager
    def tracked_transaction(**kwargs):
        with transaction(**kwargs) as db:
            active.append(db)
            try:
                yield db
            finally:
                active.pop()

    def load(*args):
        assert not active
        events.append("load")
        return inputs

    def validate_in_writer(self):
        assert active and active[-1].in_transaction
        events.append("validate")
        return validate(self)

    monkeypatch.setattr(service.store.jobs, "_transaction", tracked_transaction)
    monkeypatch.setattr(ReviewInputs, "validate", validate_in_writer)
    service.load_inputs = load
    service.resolve_review(_actor(), review["review_id"], body, '"1"', "a2-transaction-0001")
    assert events == ["load", "validate"]


def test_c2_publication_rejection_preserves_revision_bytes(tmp_path):
    inputs = inputs_for(tmp_path)
    claim = inputs.context.claim
    jobs = LocalSQLiteJobStore(tmp_path / "state.sqlite")
    jobs.create_run(claim.tenant_id, inputs.run_id, claim.document_version_id)
    service = ReviewService(LocalSQLiteReviewStore(jobs), load_inputs=lambda *args: inputs)
    review = service.publish(inputs)
    before = revision_bytes(service.store)
    body = dict(
        base_tag_revision=1,
        track="management",
        reason="원문 태깅 검토",
        elements=[asdict(e) for e in inputs.consensus.candidate_elements],
    )
    with pytest.raises(ReviewRejected) as rejected:
        service.resolve_review(_actor(), review["review_id"], body, '"1"', "a2-c2-refusal-0001")
    assert (rejected.value.status, rejected.value.code) == (409, "C2_PUBLICATION_DISABLED")
    assert revision_bytes(service.store) == before
