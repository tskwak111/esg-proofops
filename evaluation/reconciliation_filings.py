"""Discover annual DART receipts or explicitly pin one into a new immutable snapshot.

Network listing requires --allow-network and DART_API_KEY in the environment.
The pin command is offline and never loads credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from proofops.adapters.dart.client import DartClient
from proofops.adapters.dart.filings import list_annual_filings, pin_filing, write_filings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--corp-code", required=True)
    listing.add_argument("--bgn-de", required=True)
    listing.add_argument("--as-of", required=True)
    listing.add_argument("--page-count", type=int, default=100)
    listing.add_argument("--max-pages", type=int, default=100)
    listing.add_argument("--allow-network", action="store_true")
    listing.add_argument("--output", type=Path, required=True)
    pin = commands.add_parser("pin")
    pin.add_argument("--input", type=Path, required=True)
    pin.add_argument("--rcept-no", required=True)
    pin.add_argument("--operator", required=True)
    pin.add_argument("--pinned-at", required=True, help="ISO timestamp with timezone")
    pin.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise ValueError("output_exists")
        if args.command == "list":
            if not args.allow_network or not os.environ.get("DART_API_KEY", "").strip():
                raise ValueError("explicit_network_permission_and_key_required")
            result = list_annual_filings(
                DartClient(),
                corp_code=args.corp_code,
                bgn_de=args.bgn_de,
                as_of=args.as_of,
                page_count=args.page_count,
                max_pages=args.max_pages,
            )
        else:
            result = pin_filing(
                json.loads(args.input.read_text(encoding="utf-8")),
                rcept_no=args.rcept_no,
                operator=args.operator,
                pinned_at=args.pinned_at,
            )
        write_filings(args.output, result)
        return 3 if result["status"] == "blocked" else 0
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        print(json.dumps({"error": "filings_input_or_output_rejected"}), file=sys.stderr)
        return 2
    except Exception:
        print(json.dumps({"error": "filings_failed"}), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
