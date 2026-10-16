"""Explicit new-run boundaries for source-local input failures."""

HOSTED_MAX_UPLOAD_BYTES = 150 * 1024 * 1024

POLICY = {
    "profile": "source-local-input-failures-hx5-v1",
    "tables": "invalid-owned-grid-remains-unknown; continue-other-sources",
    "scope_attestation": "unavailable-reader-remains-unresolved; continue-other-spans",
    "integrity": "identity-policy-and-replay-mismatch-fail-closed",
}

TABLE_ERRORS = frozenset(
    {
        "J8_GRID_MISSING",
        "J8_GRID_INVALID",
        "J8_GRID_OVERLAP",
        "J8_CELL_OWNERSHIP_INVALID",
        "J8_CELL_GEOMETRY_INVALID",
        "W9_GRID_INVALID",
        "W9_GRID_TEXT_MISMATCH",
    }
)

RECOVERABLE_SOURCE_CODES = frozenset(
    {
        "BUDGET_EXHAUSTED",
        "SOURCE_ATTESTATION_UNAVAILABLE",
        "SOURCE_ATTESTATION_GEOMETRY_UNSUPPORTED",
        "SOURCE_ATTESTATION_RENDER_LIMIT",
    }
)
