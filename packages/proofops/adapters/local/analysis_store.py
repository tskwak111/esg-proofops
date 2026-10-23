"""Immutable local projections for observations, assurance and safe harbor."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, cast

from proofops.adapters.local.catalog_pages import initialize, page
from proofops.adapters.local.run_artifacts import load_run_graph
from proofops.application.assurance import ClaimContext, match_assurance
from proofops.application.assurance import (
    claim_context_from_review_inputs as _claim_context_from_review_inputs,
)
from proofops.application.ingest.normalize import normalize_tables
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.engine import ConfirmedFact, ConfirmedTags
from proofops.domain.rules.safe_harbor import record_safe_harbor
from proofops.domain.values import _source_ref_from_dict

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable
    from typing import Any, NoReturn

    from proofops.adapters.local.assurance_store import LocalAssuranceStore
    from proofops.adapters.local.claim_store import LocalClaimStore
    from proofops.adapters.local.run_store import LocalSQLiteRunStore
    from proofops.adapters.local.tag_store import LocalTagStore
    from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
    from proofops.application.claims import Claim
    from proofops.application.reviews import ReviewInputs
    from proofops.application.uploads import UploadService


claim_context_from_review_inputs = _claim_context_from_review_inputs


class SafeHarborPending(ValueError):
    """A confirmed head exists but its immutable inputs cannot be replayed."""


def _missing_snapshot() -> NoReturn:
    raise ValueError("missing catalog snapshot")


class LocalAnalysisStore:
    """Build fixed v1 pages from the run's fence-published artifacts."""

    kind = "local-synthetic-only"

    def __init__(
        self,
        runs: LocalSQLiteRunStore,
        uploads: UploadService,
        parser: OpenDataLoaderParser,
        claims: LocalClaimStore,
        tags: LocalTagStore | None = None,
        assurance: LocalAssuranceStore | None = None,
    ) -> None:
        paths = {Path(runs.path).resolve(), Path(claims.store.path).resolve()}
        if tags is not None:
            paths.add(Path(tags.store.path).resolve())
        if len(paths) != 1:
            raise ValueError("runs, claims and tags must share one local database")
        self.runs, self.uploads, self.parser = runs, uploads, parser
        self.claims, self.tags = claims, tags
        # Optional source-validated assurance replay. When absent the matcher
        # keeps receiving None and every claim stays "undetermined".
        self.assurance_store = assurance

    def _continuation(
        self, tenant_id: str, run_id: str, endpoint: str, cursor: str | None, limit: int, now: float
    ) -> dict[str, Any]:
        with self.runs.jobs._transaction() as db:
            initialize(db)
            return page(
                db,
                tenant_id=tenant_id,
                endpoint=endpoint,
                query={"run_id": run_id, "filter": None},
                cursor=cursor,
                limit=limit,
                now=now,
                load_items=_missing_snapshot,
            )

    def _first_page(
        self,
        tenant_id: str,
        run_id: str,
        endpoint: str,
        limit: int,
        now: float,
        prepared: Callable[[sqlite3.Connection, dict[str, Any]], list[dict[str, Any]]],
        snapshot: dict[str, Any],
        epoch: int,
    ) -> dict[str, Any]:
        with self.runs.jobs._transaction() as db:
            initialize(db)
            current_snapshot = self.runs._snapshot(db, tenant_id, run_id)
            current_run = self.runs.jobs._get(db, tenant_id, run_id, "run", "META")
            if (
                canonical_hash(current_snapshot) != canonical_hash(snapshot)
                or current_run["mutation_epoch"] != epoch
            ):
                raise ValueError("run changed while analysis inputs were loading")
            items = prepared(db, current_run)
            return page(
                db,
                tenant_id=tenant_id,
                endpoint=endpoint,
                query={"run_id": run_id, "filter": None},
                cursor=None,
                limit=limit,
                now=now,
                load_items=lambda: {"items": items, "snapshot_epoch": epoch},
            )

    def observations(
        self, tenant_id: str, run_id: str, *, cursor: str | None, limit: int, now: float
    ) -> dict[str, Any]:
        if cursor is not None:
            return self._continuation(tenant_id, run_id, "observations", cursor, limit, now)
        snapshot = self.runs.snapshot(tenant_id, run_id)
        epoch = self.runs.get(tenant_id, run_id)["mutation_epoch"]
        graph = load_run_graph(
            self.runs, self.uploads, self.parser, tenant_id=tenant_id, run_id=run_id
        )
        observations = tuple(
            sorted(
                normalize_tables(graph, tenant_id=tenant_id).observations,
                key=lambda item: (item.table_id, item.row, item.column, item.observation_id),
            )
        )
        items = [item.to_dict() for item in observations]
        return self._first_page(
            tenant_id,
            run_id,
            "observations",
            limit,
            now,
            lambda _db, _run: items,
            snapshot,
            epoch,
        )

    def assurance(
        self, tenant_id: str, run_id: str, *, cursor: str | None, limit: int, now: float
    ) -> dict[str, Any]:
        if cursor is not None:
            return self._continuation(tenant_id, run_id, "assurance", cursor, limit, now)
        snapshot = self.runs.snapshot(tenant_id, run_id)
        epoch = self.runs.get(tenant_id, run_id)["mutation_epoch"]
        discovery = self.claims.load(tenant_id, run_id)
        claims = self._ordered_claims(discovery.claims)
        # One published source-validated opinion per run (or None). The identical
        # matcher runs for every claim with source-validated preliminary dimensions;
        # unavailable dimensions stay undetermined.
        statement = (
            self.assurance_store.load(tenant_id, run_id)
            if self.assurance_store is not None
            else None
        )

        def _claim_context(claim: Claim) -> ClaimContext | None:
            try:
                review_inputs = (
                    self.tags.load_inputs(tenant_id, run_id, claim.claim_id)
                    if self.tags is not None
                    else None
                )
            except Exception:
                review_inputs = None
            try:
                return claim_context_from_review_inputs(
                    review_inputs,
                    tenant_id=claim.tenant_id,
                    document_version_id=claim.document_version_id,
                    claim_id=claim.claim_id,
                )
            except Exception:
                return ClaimContext(
                    tenant_id,
                    claim.document_version_id,
                    claim.claim_id,
                    None,
                    None,
                    (),
                    (),
                )

        # Invalid claim identity may yield None; retain the existing matcher failure.
        matches = [
            match_assurance(statement, cast(ClaimContext, _claim_context(claim))).to_dict()
            for claim in claims
        ]
        return self._first_page(
            tenant_id,
            run_id,
            "assurance",
            limit,
            now,
            lambda _db, _run: matches,
            snapshot,
            epoch,
        )

    def safe_harbor(
        self, tenant_id: str, run_id: str, *, cursor: str | None, limit: int, now: float
    ) -> dict[str, Any]:
        if cursor is not None:
            return self._continuation(tenant_id, run_id, "safe-harbor", cursor, limit, now)
        snapshot = self.runs.snapshot(tenant_id, run_id)
        run = self.runs.jobs.get_run(tenant_id, run_id)
        epoch = run["mutation_epoch"]
        discovery = self.claims.load(tenant_id, run_id)
        claims = self._ordered_claims(discovery.claims)
        inputs = {}
        if self.tags is not None and "tag_job" in run:
            for claim in claims:
                try:
                    value = self.tags.load_inputs(tenant_id, run_id, claim.claim_id)
                    inputs[claim.claim_id] = (value, canonical_hash(value.snapshot()))
                except KeyError:
                    pass

        def records(db: sqlite3.Connection, _run: dict[str, Any]) -> list[dict[str, Any]]:
            return [
                self._safe_record(db, tenant_id, run_id, claim, inputs.get(claim.claim_id))
                for claim in claims
            ]

        return self._first_page(
            tenant_id,
            run_id,
            "safe-harbor",
            limit,
            now,
            records,
            snapshot,
            epoch,
        )

    @staticmethod
    def _ordered_claims(claims: Iterable[Claim]) -> tuple[Claim, ...]:
        return tuple(
            sorted(
                claims,
                key=lambda claim: (
                    claim.source_refs[0].page_num,
                    claim.source_refs[0].char_start,
                    claim.source_refs[0].source_id,
                    claim.claim_id,
                ),
            )
        )

    @staticmethod
    def _unknown_safe_harbor(claim_id: str) -> dict[str, Any]:
        return {
            "claim_id": claim_id,
            "applicable": None,
            "category": None,
            "checklist": [],
            "reasonable_basis_documented": None,
            "legal_effect": "not_determined",
            "mapping_status": "unresolved",
            "gap_ids": ["GAP-002"],
        }

    def _safe_record(
        self,
        db: sqlite3.Connection,
        tenant_id: str,
        run_id: str,
        claim: Claim,
        prepared_inputs: tuple[ReviewInputs, str] | None,
    ) -> dict[str, Any]:
        raw_head = self.runs.jobs._raw(db, tenant_id, run_id, "claim_head", claim.claim_id)
        if raw_head is None:
            return self._unknown_safe_harbor(claim.claim_id)
        head = json.loads(raw_head)
        tag = self.runs.jobs._get(
            db,
            tenant_id,
            run_id,
            "tag_revision",
            f'{claim.claim_id}:{head["tag_revision"]:010}',
        )
        raw = tag.get("confirmed_tags")
        if raw is None or raw.get("safe_harbor_category") is None:
            return self._unknown_safe_harbor(claim.claim_id)
        if prepared_inputs is None:
            raise SafeHarborPending("confirmed safe-harbor inputs are unavailable")
        inputs, expected_input_hash = prepared_inputs
        input_hash = (
            canonical_hash(tag["inputs"]) if "inputs" in tag else tag.get("input_snapshot_sha256")
        )
        if input_hash != expected_input_hash:
            raise SafeHarborPending("confirmed safe-harbor inputs do not match")
        confirmed = ConfirmedTags(
            **(
                raw
                | {
                    "facts": tuple(
                        ConfirmedFact(
                            **(
                                fact
                                | {
                                    "evidence_refs": tuple(
                                        _source_ref_from_dict(ref) for ref in fact["evidence_refs"]
                                    )
                                }
                            )
                        )
                        for fact in raw["facts"]
                    )
                }
            )
        )
        if (
            confirmed.tag_revision != head["tag_revision"]
            or confirmed.claim_id != claim.claim_id
            or confirmed.document_version_id != claim.document_version_id
        ):
            raise SafeHarborPending("confirmed safe-harbor head does not match")
        return record_safe_harbor(confirmed, inputs.rule_context, inputs.rulepack).to_api_dict()
