# Native footnote extraction checkpoint — 2026-09-14 KST

Goal remains active. This adds a real two-stage model experiment, not a production
note-acceptance service. The original goal has not been narrowed to this checkpoint.

## Change and actual failure loop

`evaluation/table_layout_context.py` preserves mixed-size/mixed-baseline native
characters in styled words; table-role packets carry that context. Ordinary
Scope1 digits are not inferred to be footnotes. `evaluation/table_notes.py`
rebuilds the packet from the pinned graph and original PDF before accepting any
model fragment ID. All same-page parsed tables are required; unknown ownership
and unlocated source cells remain explicit. Model proposals never create graph
edges, accepted semantic bindings, present tags, grades or rule-engine results.

The first actual Solar Pro3 call selected the wrong table because the initial
prototype omitted every unlocated table cell. The next version retained those
cells without inventing coordinates, and separated discovery from ownership to
reduce request size. Its combined English discovery prompt still caused invalid
ownership outputs. A dedicated Korean discovery prompt with Solar Pro4 found the
three Kia notes and stopped classifying KB/Naver table rows as notes. Unconstrained
ownership still attached both numbered notes to the wrong table. The final probe
uses native raised-digit typography and unique same-table literal suffix matches
to constrain numbered-note proposals; its Korean binding prompt returned the
correct metric cells. These failures are retained under `.local/table-note-wave/`.

A numbered target requires a unique native marker candidate; absent, duplicate or
clipped marker candidates allow only unknown ownership. Arabic suffix markers
are the supported subset; other marker styles are unfinished. Fragment-order
manipulation cannot bypass the numbered-note constraint. General notes still
require semantic review; source membership does not prove that a fragment is a
note. Binding may retag kind while preserving the detected source-fragment sets.
A failed binding preserves discovery notes with empty targets, not approved links.

## Real-report observations

Final archive: `.local/table-note-wave/live-v4/{kia,kb,naver}`.
Local visual review: `.local/table-note-wave/review.html`.
The coordinator inspected the original PDF images, not just parser text.

- Kia physical45: domestic coverage → left waste-target table; vehicle-limited
  note1 → total plastic-material metric; vehicle-average note2 → recycled-plastic
  ratio metric. All three source conditions are retained. Kind2 was tagged
  methodology; the full average and vehicle qualifiers remain in the quote.
- KB physical30: no **external** table-note proposals on the inspected page.
  Parenthetical conditions inside investment cells are not validated by this result.
- Naver physical84: no external table-note proposals on the inspected page.
- Kakao physical114 holdout: request rejected before billing because it exceeds
  the existing16KB request budget. The subsequent Samsung Life holdout was not_run.

These are selected diagnostic pages, including one positive page. They do not
establish precision/recall, report-wide performance or service readiness.
Twelve paid calls across four prototype variants cost USD0.0151743900; the shared
ledger is USD7.6980694500 committed/reserved,1283 calls, with six old unsettled
reservations preserved. No ledger reset, separate budget or AWS call occurred.

## Orca review

Run `run_bd4f467aede6`, Muse Spark1.3 Free tasks `task_3853a1f01585` and
`task_16c3bb2b8019`. The first confirmed that the numeric checker has no direct
application caller. The second reproduced the wrong-table binding and identified
unresolved marker styles, interior-note classification and incomplete-boundary
risks. Native marker constraints were added with failing regressions. All
workers settled, were released, and their exact externally created terminals closed.

## Validation

- Fail-first: missing typography; missing note harness; unlocated-cell omission;
  wrong-table note acceptance; prepended-fragment marker bypass.
- Focused suite:12 passed.
- Ruff passed; mypy162 files passed with existing untyped-function notes.
- Four Python package builds passed.
- Full suite:1812 passed,2 existing deprecation warnings,116.63s;
  `.local/table-note-wave/pytest-final.log`.
- Current-code real-response replay passed for Kia/KB/Naver; the previous Kia
  wrong-table response now fails the native-marker constraint.
- `uv run python scripts/validate_package.py`:757 document/contract checks passed.
- `git diff --check` passed.
- Document/contracts validation is recorded separately; it is not app accuracy.

## Remaining work on the unchanged goal

1. Bounded discovery for dense pages without dropping continuation conditions.
2. More positive-report visual checks, repeated/ordinary/isolated/rotated markers.
3. Accepted condition interpretation and verified source lineage into the actual
   service flow; numeric consistency currently remains library-only.
4. Service E2E and independent quality evaluation before any readiness claim.
