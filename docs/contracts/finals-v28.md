# I28: finals-20261016-v28

`finals-unattended-v2` selects `FINALS_I28_POLICY`, hash
`31808287164e43e17495bccb17e31e7c53c7746ff0f7c9148276958f7d28cab2`.
It is exactly the complete v27 policy plus the two RB4_STREAM memory selectors
and the new integration profile name. S5 remains the single source reader;
RB1 isolation, RB2 parser output/period handling, RB3 deadlines, and the I27
optional SC1 transient policy retain their v27 values.

The immutable v27 hash
`fcd788f4c89034141c8767913f1c1acabdaefa1c8f543cdc5231903f05fa1804`,
the pre-RB2 v27 pin, and standalone RB4 pins remain registered for preparation,
publication, and replay. V27 result reads retain duplicate occurrences and
table-observation source references after the default changes.

RB4 releases serialized inputs and proof references only after their existing
source, tenant, head, lease, and outcome checks. Publication compares the
validated canonical checkpoint digest before decoding a second copy, retaining
the original semantic comparison for noncanonical JSON. Legacy claim-store
facades without outcome projection retain their previous read contract.

Publication hashes every authoritative record as before, but sorts only keys
and reads each full value within the same SQLite transaction. This avoids
spilling large checkpoint BLOBs into the 512 MiB `/tmp` used by EC2 compose and
the public deployment runtime. No tmpfs enlargement, SQL temp-store change,
new dependency, DB migration, or API schema change is required for v28.

No rule, evidence-admission criterion, source receipt, or historical policy is
weakened. Fresh offline simulations measure pipeline and resource behavior,
not live-model accuracy. Deployment remains outside this local integration.
For a later authorized rollout or rollback, keep the API 1536 MiB override;
rollback code is `c3a304204b2f3c6eb6c61da2136cb176ae9a3957`. Existing v28 receipts
must be retained with a compatible reader, never rewritten as v27 artifacts.
