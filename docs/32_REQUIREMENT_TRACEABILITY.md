# 32 · 요구사항 추적표

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## 추적 규칙
기계 판독 정본은 requirement_catalog/task_catalog/api_operations 다. HTTP operation 은 실제 OpenAPI 에 있어야 하고, 각 requirement 는 task/test 로 연결돼야 한다. 아래 entity 는6장의 DDB record 또는 S3 typedartifact 를뜻한다.

| Requirement | Priority | UI | API | Data | Task | Acceptance test |
|---|---|---|---|---|---|---|
| FR-001 | P0 | `/documents/new` | `POST /v1/documents; POST /v1/documents/{document_id}/versions` | DocumentVersion | TASK-001 | AT-001 |
| FR-002 | P0 | `/runs/:runId/claims/:claimId` | `GET /v1/runs/{run_id}/sources/{source_id}` | SourceArtifact | TASK-002 | AT-002 |
| FR-003 | P0 | `/runs/:runId/quality` | `GET /v1/runs/{run_id}/quality` | ParseManifest | TASK-003 | AT-003 |
| FR-004 | P0 | `/runs/:runId/quality` | `GET /v1/runs/{run_id}/observations` | Observation | TASK-004 | AT-004 |
| FR-005 | P0 | `/runs/:runId/claims/:claimId` | `GET /v1/runs/{run_id}/claims/{claim_id}` | CheckResult | TASK-005 | AT-005 |
| FR-006 | P0 | `/runs/:runId/quality` | `GET /v1/runs/{run_id}/quality` | IndexEntry | TASK-006 | AT-006 |
| FR-007 | P0 | `/runs/:runId/assurance` | `GET /v1/runs/{run_id}/assurance` | AssuranceStatement | TASK-007 | AT-007 |
| FR-008 | P0 | `/runs/:runId/claims` | `GET /v1/runs/{run_id}/claims` | Claim | TASK-008 | AT-008 |
| FR-009 | P0 | `/runs/:runId/claims/:claimId` | `GET /v1/runs/{run_id}/claims/{claim_id}` | TagRevision | TASK-009 | AT-009 |
| FR-010 | P0 | `/runs/:runId/claims/:claimId` | `GET /v1/runs/{run_id}/claims/{claim_id}` | TagRun | TASK-010 | AT-010 |
| FR-011 | P0 | `/runs/:runId/claims/:claimId` | `GET /v1/runs/{run_id}/claims/{claim_id}` | EvidencePacket | TASK-011 | AT-011 |
| FR-012 | P0 | `/runs/:runId/claims/:claimId` | `GET /v1/runs/{run_id}/sources/{source_id}` | EvidenceRef | TASK-012 | AT-012 |
| FR-013 | P0 | `/runs/:runId/claims/:claimId` | `GET /v1/runs/{run_id}/claims/{claim_id}` | EvidenceBinding | TASK-013 | AT-013 |
| FR-014 | P0 | `/runs/:runId/claims/:claimId` | `GET /v1/runs/{run_id}/claims/{claim_id}` | DecisionRevision | TASK-014 | AT-014 |
| FR-015 | P0 | `/runs/:runId/claims/:claimId` | `GET /v1/runs/{run_id}/claims/{claim_id}` | DecisionRevision | TASK-015 | AT-015 |
| FR-016 | P0 | `/runs/:runId/safe-harbor` | `GET /v1/runs/{run_id}/safe-harbor` | SafeHarborRecord | TASK-016 | AT-016 |
| FR-017 | P0 | `/runs/:runId/summary` | `GET /v1/runs/{run_id}/summary` | Applicability | TASK-017 | AT-017 |
| FR-018 | P0 | `/runs/:runId/summary` | `GET /v1/runs/{run_id}/summary` | Applicability | TASK-018 | AT-018 |
| FR-019 | P0 | `/runs/:runId/reviews` | `POST /v1/reviews/{review_id}/resolve` | Review | TASK-019 | AT-019 |
| FR-020 | P0 | `/runs/:runId` | `POST /v1/runs/{run_id}/rescores` | Rescore | TASK-020 | AT-020 |
| FR-021 | P0 | `/runs/:runId/report` | `POST /v1/runs/{run_id}/exports` | ExportSnapshot | TASK-021 | AT-021 |
| FR-022 | P0 | `/runs/:runId/audit` | `GET /v1/runs/{run_id}/audit` | AuditEvent | TASK-022 | AT-022 |
| FR-023 | P1 | `/runs/:runId/comparison` | `POST /v1/runs/{run_id}/comparisons` | Comparison | TASK-023 | AT-023 |
| FR-024 | P1 | `/documents/new` | `POST /v1/runs` | Run | TASK-024 | AT-024 |
| FR-025 | P0 | `/settings/rules` | `POST /v1/rule-packs/{rule_pack_id}/activate` | RulePack | TASK-025 | AT-025 |
| FR-026 | P0 | `/runs/:runId/summary` | `GET /v1/runs/{run_id}/summary` | Summary | TASK-026 | AT-026 |
| FR-027 | P0 | `/runs/:runId` | `GET /v1/runs/{run_id}` | Run | TASK-027 | AT-027 |
| FR-028 | P0 | `/runs/:runId` | `POST /v1/runs/{run_id}/cancel; POST /v1/runs/{run_id}/retry` | StageJob | TASK-028 | AT-028 |
| FR-029 | P0 | `/settings/runtime` | `POST /v1/preflight` | RuntimeBinding | TASK-029 | AT-029 |
| FR-030 | P0 | `/runs/:runId/cost` | `GET /v1/runs/{run_id}/cost` | UsageLedger | TASK-030 | AT-030 |
| FR-031 | P0 | `/runs/:runId/report` | `GET /v1/exports/{export_id}; POST /v1/exports/{export_id}/download` | ExportSnapshot | TASK-031 | AT-031 |
| FR-032 | P0 | `/settings/evaluation` | `GET /v1/evaluations/{evaluation_id}` | Evaluation | TASK-032 | AT-032 |
| NFR-001 | P0 | `/runs/:runId/audit` | `GET /v1/runs/{run_id}/audit` | RunManifest | TASK-033 | AT-033 |
| NFR-002 | P0 | `/runs/:runId` | `GET /v1/health/ready` | Health | TASK-034 | AT-034 |
| NFR-003 | P0 | `/runs/:runId/cost` | `GET /v1/runs/{run_id}/cost` | Trace | TASK-035 | AT-035 |
| NFR-004 | P0 | `/runs/:runId/reviews` | `GET /v1/runs/{run_id}/claims` | SchemaVersion | TASK-036 | AT-036 |
| SEC-001 | P0 | `/login` | `GET /v1/session; POST /v1/session/tenant` | Membership | TASK-037 | AT-037 |
| SEC-002 | P0 | `/documents/new` | `POST /v1/uploads/{upload_id}/complete` | Upload | TASK-038 | AT-038 |
| SEC-003 | P0 | `/settings/runtime` | `POST /v1/preflight` | ConsentProfile | TASK-039 | AT-039 |
| SEC-004 | P0 | `/documents/:documentId` | `POST /v1/documents/{document_id}/deletion-requests` | DeletionRequest | TASK-040 | AT-040 |
| SEC-005 | P0 | `/login` | `POST /v1/auth/logout` | Session | TASK-041 | AT-041 |
| SEC-006 | P0 | `/settings/runtime` | `POST /v1/preflight` | LicenseInventory | TASK-042 | AT-042 |
| FR-033 | P0 | `/documents/new` | `GET /v1/companies; POST /v1/companies; GET /v1/runtime-options` | Company | TASK-045 | AT-045 |

## 소스→명세 연결
원문 §4→28장/루브릭/FX-RULE; 원문 §5–6→03·09·10·27장/graph/source contracts; 원문 §8→06·07장/JSONSchema; 원문 §9→04·16·17장; 원문 §10→14장; 원문 §12→19·20장; 원문 §13→30·31장. 기존 GitHub 코드→26장/evidencelegacyinspection, 두번째첨부의00–25요청→동명문서로연결한다.
