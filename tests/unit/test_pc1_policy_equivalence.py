"""Every baseline policy, pin, hosted admission and public API stays unchanged."""

import json
from pathlib import Path

from scripts.pc1_cleanup.equivalence import snapshot


def test_pc1_policy_equivalence():
    path = Path(__file__).parents[1] / "fixtures" / "pc1_policy_equivalence.json"
    baseline = json.loads(path.read_text())
    actual = snapshot()
    assert actual.keys() == baseline["snapshot"].keys()
    for section, expected in baseline["snapshot"].items():
        assert actual[section] == expected, section
