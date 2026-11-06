"""FX6b corpus provenance includes the validator's extracted implementation."""

import json
import sys
from hashlib import sha256

import pytest

from scripts import fx6b_corpus_check as corpus_check

VALIDATOR_FILES = (
    "packages/proofops/application/uploads_security.py",
    "packages/proofops/application/upload_contracts.py",
    "packages/proofops/adapters/upload_security/__init__.py",
    "packages/proofops/adapters/upload_security/strict.py",
)


def write_validator(root, paths=VALIDATOR_FILES):
    for name in paths:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {name}\n")


@pytest.fixture
def corpus_run(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    write_validator(root)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for number in range(50):
        (corpus / f"{number:02}.pdf").write_bytes(b"synthetic corpus input")
    output = tmp_path / "output"
    monkeypatch.setattr(corpus_check, "__file__", str(root / "scripts/fx6b_corpus_check.py"))
    monkeypatch.setattr(sys, "argv", ["fx6b_corpus_check.py", str(corpus), str(output)])
    monkeypatch.setattr(corpus_check, "verify_pdf_file", lambda *args, **kwargs: 1)
    return root, output


def test_manifest_hash_uses_sorted_relative_paths_and_file_hashes(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    write_validator(first)
    write_validator(second, reversed(VALIDATOR_FILES))
    (second / "packages/proofops/adapters/upload_security/README.md").write_text("ignored")
    manifest = [
        (name, sha256(f"# {name}\n".encode()).hexdigest()) for name in sorted(VALIDATOR_FILES)
    ]
    expected = sha256(json.dumps(manifest, separators=(",", ":")).encode()).hexdigest()
    assert corpus_check.implementation_digest(first) == expected
    assert corpus_check.implementation_digest(second) == expected


def test_helper_change_updates_implementation_fingerprint_and_preserves_legacy(corpus_run):
    root, output = corpus_run
    corpus_check.main()
    before = json.loads((output / "corpus-results.json").read_text())
    (root / VALIDATOR_FILES[-1]).write_text("# changed helper only\n")
    corpus_check.main()
    after = json.loads((output / "corpus-results.json").read_text())

    expected_legacy = sha256((root / VALIDATOR_FILES[0]).read_bytes()).hexdigest()
    assert before["validator_sha256"] == after["validator_sha256"] == expected_legacy
    assert before["validator_implementation_sha256"] != after["validator_implementation_sha256"]
    assert after["validator_implementation_sha256"] == corpus_check.implementation_digest(root)
    assert after["counts"] == {"verified": 50}
    assert all(row["original_sha256_unchanged"] for row in after["files"])
    assert (output / "corpus-table.md").is_file()


@pytest.mark.parametrize("change", ["edit", "add", "remove", "rename", "contract"])
def test_implementation_changes_during_run_are_rejected(corpus_run, monkeypatch, change):
    root, output = corpus_run
    helper = root / VALIDATOR_FILES[-1]
    changed = False

    def verify(*args, **kwargs):
        nonlocal changed
        if not changed:
            if change == "edit":
                helper.write_text("# edited during check\n")
            elif change == "add":
                helper.with_name("new_helper.py").write_text("# added during check\n")
            elif change == "remove":
                helper.unlink()
            elif change == "rename":
                helper.rename(helper.with_name("renamed.py"))
            else:
                (root / VALIDATOR_FILES[1]).write_text("# changed contract\n")
            changed = True
        return 1

    monkeypatch.setattr(corpus_check, "verify_pdf_file", verify)
    with pytest.raises(
        AssertionError, match="Validator implementation changed during corpus check"
    ):
        corpus_check.main()
    assert not (output / "corpus-table.md").exists()
