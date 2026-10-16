"""Same retained 8 gold pages + LG 13 pages under the I4 composite policy."""

from proofops.application.analysis_profile import FINALS_I4_POLICY

from evaluation.i1_replay import main

if __name__ == "__main__":
    main(integration_policy=FINALS_I4_POLICY, baseline_dir="perf/I3/stage-A-final")
    import json
    import sys
    from pathlib import Path

    path = Path(sys.argv[sys.argv.index("--output") + 1]) / "measurement.json"
    measured = json.loads(path.read_text())
    measured["selection_wire_projection"] = (
        "Validated historical source selections projected as unchanged literal spans; "
        "no old UUID response is admitted as an I4 short-selector provider response. "
        "The new dispatch wire is validated by focused tests and fresh stage B."
    )
    path.write_text(json.dumps(measured, ensure_ascii=False, indent=2))
