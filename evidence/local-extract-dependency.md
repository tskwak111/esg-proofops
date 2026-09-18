# Existing workspace extraction dependency

The explicit local extraction worker imports SyntheticClaimExtractor from the existing proofops-agent workspace package. proofops-worker now declares that package so an isolated installation cannot silently rely on the development workspace having it installed.

No external library was added; existing repository licensing and redistribution gates apply to both internal packages. `uv lock --offline` resolved the same 73 packages; the only lock change adds the internal worker-to-agent edge. `uv build --offline --package proofops-worker` and `uv build --offline --package proofops-agent` both created wheel and source archives. Actual extraction behavior is verified separately in evidence/local-extract-runner.md. This is not live model/cloud evidence.
