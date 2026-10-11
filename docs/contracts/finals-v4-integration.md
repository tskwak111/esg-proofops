# finals-20261012-v4 — I4 integration

I4 combines K4 `503039d`/`e61f4f4`, S1 `1e78a14`, and only P2
`80942eb`'s identity-free renderers, numerical value/quote guidance and G6
declaration-versus-means guidance. The reconstructed P2 extraction and full
rubric prompts are excluded. Existing v3 rule cards and definitions are frozen
in `finals_i4_assets`; extraction candidate semantics and the Python rulepack are unchanged.
An observed UUID typo rejected a whole 20-cell selection. New I4 dispatches use
short local selectors `c0..cN` and a closed enum, with original identities, source
text and offsets retained on the server. Unknown/duplicate selectors and old UUID
echoes are rejected. Historical extraction profiles keep their original ID wire;
failed old responses are never repaired. This changes the extraction prompt/rule
and composite hashes, not claim admission or the P2 semantic extraction prompt.

The composite is selected as `finals-unattended-v2` with integration profile
`finals-20261012-v4`. Its canonical hash includes both prompt contents, K4
policies and the original S1 implementation hash. An explicit JSON-null instruction
was added after two new preliminary responses emitted the string `"null"`;
that changes the prompt and composite hashes. Existing table-observation routing
and the claim-local masked-PUE restriction were clarified after ordinary numeric
rows were incorrectly treated as masked bands. Original failed receipts remain
failed and are retained in the I4 measurement directory.

Pilot and worker settings select `K4_PRELIMINARY`/`K4_ELEMENTS`. Preflight
allowlists and local configuration require matching prompts/profile. Authorized
preliminary packets pin the new prompt hash. PB2 fact-field restrictions and K4
identity removal run before `preliminary_k4`/`elements_k4` render the final schema.
The preliminary renderer replaces the legacy `exactly claim_id` instruction.
Element requests select COMMON, the validated track, and TAIL. Full requests must
fit the existing 16,384-byte body bound.

The authorized packet retains K4 response/value policies; provider projection
removes server-only policy metadata. Raw provider responses are validated against
the no-identity wire schema before dispatch-owned `bind_response`. Internal
LlmTags, tenant/packet/replica checks, cache signatures, source admission and three
guarded votes are preserved. Echoed identity, extra keys and invalid raw types
are rejected; no response repair or new transport retry is introduced.

S1's original `parse_table_cache.py` bytes and standalone policy remain pinned.
`i4_parse_scope.for_snapshot` activates the same cache for only the exact composite
snapshot after verifying its hash and original S1 implementation. Historical
snapshots delegate to the original S1 selector. Cold/mismatched proofs execute
the original verifier. Native and evidence source checks still run. K4 facilities
are review dimensions, not element votes or automatic grade credit.

Public API/DB schema, migrations and dependencies are unchanged. The new prompt
profile is an internal opaque settings field. Explicit v1/v2/v3 pins keep their
original policy/rendering; v3 remains accepted for rollback. Standalone K4 stays
publication-blocked. Stop selecting the new composite to roll back; keep its
reader, original artifacts, revisions and reports. No runtime.env/cloud change
is part of I4. Adoption and measured limitations are recorded in I4-REPORT.md.
