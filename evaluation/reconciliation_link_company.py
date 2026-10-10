"""Link an existing company to DART from the trusted local operator console.

Filesystem access to the server database is the authority boundary. This is
not an HTTP endpoint and never accepts a client-supplied company registry.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import UUID

from proofops.adapters.local.claim_store import LocalClaimStore
from proofops.adapters.local.reconciliation_store import LocalReconciliationStore
from proofops.adapters.local.run_store import LocalSQLiteRunStore
from proofops.application.authorization import AuthContext
from proofops.application.registry import Registry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--company-id", type=UUID, required=True)
    parser.add_argument("--corp-code", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    if os.environ.get("APP_ENV", "local") != "local" or not args.database.is_file():
        parser.error("an existing local server database is required")
    registry = Registry.sqlite(args.database)
    try:
        runs = LocalSQLiteRunStore(args.database)
        store = LocalReconciliationStore(
            args.database,
            args.database.parent / "reconciliation",
            run_store=runs,
            claims=LocalClaimStore(runs, None, None),
        )
        auth = AuthContext(
            args.actor,
            str(args.tenant_id),
            "admin",
            frozenset({"viewer", "admin"}),
            "local-operator-company-link",
        )
        result = store.link_company(
            auth, str(args.company_id), args.corp_code, registry=registry, reason=args.reason
        )
        print(json.dumps(result))
        return 0
    except (ValueError, LookupError, OSError) as exc:
        print(json.dumps({"error": getattr(exc, "code", "company_link_rejected")}), file=sys.stderr)
        return 2
    finally:
        registry.close()


if __name__ == "__main__":
    raise SystemExit(main())
