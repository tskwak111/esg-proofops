"""K3 worker admission shares W9's exact grid candidates; never an evidence gate."""

from proofops.application.ingest.w9_tables import POLICY as W9_POLICY

POLICY = dict(
    profile="w9-worker-routing-k3-v1",
    w9_policy=W9_POLICY,
    candidate="same-graph-owned-table-observations-or-cell-entries",
    source="no-source-promotion; existing-source-and-budget-fences",
)
