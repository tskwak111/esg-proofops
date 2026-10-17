#!/usr/bin/env python3
"""PC1: plan/apply a mechanical legacy move on the supplied integrated checkout.

Usage: uv run python /path/to/apply_cleanup.py --root . [--apply]
No version names, policy hashes, or hosted admissions are hardcoded. Unknown
source shapes are rejected before writing. Applying runs the byte-equivalence
oracle in fresh processes and restores touched files on any failure.
"""

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

SOURCE = Path("packages/proofops/application/analysis_profile.py")
BASE = SOURCE.parent / "policies"
ORACLE = Path("scripts/pc1_cleanup/equivalence.py")
FIXTURE = Path("tests/fixtures/pc1_policy_equivalence.json")
TEST = Path("tests/unit/test_pc1_policy_equivalence.py")
MARKER = "PC1: mechanically extracted legacy policies"
TEST_SOURCE = '''"""Every baseline policy, pin, hosted admission and public API stays unchanged."""

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
'''


def require(condition, message):
    if not condition:
        raise ValueError(message)


def is_assignment(node, name):
    return (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == name
    )


def is_v2(node):
    return ast.dump(node) == ast.dump(ast.parse("profile == V2_PROFILE", mode="eval").body)


def tuple_entries(node, previous=None):
    require(isinstance(node, ast.Tuple), "Registry must remain an explicit tuple")
    entries = list(node.elts)
    if previous is not None:
        require(
            entries
            and isinstance(entries[0], ast.Starred)
            and isinstance(entries[0].value, ast.Name)
            and entries[0].value.id == previous,
            "Unexpected registry append",
        )
        entries.pop(0)
    for entry in entries:
        value = entry.value if isinstance(entry, ast.Starred) else entry
        require(isinstance(value, ast.Name), "Registry entries must be names or starred names")
    return entries


def names_defined(nodes):
    names = set()
    for node in nodes:
        if isinstance(node, ast.ImportFrom):
            require(node.level == 0, "Relative prefix imports need manual review")
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.Assign):
            require(
                all(isinstance(target, ast.Name) for target in node.targets),
                "Only simple top-level assignments are supported",
            )
            names.update(target.id for target in node.targets)
        else:
            require(
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str),
                "Unexpected prefix statement",
            )
    return names


def plan(source):
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    require(
        set(functions)
        == {
            "policy_for",
            "publication_policy_for",
            "apply_pilot_profile",
            "certification_profile_for",
        },
        "Public API changed; review oracle",
    )
    first = functions["policy_for"]
    require(
        all(isinstance(node, ast.FunctionDef) for node in tree.body if node.lineno >= first.lineno),
        "Definitions after the API need manual review",
    )
    prefix = [node for node in tree.body if node.lineno < first.lineno]
    defaults = [node for node in prefix if is_assignment(node, "V2_POLICY")]
    require(
        defaults and isinstance(defaults[-1].value, ast.Name),
        "Final V2_POLICY must alias a named policy",
    )
    current_name = defaults[-1].value.id
    current = [node for node in prefix if is_assignment(node, current_name)]
    require(len(current) == 1, "Current policy must have one top-level definition")
    boundary = current[0].lineno
    lines = source.splitlines(keepends=True)
    while boundary > 1 and (
        not lines[boundary - 2].strip() or lines[boundary - 2].lstrip().startswith("#")
    ):
        boundary -= 1
    legacy_nodes = [node for node in prefix if node.lineno < boundary]
    current_nodes = [node for node in prefix if node.lineno >= boundary]
    legacy_names = names_defined(legacy_nodes)
    current_names = names_defined(current_nodes)
    require(
        not any(
            isinstance(node, ast.Name) and node.id in {"__file__", "__name__"}
            for item in prefix
            for node in ast.walk(item)
        ),
        "Location-sensitive policy",
    )

    replay = functions["policy_for"]
    branches = [
        node
        for node in ast.walk(replay)
        if isinstance(node, ast.If)
        and is_v2(node.test)
        and node.body
        and is_assignment(node.body[0], "choices")
    ]
    branches.sort(key=lambda node: node.lineno)
    for branch in branches:
        require(
            isinstance(branch.body[0].value, ast.Tuple) and branch.body[0].value.elts,
            "Unexpected V2 replay tuple",
        )
    initial = [node for node in branches if not isinstance(node.body[0].value.elts[0], ast.Starred)]
    require(len(initial) == 1 and len(initial[0].body) == 1, "Unexpected V2 replay branch")
    initial_assignment = initial[0].body[0]
    replay_entries = tuple_entries(initial_assignment.value)
    require(ast.unparse(replay_entries[0]) == "V2_POLICY", "V2 default must stay first")
    replacements = []
    for branch in branches:
        if branch is initial[0]:
            continue
        for node in branch.body:
            require(is_assignment(node, "choices"), "Unexpected replay append body")
            replay_entries.extend(tuple_entries(node.value, "choices"))
        replacements.append((branch.lineno, branch.end_lineno, ""))

    publication = functions["publication_policy_for"]
    allowed = [node for node in publication.body if is_assignment(node, "allowed")]
    require(
        len(allowed) == 1
        and isinstance(allowed[0].value, ast.IfExp)
        and is_v2(allowed[0].value.test),
        "Unexpected hosted allowlist",
    )
    hosted_tuple = allowed[0].value.body
    require(
        isinstance(hosted_tuple, ast.Tuple)
        and ast.unparse(hosted_tuple.elts[0]) == "policy_for(profile)",
        "Hosted default must be selected by policy_for",
    )
    require(
        ast.unparse(allowed[0].value.orelse) == "(policy_for(profile),)",
        "Non-V2 hosted behavior changed",
    )
    hosted_entries = tuple_entries(
        ast.Tuple(elts=[ast.Name(id="V2_POLICY"), *hosted_tuple.elts[1:]])
    )
    for branch in publication.body:
        if not isinstance(branch, ast.If) or not is_v2(branch.test):
            continue
        require(not branch.orelse, "Unexpected hosted append else")
        for node in branch.body:
            require(is_assignment(node, "allowed"), "Unexpected hosted append body")
            hosted_entries.extend(tuple_entries(node.value, "allowed"))
        replacements.append((branch.lineno, branch.end_lineno, ""))
    hosted = {ast.unparse(entry) for entry in hosted_entries}
    require(
        hosted <= {ast.unparse(entry) for entry in replay_entries},
        "Hosted registry contains entries outside replay",
    )
    entry_names = {ast.unparse(entry).lstrip("*") for entry in replay_entries}
    require(entry_names <= legacy_names | current_names, "Unbound registry entry")
    parameters = sorted(entry_names & current_names)
    call = "_v2_policy_registry(" + ", ".join(parameters) + ")"
    replacements.extend(
        [
            (
                initial_assignment.lineno,
                initial_assignment.end_lineno,
                "        choices = tuple(policy for policy, _ in " + call + ")\n",
            ),
            (
                allowed[0].lineno,
                allowed[0].end_lineno,
                "    allowed = (\n        tuple(policy for policy, hosted in "
                + call
                + " if hosted)\n"
                "        if profile == V2_PROFILE else (policy_for(profile),)\n    )\n",
            ),
        ]
    )
    for start, end, replacement in sorted(replacements, reverse=True):
        lines[start - 1 : end] = [replacement]
    api = "".join(lines[first.lineno - 1 :])
    # Edits above first.lineno are forbidden, so its original offset stays valid.
    original_lines = source.splitlines(keepends=True)
    legacy = "".join(original_lines[: boundary - 1])
    current_source = "".join(original_lines[boundary - 1 : first.lineno - 1])
    needed = {
        node.id
        for item in [*current_nodes, *functions.values()]
        for node in ast.walk(item)
        if isinstance(node, ast.Name)
    }
    public_legacy = sorted(
        name for name in legacy_names if not name.startswith("_") or name in needed
    )
    reexports = "\n".join(f"{name} = _legacy.{name}" for name in public_legacy)
    facade = (
        '"""Current default, one policy registry, and compatible public entry points.\n\n'
        + MARKER
        + '. Historical definitions are re-exported explicitly.\n"""\n\n'
        + "from proofops.application.policies.legacy import analysis_profiles as _legacy\n"
        + "from proofops.application.policies.registry import (\n"
        + "    v2_policy_registry as _v2_policy_registry,\n)\n\n"
        + "# Explicit aliases preserve historical imports and object identity.\n"
        + reexports
        + "\n\n"
        + current_source
        + api
    )
    registry = [
        '"""Replay order and hosted admission share one explicit registry."""\n\n',
        "from proofops.application.policies.legacy import analysis_profiles as _legacy\n\n\n",
        "def v2_policy_registry(" + ", ".join(parameters) + "):\n",
        '    """Return original policy objects; the caller supplies its current default."""\n',
        "    return (\n",
    ]
    for entry in replay_entries:
        name = ast.unparse(entry).lstrip("*")
        ref = name if name in parameters else "_legacy." + name
        flag = ast.unparse(entry) in hosted
        registry.append(
            f"        *((policy, {flag}) for policy in {ref}),\n"
            if isinstance(entry, ast.Starred)
            else f"        ({ref}, {flag}),\n"
        )
    registry.append("    )\n")
    # Original imports are part of the public compatibility surface even when
    # the relocated definitions no longer use them locally.
    legacy += "\n__all__ = " + repr(sorted(legacy_names)) + "\n"
    outputs = {
        SOURCE: facade,
        BASE / "__init__.py": '"""Analysis policy definitions and replay registration."""\n',
        BASE
        / "legacy/__init__.py": '"""Historical and experimental policies retained for replay."""\n',
        BASE / "legacy/analysis_profiles.py": legacy,
        BASE / "registry.py": "".join(registry),
    }
    for value in outputs.values():
        ast.parse(value)
    return outputs


def observe(root):
    # Source checkout wins over editable installs pointing at another worktree.
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "packages") + os.pathsep + str(root)
    result = subprocess.run(
        [sys.executable, "-m", "scripts.pc1_cleanup.equivalence"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def apply(root, write):
    path = root / SOURCE
    source = path.read_text()
    if MARKER in source:
        baseline = json.loads((root / FIXTURE).read_text())
        require(observe(root) == baseline["snapshot"], "Existing cleanup drifted from its baseline")
        print("already_applied: equivalence passed; no files changed")
        return
    outputs = plan(source)
    for relative in outputs:
        require(
            relative == SOURCE or not (root / relative).exists(),
            f"Refusing to overwrite existing output: {relative}",
        )
    print(
        json.dumps(
            {
                "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                "files": [str(relative) for relative in outputs],
            },
            indent=2,
        )
    )
    if not write:
        return
    generated = set(outputs)
    outputs[ORACLE] = Path(__file__).with_name("equivalence.py").read_text()
    outputs[ORACLE.parent / "__init__.py"] = (
        '"""Reproducible, offline PC1 policy cleanup tooling."""\n'
    )
    outputs[TEST] = TEST_SOURCE
    for relative, content in outputs.items():
        if relative not in generated:
            require(
                not (root / relative).exists() or (root / relative).read_text() == content,
                f"Refusing to overwrite different support file: {relative}",
            )
    require(not (root / FIXTURE).exists(), "Refusing to replace an existing baseline")
    backups = {
        relative: (root / relative).read_bytes() if (root / relative).exists() else None
        for relative in [*outputs, FIXTURE]
    }
    written = set()
    try:
        for relative in (ORACLE, ORACLE.parent / "__init__.py"):
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            (root / relative).write_text(outputs[relative])
            written.add(relative)
        before = observe(root)
        require(path.read_text() == source, "Source changed concurrently; retry after integration")
        for relative, content in outputs.items():
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            (root / relative).write_text(content)
            written.add(relative)
        subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--select", "I", "--fix", *map(str, outputs)],
            cwd=root,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [sys.executable, "-m", "ruff", "format", *map(str, outputs)],
            cwd=root,
            check=True,
            capture_output=True,
        )
        after = observe(root)
        require(before == after, "Policy/API equivalence failed; restoring original files")
        metadata = {
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "snapshot": before,
        }
        written.add(FIXTURE)
        (root / FIXTURE).write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
        print(
            f"equivalence passed: {len(before['policy_hashes'])} policy hashes; "
            f"{len(before['lookups'])} profile cases; {len(before['pilot'])} CLI cases"
        )
    except BaseException:
        for relative in written:
            content = backups[relative]
            target = root / relative
            if content is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(content)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Apply and verify; default only plans")
    args = parser.parse_args()
    apply(args.root.resolve(), args.apply)


if __name__ == "__main__":
    main()
