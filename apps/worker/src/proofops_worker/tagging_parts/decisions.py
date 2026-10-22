"""Explicit local Decisions research path; never a hosted default."""

from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

from proofops.adapters.local.upstage import request_usage
from proofops.application.budget import BudgetCall, TokenUsage
from proofops.application.evidence.binding import local_relation_tags
from proofops.application.ports.jobs import LeaseLost
from proofops.application.registry import artifact_sha256
from proofops.domain.provenance import canonical_hash


def decision_pair(
    self, claim, state, questions, purpose, *, packet_sha256, retrieval_packet_sha256=None
):
    from proofops.application.preflight import check_local_decision_binding
    from proofops.application.tagging.decisions import POLICY

    self.allow_packet(claim.claim_id, packet_sha256)
    answers, receipts = [], []
    for provider in ("openai", "openrouter"):
        probe = self.decision_probes[provider]
        request_id = str(
            uuid5(
                UUID(self.lease.message.job_id),
                f"decision:{purpose}:{claim.claim_id}:{provider}",
            )
        )
        pins = dict(
            tenant_id=self.auth.tenant_id,
            run_id=self.snapshot["run_id"],
            claim_id=claim.claim_id,
            graph_sha256=canonical_hash(asdict(self.graph)),
            packet_sha256=packet_sha256,
            retrieval_packet_sha256=retrieval_packet_sha256,
            policy_sha256=canonical_hash(POLICY),
            settings_sha256=self.snapshot["decision_settings_hash"],
            runtime_sha256=self.snapshot["decision_runtime_hashes"][provider],
        )
        call = BudgetCall(
            self.auth.tenant_id,
            self.snapshot["run_id"],
            self.graph.document_version_id,
            request_id,
            1,
            "decision",
            probe.model,
            "provider-managed-unverified",
            canonical_hash(POLICY["models"][provider]),
            canonical_hash(dict(state=state, questions=questions, pins=pins)),
            None,
        )

        def check_authority():
            self._fence()
            for kind, frozen, identifier in (
                ("runtime", self.snapshot["decision_runtimes"][provider], "runtime_binding_id"),
                ("consent", self.snapshot["consent"], "consent_profile_id"),
                ("rights", self.snapshot["rights"], "rights_profile_id"),
            ):
                current = self.registry.resolve_profile(self.auth, kind, frozen[identifier])
                if artifact_sha256(current) != artifact_sha256(frozen):
                    raise ValueError("DECISION_APPROVAL_CHANGED")
            if not check_local_decision_binding(
                binding=self.snapshot["decision_runtimes"][provider],
                consent=self.snapshot["consent"],
                auth=self.auth,
                checked_at=datetime.fromtimestamp(self.runner.clock(), UTC).isoformat(),
                source_sha256=self.graph.source_sha256,
                document_rights=self.snapshot["document"]["metadata"]["rights_profile_id"],
                provider=provider,
                settings=self.snapshot["decision_settings"],
            ).ready:
                raise ValueError("DECISION_PREFLIGHT_BLOCKED")

        def authorize():
            check_authority()
            if not self.runner.store.usage.reserve_budget(
                call,
                input_tokens=66560,
                max_output_tokens=4096,
                pricing=None,
                now=int(self.runner.clock()),
            ):
                raise ValueError("DECISION_PENDING_CALL")

        def dispatch():
            check_authority()
            if not self.runner.store.usage.mark_dispatched(call):
                raise ValueError("DECISION_PENDING_CALL")

        try:
            self._check_heartbeat()
            result = probe.decide(
                state,
                questions,
                request_id=request_id,
                pins=pins,
                authorize=authorize,
                before_dispatch=dispatch,
            )
            receipt = result["receipt"]
            self.runner.store.usage.record_usage(
                call,
                TokenUsage(
                    receipt["input_tokens"],
                    receipt["output_tokens"],
                    0,
                    0,
                    receipt["latency_ms"],
                    "succeeded",
                    receipt["provider_request_id"],
                ),
                now=int(self.runner.clock()),
            )
            answers.append(result["answers"])
            receipts.append(receipt)
        except LeaseLost:
            raise
        except (ValueError, OSError, KeyError, TypeError) as error:
            answers.append({})
            code = (
                str(error)
                if str(error)
                in {
                    "BUDGET_EXHAUSTED",
                    "R108_BUDGET_EXHAUSTED",
                    "DECISION_PENDING_CALL",
                    "DECISION_REQUEST_FAILED",
                    "DECISION_ANSWERS_INVALID",
                    "DECISION_PREFLIGHT_BLOCKED",
                    "DECISION_APPROVAL_CHANGED",
                    "PROBE_REQUEST_TOO_LARGE",
                    "DECISION_RECEIPT_MISMATCH",
                }
                else "DECISION_LOCAL_STOP"
            )
            receipts.append(
                dict(
                    request_id=request_id,
                    provider=provider,
                    status="needs_review",
                    error_code=code,
                )
            )
        finally:
            with self._account_lock:
                self.decision_request_ids[provider].add(request_id)
                self.usage["decision_usage"] = {
                    p: request_usage(pr.ledger, sorted(self.decision_request_ids[p]))
                    for p, pr in self.decision_probes.items()
                }
                self.usage["decision_request_ids"] = {
                    p: sorted(ids) for p, ids in self.decision_request_ids.items()
                }
    return answers, receipts


def decision_preliminary(self, claim, packet, results):
    from proofops.application.evidence.binding import ClaimContext
    from proofops.application.tagging.decisions import (
        AXES,
        POLICY,
        preliminary_dimensions,
        preliminary_questions,
        preliminary_state,
        resolve_preliminary,
    )
    from proofops.application.tagging.tracks import validate_track_candidates

    quotes = {}
    if results is not None:
        for axis in AXES:
            values = [r.context.dimensions.get(axis) for r in results]
            if all(v == values[0] for v in values) and values[0] is not None:
                quotes[axis] = values[0]
    pair, receipts = self._decision_pair(
        claim,
        preliminary_state(packet),
        preliminary_questions(),
        "preliminary",
        packet_sha256=canonical_hash(packet),
    )
    fields = resolve_preliminary(*pair, quotes)
    categories = [r.safe_harbor_category for r in results] if results else []
    category_agreed = len(categories) == 3 and all(c == categories[0] for c in categories)
    self.decision_records[claim.claim_id] = dict(
        fields={
            k: v | {"value": asdict(v["value"]) if k != "track" and v["value"] else v["value"]}
            for k, v in fields.items()
        },
        receipts=receipts,
        policy_sha256=canonical_hash(POLICY),
        safe_harbor_category=dict(
            state="agreed" if category_agreed else "unresolved", replicate_values=categories
        ),
    )
    if results is None or fields["track"]["state"] != "agreed" or not category_agreed:
        return None
    track = validate_track_candidates(
        (claim,),
        (
            dict(
                claim_id=claim.claim_id,
                track=fields["track"]["value"],
                safe_harbor_category=categories[0],
            ),
        ),
    )[0]
    context = ClaimContext(
        claim, preliminary_dimensions(fields, [r.context.dimensions for r in results])
    )
    return track, context, local_relation_tags(context)


def configure_decisions(self, runner, snapshot, ledger):
    self.decision_probes = {}
    if "decision_settings" in snapshot:
        import os

        from proofops.adapters.local.decisions import DecisionProbe, load_key
        from proofops.application.tagging.decisions import validate_decision_snapshot

        validate_decision_snapshot(snapshot)
        injected = getattr(runner, "decision_probes", None)
        if injected is not None:
            self.decision_probes = injected
        else:
            project = Path(
                os.environ.get(
                    "PROOFOPS_DECISION_PROJECT_ROOT", str(Path(ledger).resolve().parents[2])
                )
            )
            historical = [
                project / ".local" / p / "budget.sqlite3" for p in ("openrouter", "upstage")
            ]
            for provider in ("openai", "openrouter"):
                self.decision_probes[provider] = DecisionProbe(
                    provider,
                    project / ".local" / provider / "budget.sqlite3",
                    r108_spend=project
                    / "outputs/agent-results/R108-redesign/lab/sprint3/E2E/r108-spend.json",
                    key_loader=lambda p=provider: load_key(p, project),
                    historical_ledgers=historical,
                )
