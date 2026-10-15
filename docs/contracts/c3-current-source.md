# C3 current source receipt

`c3_current_source_receipt_v1` uses the main pipeline's v23 claim reader
(`upstage-ocr-page-v21`: FXA visible native prose plus D2 pixel confirmation).
C3 rechecks its exact refs against the original PDF. The main hosted pipeline's
selected-page PDF has a different SHA and physical page numbering; its verified
flags or receipts must not be transplanted onto the original graph.

The wrapper policy hashes its verifier and the complete claim reader policy.
The nested receipt binds tenant, run, PDF SHA, document version, parse manifest,
input graph, page, bbox, raw text hash and codepoint span. Replay recomputes the
receipt with the original bytes and retained OCR collections. Unresolved source
records stop C3 before transport creation. Admission verifies only the selected
spans, leaving parent block quality unchanged.

New source receipts change the graph and packet hashes. The reviewed LG source
fingerprint, Python domain rules, and current authenticated three-response
contract are unchanged. Saved or simulated tagging replies cannot publish.

The `c2_selected_source_receipt_v1` reader and policy bytes remain unchanged;
publication reload dispatches historical receipts to that reader. No public API
or database migration is required. Rollback stops creating the new receipt
schema and retains its reader for already stored results; older deployments
must reject unsupported new receipts rather than reinterpret them.
