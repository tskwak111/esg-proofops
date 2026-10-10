import type { Session } from "../session/api";
import type { ReviewElement, SourceRef } from "../reviews/ReviewWorkspace";
import type { ElementEvidence } from "./MissingEvidenceCard";

export type Track = "goal" | "performance" | "management";
export type ReviewStatus = "auto_confirmed" | "needs_review" | "human_confirmed" | "ai_delegated_confirmed";
export type Decision = {
  decision_revision: number;
  tag_revision: number;
  decision_status: "decided" | "blocked_evidence" | "blocked_rule_gap" | "not_applicable" | "not_run";
  evidence_grade: "E0" | "E1" | "E2" | "E3" | null;
  label: "SUBSTANTIATED" | "INCOMPLETE" | "UNSUBSTANTIATED" | null;
  sublabel: "PERF" | "IMPL" | null;
  review_status: ReviewStatus;
  missing_elements: string[];
  rule_ids: string[];
  rule_pack_sha256: string;
  semantic_hash: string;
  gap_ids: string[];
  // Engine v3+: reachable ladder grades while evidence is unresolved; not a grade.
  grade_range?: { floor: Grade; ceiling: Grade; open_elements: string[] } | null;
};
export type Grade = "E0" | "E1" | "E2" | "E3";
export type ClaimSummary = {
  claim_id: string;
  page_num: number;
  quote: string;
  track: Track | null;
  topic_ids: string[];
  decision: Decision | null;
  revision: number;
};
export type ClaimPage = { items: ClaimSummary[]; next_cursor: string | null; snapshot_epoch: number | null };
export type Assurance = {
  status: "covered" | "not_covered" | "undetermined";
  level: "limited" | "reasonable" | "none" | null;
  provider: string | null;
  statement_id: string | null;
  metric_match: "yes" | "no" | "unknown";
  period_match: "yes" | "no" | "unknown";
  boundary_match: "yes" | "no" | "unknown";
  evidence_refs: SourceRef[];
};
export type FieldAgreement = {
  field_id: string;
  status: "agreed" | "conflict" | "unresolved";
  replicate_values: unknown[];
};
export type ReviewCandidate = {
  source_ref: SourceRef;
  status: "candidate" | "unverified" | "unconfirmed";
  reason: string | null;
};
export type ReviewProjection = {
  schema_version: 1;
  candidate_snippets: string[];
  blocked_reason: string | null;
  blocked_action: string | null;
  field_agreements: FieldAgreement[];
  raw_candidates?: ReviewCandidate[];
};
// Optional review context; P6 stays on hold without a same-scope table observation.
export type ReviewedContextConsidered = { source_ref: SourceRef; status: string };
export type ReviewedContext = {
  origin: "ai_delegated";
  dimensions: {
    facility: SourceRef;
    reporting_period: SourceRef;
    metric: SourceRef;
    value: SourceRef;
    unit: SourceRef;
  };
  numeric_check: {
    status: "needs_review";
    reason: "no_comparable_table_observation";
    considered: ReviewedContextConsidered[];
  };
};
export type ClaimDetail = {
  element_evidence?: ElementEvidence[];
  claim: ClaimSummary;
  source_refs: SourceRef[];
  elements: ReviewElement[];
  assurance: Assurance;
  replicate_request_ids: string[];
  packet_sha256: string | null;
  tag_status?: "tagged" | "untagged" | null;
  suggestion: string | null;
  basis_refs: Array<{
    standard: string;
    clause: string | null;
    summary: string;
    verification_status: "verified" | "unverified" | "unlicensed";
  }>;
  rulepack_approved_by?: string | null;
  review_projection?: ReviewProjection | null;
  reviewed_context?: ReviewedContext | null;
  submitted_reviews?: Array<{
    reference_sha256: string;
    external_claim_id: string;
    origin: "data_manager_submission" | "ai_corrected_submission";
    claim_source_quality: string;
    tables: Record<"claims" | "elements" | "numeric" | "assurance", Array<Record<string, string>>>;
  }>;
};
export type LoadState = "loading" | "ready" | "pending" | "error";

export type CommonProps = {
  apiBase?: string;
  csrfToken: string;
  tenantKey: string;
  session: Session;
  runId: string;
  onSessionInvalid: () => void;
  onDataChanged: () => void;
};
export type ClaimWorkspaceProps = CommonProps & { claimId?: string };
