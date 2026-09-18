# Package validator bootstrap fix

The original recursive JSON/YAML scan traversed installed dependencies and local
runtime data. That would make package validation depend on unrelated tool files
once TASK-000 installed Python/Node packages.

- RED: `python3 -m unittest discover -s tests/unit -p test_package_validation.py`
  failed because malformed example JSON under node_modules and .venv was checked.
- Change: prune generated, dependency, legacy-reference, and runtime directories
  with stdlib os.walk. Continue checking project-owned JSON/YAML.
- GREEN: the same command passed (1 regression test). The test also creates
  malformed contracts/broken.json and confirms the validator still rejects it.
- Scope: document validator only. No application/PDF/model/AWS verification.
