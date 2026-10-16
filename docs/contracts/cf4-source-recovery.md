# CF4 original-region source recovery

`CF4_SOURCE_POLICY` (`cf4_source_recovery_v1`) is an explicit new-run pin on
c3a3042/v27. The default and all historical policies remain unchanged. Selection
uses the normal `finals-unattended-v2` pinned-hash path. Rollback stops assigning
this pin to new runs and retains its reader for existing receipts.

The reader first executes the complete S5/v27 source verifier. Only unresolved
paragraph references enter CF4; tables keep their existing ownership checks.
For each eligible reference, the existing v4 native gate recomputes the exact
source identity, offsets, canonical quote, glyph geometry, annotation eligibility
and reversible character map from the original PDF. Native-only success does
not independently admit a new CF4 recovery.

The original annotated PDF is rendered at 216 dpi over the quote's glyph region.
Outward rounding and the inverse pixel-to-PDF transform are recorded. Six-pixel
horizontal padding and enough vertical white padding to bound the image aspect
ratio to 4:1 prevent very shallow strips from degrading OCR. Original pixels
are unchanged. The maximum is 16 million pixels and 24 distinct regions per
attestation; unsupported geometry and excess regions stay unresolved.

The existing budgeted, tenant-scoped Upstage OCR store obtains and authenticates
the reading. Acquisition failure stays unresolved. No caller-supplied response
or model correction is trusted. The existing word-ownership mapper and FXF
matcher require exact canonical text, confidence >=0.98 for every matched word,
and each native glyph center inside that word's polygon. Punctuation, numbers
and characters are never replaced to obtain agreement. This is independent
native-glyph plus rendered-pixel corroboration, not two votes from one parser.

A separate receipt retains the full previous receipt, all region manifests,
trusted collections, native maps and the new policy hashes. Cold replay renders
again, authenticates each retained collection in the private ledger, reruns
all matching, and compares the complete receipt. It never buys a replay read.
The public SourceRef, selected-page mapping and W18 coordinates are unchanged.
API/DB migration is unnecessary.

Replay requires the same rendering/PNG runtime. Mac and Linux can produce
identical decoded pixels with different PNG bytes; those manifests must fail
closed. Collect production receipts in the pinned Linux runtime rather than
importing Mac OCR collections or relaxing the image hash check.

This change establishes source presence only. It does not assign `present`,
convert unknown/conflict/unreadable to absence, change DEC-85/92/93, infer table
ownership, select among conflicting values, or grant scope confirmation. Fresh
replicas, evidence binding and the rule engine remain responsible for those
subsequent decisions. The CF4 report records the source, semantic and LG13 gates
separately; a failed gate must not be presented as integration approval.
