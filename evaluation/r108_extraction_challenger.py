"""Prepare R108 runs from the next control argv, without provider calls.

Use Sprint5 E2E3's new-run-argv.json format. Preserve every control flag except
--state; --extraction-atomic adds only the challenger flag. Paid execution stays
with the budget-fenced E2E controller, using the emitted pilot argv.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from evaluation import local_upstage_pilot as pilot

COMPANIES = ("naver", "kia", "sk", "hyundai", "posco", "samsung")


def build_run_argv(
    control: list[str], state: Path, *, extraction_atomic: bool = False
) -> list[str]:
    if not control or control[0] != "pilot" or control.count("--state") != 1:
        raise ValueError("expected E2E3 pilot argv with exactly one --state")
    if any(flag in control for flag in ("--invoke", "--resume", "--serve", "--serve-worker")):
        raise ValueError("control argv must be a new-run preparation without invocation")
    if "--extraction-atomic" in control:
        raise ValueError("control must keep atomic extraction off")
    if extraction_atomic and "--extraction-source-ids" not in control:
        raise ValueError("atomic challenger requires control --extraction-source-ids")
    if state.exists():
        raise ValueError("challenger/control requires a new state directory")
    argv = list(control)
    argv[argv.index("--state") + 1] = str(state.resolve())
    if extraction_atomic:
        argv.append("--extraction-atomic")
    return argv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-argv", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extraction-atomic", action="store_true")
    parser.add_argument("--prepare", choices=COMPANIES, help="Prepare one company offline")
    args = parser.parse_args(argv)
    controls = json.loads(args.control_argv.read_text())
    if set(controls) != set(COMPANIES):
        parser.error("control argv must contain all six E2E3 companies")
    selected = (args.prepare,) if args.prepare else COMPANIES
    runs: dict[str, dict[str, Any]] = {}
    for company in selected:
        try:
            av = build_run_argv(
                controls[company],
                args.state_root / company,
                extraction_atomic=args.extraction_atomic,
            )
        except ValueError as error:
            parser.error(str(error))
        runs[company] = {
            "argv": av,
            "command": shlex.join(
                [sys.executable, "-m", "evaluation.local_upstage_pilot", *av[1:]]
            ),
            "status": "not_run",
        }
    if args.prepare:
        av = runs[args.prepare]["argv"]
        previous = sys.argv
        try:
            sys.argv = av
            code = pilot.main()
        finally:
            sys.argv = previous
        if code:
            return code
        state = args.state_root / args.prepare
        (state / "create-argv.json").write_text(json.dumps(av, ensure_ascii=False, indent=2) + "\n")
        manifest = json.loads((state / "pilot.json").read_text())
        runs[args.prepare].update(
            status="prepared_no_provider_calls",
            manifest=str(state / "pilot.json"),
            **{
                key: manifest[key]
                for key in ("extraction_profile_name", "extraction_profile", "atomic_policy_sha256")
                if key in manifest
            },
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"runs": runs}, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
