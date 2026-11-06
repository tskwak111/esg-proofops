"""Every baseline policy, pin, hosted admission and public API stays unchanged."""

import json
from pathlib import Path

import pytest

from scripts.pc1_cleanup.equivalence import runtime_ast_dump, runtime_signature, snapshot


def test_pc1_policy_equivalence():
    path = Path(__file__).parents[1] / "fixtures" / "pc1_policy_equivalence.json"
    baseline = json.loads(path.read_text())
    actual = snapshot()
    assert actual.keys() == baseline["snapshot"].keys()
    for section, expected in baseline["snapshot"].items():
        assert actual[section] == expected, section


def test_runtime_signature_preserves_parameter_contract():
    def typed(
        value: int, /, optional: str = "x", *args: int, flag: bool = False, **kwargs: str
    ) -> int:
        return value

    assert runtime_signature(typed) == "(value, /, optional='x', *args, flag=False, **kwargs)"


@pytest.mark.parametrize("prefix", ("def", "async def"))
def test_runtime_ast_ignores_only_annotations(prefix):
    typed = f"""{prefix} sample(value: int, /, optional: str = "x", *, flag: bool = False) -> int:
    pending: list[str]
    result: int = value + 1
    return result
"""
    plain = f"""{prefix} sample(value, /, optional="x", *, flag=False):
    result = value + 1
    return result
"""
    assert runtime_ast_dump(typed) == runtime_ast_dump(plain)


@pytest.mark.parametrize(
    "changed",
    (
        "def sample(renamed, /, *, flag=False):\n    return value + 1",
        "def sample(value, *, flag=False):\n    return value + 1",
        "def sample(value, /, *, flag=True):\n    return value + 1",
        "def sample(value, /, *, flag=False):\n    return value + 2",
        "def sample(value, /, *, flag=False):\n    return cast(int, value + 1)",
        "@decorator\ndef sample(value, /, *, flag=False):\n    return value + 1",
    ),
)
def test_runtime_ast_keeps_api_and_execution_changes(changed):
    original = "def sample(value, /, *, flag=False):\n    return value + 1"
    assert runtime_ast_dump(original) != runtime_ast_dump(changed)
