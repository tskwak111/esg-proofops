# I3 integration: finals-20261011-v3

`finals-unattended-v2` now selects `FINALS_I3_POLICY` for new runs. Its canonical
hash combines W4/W7/W8/DEC24/W9/W3 with J3/J7/J8 and K1/K2/K3. Old I1/I2, standalone
policies and the rejected I2 J3 candidate remain exact hash-selected replay inputs.
The rejected candidate and old integration defaults cannot publish a new run.

J8 owned-cell selection and K3 worker routing/source v11 are independent options;
neither replaces the other. The parser binds v11 to the owning run, and every new
child span receives its own source check. A parent attestation or grade is never
copied to a child. W4 retains the same bounded scope ranking and page provenance.

The I3 compact selection wire shares identical literal parent context by index and
sends candidate IDs, text, roles and row/column to the model. The full original
offsets, source IDs and binding metadata remain in the local candidate planner and
immutable packet. No candidate text or parent context is truncated. This wire is
explicitly versioned and changes extraction rule/prompt/request hashes; J8's
historical wire remains unchanged. The existing 16,384-byte provider cap stays in
force. Unknown/conflict/unreadable never become absent; source repair alone cannot
produce present or a grade. K1/K2 revalidate retained votes only where available.

There is no public DTO/DB column or dependency change. Runtime settings add the
trusted `extraction_i3_wire` option, permitted only with J8 and the known I3 policy.
Rollback stops new v3 creation and deploys the prior release; v3 snapshots must
retain their matching readers for replay. Existing reports/revisions stay immutable.
No push, deployment, runtime.env edit, AWS change or new parser/model purchasing
is authorized by this contract. The task's model canary uses a shared USD .30 cap.
