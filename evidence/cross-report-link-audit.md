# Cross-report evidence-link audit — 2026-09-12

Orca run `run_c113b48f36e3`, worker `task_2e25d9b39975` (Muse Spark 1.2 Free).
Coordinator reviewed and corrected the worker findings before integration.

## Supported findings

Archived LG retrieval results contain lexical matches in DATA/APPENDIX, including
Scope 1 totals near a Scope 1+2 baseline/target claim. Lexical similarity alone does
not establish matching entity, metric, period, boundary or numeric attribution.
The existing source-quality and binding guards must remain in force. Two archived
E-scope packets have `blocked_evidence`; this does not measure all claim bindings.
No production retrieval/binding defect was reproduced or guard relaxed in this wave.

`tests/unit/test_cross_report_link_audit.py` actually calls SectionSearch with a
valid scope (positive hits), then changes tenant, document version, parse manifest
or index generation separately. All four mismatches must raise. It uses existing
synthetic test graph helpers and does not depend on untracked local archives.
Existing section-pipeline tests cover candidate-only retrieval/quality behavior.

## Discarded worker claims

The worker's `.local/cross-report-audit/repro.py` hard-coded `accepted=0` and
`scope_mismatch=True`. These are not runtime measurements and are not evidence of
zero accepted bindings or a reproduced isolation failure. Its archive-based test
was replaced by the real scope-guard calls above. No human gold or verified source
quality was created. Old section maps missed Doosan/Kakao scopes; independent v5
map inspection and correction are recorded in cross-report-service-evaluation.md.

## Remaining work

Evaluate retrieval and dimensions against independently reviewed claim/evidence
pairs across companies. A matching quote is still a candidate until source and
attribution contracts pass. Current tests do not establish retrieval recall,
numeric correctness, human approval or production readiness.
