"""Explicit operator installation of source-derived project rules for the local report bridge."""

import argparse
import json
import time
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from proofops.adapters.local.rulepack_store import RulePackSqliteStore
from proofops.application.rulepacks import RulePackRecord
from proofops.domain.rulepacks import snapshot_from_validated

from scripts.review_rulepack import promote_and_review_pack

ROOT = Path(__file__).resolve().parents[1]


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--apply", action="store_true")
    cli.add_argument("--reviewer", required=True)
    cli.add_argument("--authority", required=True)
    args = cli.parse_args()
    draft = json.loads((ROOT / "api/rulepack.json").read_text(encoding="utf-8"))
    print(
        json.dumps(
            dict(
                source_hash=draft["source_document_sha256"],
                rules_hash=draft["sha256"],
                unresolved=draft["unresolved_gap_ids"],
            )
        )
    )
    if not args.apply:
        return
    if not args.reviewer.strip() or not args.authority.strip():
        raise ValueError("EXPLICIT_AUTHORITY_REQUIRED")
    directory = ROOT / ".local/analysis-policy"
    directory.mkdir(parents=True, exist_ok=True)
    store = RulePackSqliteStore(str(directory / "state.sqlite3"))
    registry = {}
    # The canonical NAVER snapshot and newly uploaded reports use these two local tenants.
    for tenant in {
        str(uuid5(NAMESPACE_URL, "parser-lab-web")),
        "8c24a809-8535-54fc-89ed-9abcee98dab6",
    }:
        record = {**draft, "tenant_id": tenant, "rule_pack_id": str(uuid4())}
        files = {path: json.loads(raw) for path, raw in record.pop("content")}
        active = promote_and_review_pack(
            store,
            tenant_id=tenant,
            draft_pack=RulePackRecord.from_dict(record),
            files=files,
            reviewer=args.reviewer,
            reviewed_at=datetime.now(UTC).isoformat(),
            source_authority=args.authority,
            note="Activate unchanged explicit project ladders for report analysis. "
            "No claim approval, expert gold, legal validation or new gap interpretation.",
            now=time.time(),
        )
        stored, content = store.get_pack_with_files(tenant, active)
        pack = snapshot_from_validated(stored.to_dict(), content)
        raw = json.dumps(asdict(pack), ensure_ascii=False, indent=2).encode("utf-8")
        path = directory / f"{active}.json"
        path.write_bytes(raw)
        registry[tenant] = dict(file=path.name, sha256=sha256(raw).hexdigest())
    (directory / "registry.json").write_text(json.dumps(registry, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
