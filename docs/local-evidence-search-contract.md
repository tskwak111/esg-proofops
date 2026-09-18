# Local evidence search — TASK-011

`proofops.adapters.local.evidence_search.LocalEvidenceSearch` implements the existing
EvidenceSearchPort without network calls, new dependencies or evaluation imports.
It reuses the existing Korean-bigram/Latin/numeric BM25 ranking, positive scores,
deterministic source-ID tie breaking and at most20 hits per query.

Construct with a trusted canonical graph, tenant_id, explicit physical `pages`,
and caller-pinned `index_generation`. Pin generation to the source/graph/page
selection and retrieval policy when composing a run; this value is not a source
approval. Tenant/document/manifest must match the graph and every subsequent
SearchScope must equal the constructed scope. Duplicate canonical IDs, bool or
nonpositive/noninteger pages and pages missing from the graph are rejected.
An empty page selection searches nothing and does not prove absence.

The adapter returns original source IDs/text hashes. It does not change source
quality, assign semantic relationships, reconstruct tables, or count provider
tokens. `synthetic` follows parser candidate provenance. Vector requests return
`not_run`; no embedding or model call is fabricated. Missing and zero-score hits
remain unknown. Korean single-character terms and synonyms may be missed; no
semantic recall claim is made. The local index scans its selected blocks per query;
replace with an indexed backend only when measured volume warrants it.

`evaluation.section_pipeline.SectionSearch` now delegates ranking to this adapter.
Its validated section map, index generation, valid-input ranking and public error
message remain compatible. `pages` describes indexed pages; `missing_pages`
separately lists declared evidence pages not parsed. `coverage` retains the full
candidate map, so missing appendix pages are not hidden or treated as processed.
`search_terms` remains importable from the previous evaluation module.

There is no API or DB change/migration. Existing receipt/cache identities and
snapshots are not rewritten. Rollback restores the former evaluation search;
retain its outputs. The default LocalTagRunner still uses its bounded atomic-only
search: enabling broad retrieval there requires a frozen runtime retrieval contract
and verified relationship supplier. This change prepares the reusable adapter and
connects the existing section-aware evaluation/demo path, not the real tag worker.

Every consumer must call retrieve_evidence for source-quality and citation checks,
then the existing binding/tagging guards. Ranking does not authorize `present`.
Numbers and target years on distant pages do not acquire local-claim scope through
search. Unresolved tables, footnotes and source issues remain unresolved.
