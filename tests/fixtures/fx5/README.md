FX5's twelve PR1 failures, copied read-only from `/srv/proofops/data/payloads/`.

| File | Run | Failure count |
|---|---|---|
| hynix.json.gz | 6bf883b7-a2f6-4283-9570-bd4b32e1c479 | 6 |
| hyundai.json.gz | 5ae64fa8-7a3a-4b90-a179-373af3188d1b | 4 |
| naver.json.gz | d44a3b5b-428d-4a1d-a5c3-5b65b5896f63 | 2 |

Each gzip JSON retains the failed claims, original graph, graph hash, run ID and
frozen v29d policy/hash. Graphs were reconstructed from manifest-hashed parser
artifacts and saved source receipts, plus the prepared PDF's native figure
projection; their hashes match the saved SC1 inventory and tagging packets.
These are historical source states, not fresh source approvals.

All twelve failures occurred before preliminary dispatch: no preliminary or
element responses exist for them. Tests use those actual input graphs and claims;
the explicit synthetic classification response only tests the validator boundary.
The runtime regression captures dispatch for all twelve; it does not turn the
absence of a saved provider response into a new hold. Seven calls use the
4-block/2000-character fallback and carry `cf5_context_truncated` in their
replica receipts. Five Hynix claims deduplicate identical overlapping refs; the
sixth validates its joined quote against both literal fragments and lineage.
Unknown source authority stays unknown. No grade is fabricated.

`python -m evaluation.fx5_replay --stored <read-only-copy> --output <report.json>`
replays all 327 claims from the three original run directories, checks saved wire
and raw responses, regenerates retrieval packets and replays CF6/SC1 decisions.
The full private server copy and PDFs belong in the FX5 lab output, not Git.
