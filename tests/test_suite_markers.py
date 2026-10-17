"""Keep the explicit bundle catalog reviewable and its safety inventory in core."""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads(Path(__file__).with_name("suite_markers.json").read_text())


def test_suite_selectors_resolve_to_existing_tests():
    selectors = set(CATALOG["legacy_pin"]) | set(CATALOG["slow"])
    selectors.update(s for group in CATALOG["core_safety"].values() for s in group)
    for selector in selectors:
        path, *names = selector.split("::")
        source = ROOT / path
        assert source.is_file(), selector
        if names:
            tree = ast.parse(source.read_text())
            assert names == [names[0]] and any(
                isinstance(node, ast.FunctionDef) and node.name == names[0] for node in tree.body
            ), selector


def test_safety_inventory_has_no_excluded_selector():
    excluded = set(CATALOG["legacy_pin"]) | set(CATALOG["slow"])
    for group in CATALOG["core_safety"].values():
        assert group
        for selector in group:
            assert selector not in excluded
            assert selector.split("::")[0] not in excluded
            if "::" not in selector:
                assert not any(s.startswith(selector + "::") for s in excluded)


def test_current_default_and_gate_regressions_remain_in_core():
    protected = {s for group in CATALOG["core_safety"].values() for s in group}
    assert {
        "tests/integration/test_i31_profile.py",
        "tests/test_fresh_e2e_gate.py",
        "tests/test_hosted_rc1.py",
        "tests/integration/test_hf1_openai_wire.py",
    } <= protected
