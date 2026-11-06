// Shared wire fields only. Hosted readers deliberately accept wider string values.
export type Track = "goal" | "performance" | "management";
export type ElementState = "present" | "absent" | "unknown" | "conflict" | "not_applicable";
export type Session<Role extends string = "viewer" | "editor" | "reviewer" | "admin"> = {
  user_id: string;
  tenant_id: string | null;
  role: Role | null;
  csrf_token: string;
  expires_at: string;
};
export type SourceRef<
  LocationQuality extends string = "located" | "unlocated" | "unreadable",
  VerificationState extends string = "candidate" | "verified" | "rejected",
> = {
  source_id: string; document_version_id: string; parse_manifest_id: string;
  page_num: number; printed_page_label: string | null; bbox: number[] | null;
  raw_text_sha256: string; quote: string; char_start: number; char_end: number;
  location_quality: LocationQuality;
  verification_state: VerificationState;
};
export type ReviewElement<Source = SourceRef> = {
  element_id: string; state: ElementState;
  evidence_refs: Source[]; normalized_value: string | null;
  credited_from: string | null; reason_code: string | null;
};
