# I23 · v23 local integration

New hosted runs default to `finals-20261015-v23`: v22 execution
(`exact-verified-read-v12`), FXA visible-glyph admission, FXB authenticated current
responses, FXC `grade-relevant-unanimity-v3`, and D2 page-local OCR acquisition
holds. Surviving grade-relevant conflict remains conflict when other replicas
fail; review and null grade/label remain mandatory. Python grading rules,
three-replica checks, and disabled general C4/C5/C6 publication are unchanged.

The current v21 source wrapper composes the complete D2 reader with the existing
v4 prose verifier. D2's private replay dispatch binds to its current Reader;
retained OCR collections bind to the active reader instance. Known acquisition
failures remain unresolved per page/block with fixed cause codes; integrity
errors still fail closed. Nested page receipts keep their original hashes.

Historical v20/v21/v22, standalone FXB/FXC, and D2 analysis pins remain registered.
D2's shipped reader is preserved byte-for-byte in `upstage_ocr_profile_d2_v21.py`;
the exact pre-D2 v21 wrapper is archived separately. Complete stored source policy
equality selects historical readers, which remain replay-only for new claim
publication. Originals, receipts, public revisions and exports are immutable.

No API/DB migration or dependency change is required. Rollback restores
`3f64d71` and stops assigning new v23 work; preserve v23 artifacts with a compatible
reader or explicitly reject unsupported hashes. Never reinterpret them as v22.

Local evidence and the build/deployment handoff are in
`outputs/agent-results/R108-redesign/lab/perf/I23/`. No push, deployment, EC2,
operational runtime configuration change, or real model API call is authorized.
Offline smoke and fake provider dispatches prove wiring, not model accuracy.
