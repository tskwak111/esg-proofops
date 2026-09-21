"""One-command local competition demo for the developer-A pipeline.

This is a thin, safe wrapper around ``evaluation.local_upstage_pilot`` for the
"show the judges a working local review UI" flow. It performs no model or cloud
calls of its own and adds no new application framework: it only

1. copies an *existing* seeded pilot state directory to a writable demo copy so
   the immutable original (real PDF pipeline output + saved real model receipts)
   is never mutated, and
2. resumes that copy through the pilot's built-in same-origin server, which
   serves the built React UI, authenticates a loopback-only session, and
   exposes the real claims / source / review / report-export endpoints.

The heavy lifting (auth, registry, run replay, export build) is entirely the
existing pilot + API. Analysis stays explicit-invoke behind the existing
cost/consent gates; this wrapper never passes ``--invoke`` and never performs a
paid retry. Blocked domain approvals surface as pending/untagged, never as a
forged grade.

Usage (resume a seeded run and serve the UI on loopback):

    uv run python scripts/submission_demo.py \
        --seed .local/developer-a-service-kakao-2025 \
        --port 8790

The command prints the exact loopback login URL to open in a browser. Stop with
Ctrl+C. Re-running with the same ``--demo-state`` reuses the writable copy when
it holds the same run; to rebuild, pass a new ``--demo-state`` path (the wrapper
never deletes a directory, so it cannot erase a seed or an unrelated path).

Safety: this wrapper never passes ``--invoke`` to the pilot, so a resume/serve
demo makes no model or cloud call and cannot trigger a paid retry. Live model
runs are launched separately by the coordinator, not by this launcher.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Policy flags in pilot.json that the pilot resume guard compares. The wrapper
# only reads them to echo a human-readable summary; the pilot itself restores
# them from the manifest under --resume.
_SUMMARY_KEYS = (
    "model",
    "selected_pages",
    "verify_paragraphs",
    "verify_tables",
    "verify_merged_tables",
    "raster_ocr",
    "live_tagging",
    "live_relations",
)


def _load_manifest(seed: Path) -> dict:
    manifest = seed / "pilot.json"
    if not manifest.is_file():
        raise SystemExit(f"seed has no pilot.json: {manifest}")
    return json.loads(manifest.read_text())


def _assert_disjoint(seed: Path, demo_state: Path) -> None:
    """Refuse any seed/demo-state overlap *before* touching the filesystem.

    Equality, ancestor, or descendant relationships could let a later copy or
    cleanup mutate the immutable seed. We validate up front and never delete an
    existing directory, so the wrapper can never remove an arbitrary path.
    """
    seed = seed.resolve()
    demo_state = demo_state.resolve()
    if seed == demo_state:
        raise SystemExit("--demo-state must differ from --seed to keep the seed immutable")
    if seed in demo_state.parents:
        raise SystemExit("--demo-state must not live inside --seed")
    if demo_state in seed.parents:
        raise SystemExit("--demo-state must not be an ancestor of --seed")


def _prepare_writable(seed: Path, demo_state: Path) -> None:
    """Create the writable copy, or reuse an existing matching demo copy.

    The seed is only ever read. An existing demo-state is reused only when it is
    a pilot state for the *same* run; otherwise the operator must choose a new
    ``--demo-state`` path. The wrapper never deletes a directory.
    """
    _assert_disjoint(seed, demo_state)
    seed_manifest = _load_manifest(seed)
    if demo_state.exists():
        demo_manifest_path = demo_state / "pilot.json"
        if not demo_manifest_path.is_file():
            raise SystemExit(
                f"--demo-state {demo_state} exists but is not a pilot state; "
                "choose a new --demo-state path"
            )
        demo_manifest = json.loads(demo_manifest_path.read_text())
        if demo_manifest.get("run_id") != seed_manifest.get("run_id"):
            raise SystemExit(
                f"--demo-state {demo_state} holds a different run "
                f"({demo_manifest.get('run_id')}); choose a new --demo-state path"
            )
        return
    shutil.copytree(seed, demo_state)
    # Seeds are stored read-only (0o700 dirs, 0o600 files); make the copy writable.
    for path in demo_state.rglob("*"):
        try:
            path.chmod(path.stat().st_mode | 0o200)
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed",
        type=Path,
        required=True,
        help="Existing immutable pilot state directory (contains pilot.json). "
        "It is copied, never mutated.",
    )
    parser.add_argument(
        "--demo-state",
        type=Path,
        default=None,
        help="Writable copy location (default: <seed>-demo alongside the seed).",
    )
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument(
        "--no-serve",
        action="store_true",
        help="Prepare/resume and print run status, but do not start the server.",
    )
    args = parser.parse_args()

    seed = args.seed if args.seed.is_absolute() else (ROOT / args.seed)
    seed = seed.resolve()
    if not seed.is_dir():
        raise SystemExit(f"seed directory not found: {seed}")
    manifest = _load_manifest(seed)

    demo_state = args.demo_state or seed.with_name(seed.name + "-demo")
    demo_state = (demo_state if demo_state.is_absolute() else (ROOT / demo_state)).resolve()
    _prepare_writable(seed, demo_state)

    summary = {key: manifest.get(key) for key in _SUMMARY_KEYS}
    print("== ESG ProofOps submission demo ==", flush=True)
    print(f"seed (immutable): {seed}", flush=True)
    print(f"demo state (writable copy): {demo_state}", flush=True)
    print(f"run_id: {manifest.get('run_id')}", flush=True)
    print(f"pipeline: {json.dumps(summary, ensure_ascii=False)}", flush=True)
    if not manifest.get("live_tagging"):
        print(
            "note: this run is extraction-only; claims show tag_status=untagged "
            "(pending), never a forged grade.",
            flush=True,
        )

    # Delegate to the pilot's resume+serve. --resume reconstructs pdf/year/period
    # and all policy flags from pilot.json. We deliberately never append
    # --invoke, so the demo makes no model or cloud call and cannot trigger a
    # paid retry; the coordinator owns any live run.
    cmd = [
        sys.executable,
        "-m",
        "evaluation.local_upstage_pilot",
        "--resume",
        "--state",
        str(demo_state),
        "--port",
        str(args.port),
    ]
    assert "--invoke" not in cmd, "submission demo must never invoke paid model calls"
    if not args.no_serve:
        cmd.append("--serve")
        print(
            f"Starting loopback server on http://127.0.0.1:{args.port} "
            "(Ctrl+C to stop). The login URL is printed below and saved to "
            f"{demo_state / 'browser.json'}.",
            flush=True,
        )
    else:
        print("Resume-only (no server) requested.", flush=True)

    completed = subprocess.run(cmd, cwd=ROOT, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
