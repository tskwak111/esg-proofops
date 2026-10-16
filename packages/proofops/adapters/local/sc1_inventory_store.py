"""Run-scoped immutable SC1 inventory provider, shared by tagging and QT2."""

import fcntl
import json
from pathlib import Path

from proofops.application.tagging.element_inventory import build_inventory, replay_inventory
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json


class SC1InventoryProvider:
    """Explicit transport injection; no default model, network client or credentials.

    Repeated claims/restarts read the same artifact. A new graph, scope, model or
    policy creates a different artifact; existing revisions are never overwritten.
    """

    def __init__(self, path, *, model_sha256, invoke, build=build_inventory):
        self.build = build
        self.path = Path(path)
        self.model_sha256, self.invoke = model_sha256, invoke

    def __call__(self, graph, selection):
        identity = canonical_hash(dict(selection=selection, model_sha256=self.model_sha256))
        directory = self.path / selection["tenant_id"] / selection["run_id"]
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / (identity + ".json")
        with (directory / (identity + ".lock")).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if target.exists():
                result = json.loads(target.read_text())
                if result["selection"] != selection or result["model_sha256"] != self.model_sha256:
                    raise ValueError("SC1_IMMUTABLE_INVENTORY_MISMATCH")
                return replay_inventory(result, graph)
            result = self.build(
                graph, selection, model_sha256=self.model_sha256, invoke=self.invoke
            )
            # Exclusive creation prevents overwrites even by a non-cooperating writer.
            with target.open("x") as output:
                output.write(canonical_json(result))
            return result
