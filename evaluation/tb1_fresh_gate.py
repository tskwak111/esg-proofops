"""Run the existing fresh gate with TB1's serial simulation ceiling."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fresh_e2e_gate as gate  # noqa: E402

_prepare = gate.prepare


def prepare(case, base, directory):
    receipt = _prepare(case, base, directory)
    path = directory / "live.json"
    config = json.loads(path.read_text())
    config["llm_max_workers"] = 1
    path.write_text(json.dumps(config))
    return receipt


if __name__ == "__main__":
    gate.prepare = prepare
    raise SystemExit(gate.main())
