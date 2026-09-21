#!/usr/bin/env python3
"""Local trusted CLI for AI-delegated tag review (R09).

This is the ONLY path that records ``origin=ai_delegated`` /
``review_status=ai_delegated_confirmed``. It never exposes an HTTP endpoint
and never runs unattended: every write requires an explicit ``--apply`` flag
plus a non-blank ``--delegated-reviewer``/``--delegation-authority``.

What it does, in order:
1. Reads the explicit correction JSON (``base_tag_revision``/``track``/
   ``elements``/``reason`` -- the same 4 keys the human HTTP route accepts;
   any extra key such as ``origin`` is rejected) and the target review row
   (read-only) from the local state DB.
2. Dry run (default): prints review/claim/run ids, expected ``If-Match``
   revision, element count and the honest labels that WOULD be recorded,
   without writing anything.
3. With ``--apply``: calls the trusted backend operation
   ``ReviewService.resolve_ai_delegated_review`` with ``delegated_reviewer``
   and ``delegation_authority`` supplied as constructor arguments (never
   parsed from the correction JSON), reusing the exact same
   source/binding/If-Match/engine guards as the human route.

``--safe-harbor-review-json`` is an opt-in input for runs already pinned to the
R07b checklist policy. It accepts only the configured category items and exact
verified refs from the immutable evidence packet; it does not enable the policy
or change old runs.

Use ``--re-review --apply`` to append a revision to a resolved review. The
correction must name the current tag revision; prior records remain immutable.

Provenance honesty: the new tag revision records
``reviewer_sub="ai-delegated-review:<operator>"``,
``origin="ai_delegated"`` and ``review_status="ai_delegated_confirmed"``,
plus ``review_origin="ai_project_interpretation"`` and the verbatim
``delegation_authority``. It is labelled "AI 검토(위임·사람 아님)" in the
web UI and is NOT accepted as a human gold approval (comparisons still
require ``human_confirmed``). No independent-human or gold claim is made.

Rollback: stop calling this tool; old ``human``/``consensus`` rows are
immutable and remain valid, and no DB schema change is involved.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--state-db", default=str(ROOT / ".local" / "state.sqlite3"))
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--review-id", required=True)
    parser.add_argument(
        "--correction-json",
        required=True,
        help="Path to explicit correction JSON (base_tag_revision/track/elements/reason only).",
    )
    parser.add_argument(
        "--applicability-review-json",
        help="Explicit single-claim trigger review JSON; complete replayed claim refs required.",
    )
    parser.add_argument(
        "--safe-harbor-review-json",
        help="Explicit category checklist facts; the run must use the R07b opt-in pack.",
    )
    parser.add_argument(
        "--delegated-reviewer",
        required=True,
        help="Trusted local operator id, e.g. coordinator@orca.local.",
    )
    parser.add_argument(
        "--delegation-authority",
        default="user delegation 2026-09-20",
        help="Recorded verbatim in the tag row; does not itself grant authorization.",
    )
    parser.add_argument("--actor-sub", default=None)
    parser.add_argument(
        "--if-match", default=None, help='e.g. "1"; default reads current revision.'
    )
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument(
        "--re-review", action="store_true", help="Explicitly re-review a resolved item."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform the write. Without this flag, only inspect (dry run).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        UUID(args.tenant_id)
        UUID(args.review_id)
    except ValueError:
        print(json.dumps({"ok": False, "error": "tenant-id and review-id must be UUIDs"}))
        return 1
    try:
        body = json.loads(Path(args.correction_json).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(json.dumps({"ok": False, "error": "correction JSON unreadable"}))
        return 1
    if not isinstance(body, dict) or set(body) != {
        "base_tag_revision",
        "track",
        "elements",
        "reason",
    }:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "correction JSON must carry exactly "
                    "base_tag_revision/track/elements/reason",
                }
            )
        )
        return 1

    applicability_review = None
    if args.applicability_review_json:
        try:
            applicability_review = json.loads(
                Path(args.applicability_review_json).read_text(encoding="utf-8")
            )
            if not isinstance(applicability_review, dict):
                raise ValueError("expected object")
        except (OSError, ValueError):
            print(json.dumps({"ok": False, "error": "applicability review JSON invalid"}))
            return 1

    safe_harbor_review = None
    if args.safe_harbor_review_json:
        try:
            safe_harbor_review = json.loads(
                Path(args.safe_harbor_review_json).read_text(encoding="utf-8")
            )
            if not isinstance(safe_harbor_review, dict):
                raise ValueError("expected object")
        except (OSError, ValueError):
            print(json.dumps({"ok": False, "error": "safe-harbor review JSON invalid"}))
            return 1

    database_path = Path(args.state_db)
    # Same wiring as apps/api composition: real loader guards, no shortcuts.
    from proofops.adapters.local.review_store import LocalSQLiteReviewStore  # noqa: E402
    from proofops.adapters.local.rulepack_store import RulePackSqliteStore  # noqa: E402
    from proofops.adapters.local.run_store import LocalSQLiteRunStore  # noqa: E402
    from proofops.adapters.local.tag_store import LocalTagStore  # noqa: E402
    from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser  # noqa: E402
    from proofops.application.authorization import AuthContext  # noqa: E402
    from proofops.application.registry import Registry, RulePackChoice  # noqa: E402
    from proofops.application.reviews import (  # noqa: E402
        AI_DELEGATED_ORIGIN,
        AI_DELEGATED_REVIEW_STATUS,
    )
    from proofops.application.reviews import (
        ReviewService as _ReviewService,
    )
    from proofops.application.uploads import UploadService  # noqa: E402

    rulepack_store = RulePackSqliteStore(database_path)

    def _active_packs(tenant_id: str) -> tuple[RulePackChoice, ...]:
        return tuple(
            RulePackChoice(
                pack.rule_pack_id,
                pack.tenant_id,
                pack.version,
                pack.sha256,
                pack.status,
                pack.mode,
                pack.effective_date,
                pack.unresolved_gap_ids,
            )
            for pack in rulepack_store.list_active_packs(tenant_id)
        )

    registry = Registry.sqlite(database_path, active_rule_packs=_active_packs)
    runs = LocalSQLiteRunStore(database_path, rulepacks=rulepack_store)
    uploads = UploadService(database_path, database_path.parent / "objects", registry)
    parser = OpenDataLoaderParser(database_path.parent / "parser-prepared")
    tags = LocalTagStore(runs, uploads, parser)
    service = _ReviewService(LocalSQLiteReviewStore(runs.jobs), load_inputs=tags.load_inputs)

    store = service.store
    try:
        review = store.get(args.tenant_id, args.review_id)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"review not found: {exc}"}))
        return 1
    if_match = args.if_match or f'"{review["revision"]}"'
    report: dict = {
        "review_id": review["review_id"],
        "run_id": review["run_id"],
        "claim_id": review["claim_id"],
        "status": review["status"],
        "revision": review["revision"],
        "base_tag_revision": review["base_tag_revision"],
        "if_match": if_match,
        "re_review": args.re_review,
        "element_count": len(body["elements"]) if isinstance(body.get("elements"), list) else 0,
        "applicability_review": applicability_review,
        "safe_harbor_review": safe_harbor_review,
        "would_record_origin": AI_DELEGATED_ORIGIN,
        "would_record_review_status": AI_DELEGATED_REVIEW_STATUS,
        "would_record_reviewer_sub": f"ai-delegated-review:{args.delegated_reviewer}",
        "note": "AI 검토(위임·사람 아님); comparisons still require human_confirmed",
    }
    if not args.apply:
        report["applied"] = False
        report["note"] = (
            "dry run: pass --apply to write the AI-delegated revision; " + report["note"]
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if not args.delegated_reviewer.strip() or not args.delegation_authority.strip():
        print(json.dumps({"ok": False, "error": "delegated reviewer/authority must be non-blank"}))
        return 1
    actor = AuthContext(
        args.actor_sub or args.delegated_reviewer.strip(),
        args.tenant_id,
        "reviewer",
        frozenset({"viewer", "reviewer"}),
        "local-cli",
    )
    # Local loader path: reuse the composition service's loader when present.
    if getattr(service, "load_inputs", None) is None:
        print(json.dumps({"ok": False, "error": "review service has no input loader"}))
        return 1
    try:
        result = service.resolve_ai_delegated_review(
            actor,
            args.review_id,
            body,
            if_match,
            args.idempotency_key,
            delegated_reviewer=args.delegated_reviewer,
            delegation_authority=args.delegation_authority,
            applicability_review=applicability_review,
            safe_harbor_review=safe_harbor_review,
            reopen=args.re_review,
        )
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", type(exc).__name__)
        status = getattr(exc, "status", None)
        print(json.dumps({"ok": False, "error": code, "status": status}))
        return 1
    report["applied"] = True
    report["new_tag_revision"] = result["new_tag_revision"]
    report["review_status"] = result["decision"]["review_status"]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
