# TASK-003 local parser runtime preparation

Reviewed 2026-09-09 KST. docs/27 pins OpenDataLoader PDF 2.5.7 and Java 21.
The existing executable was Java 25; an isolated Homebrew Java 21 keg was added.
No shell startup file, global Java link or system-library symlink was changed.

`brew info --json=v2 openjdk@21` reports version 21.0.12.1,
`GPL-2.0-only WITH Classpath-exception-2.0`, and the arm64 Tahoe bottle SHA-256
`b4f233ded4853f0196312ed48cf4a2608b3b8d9174921b728ba84d8c60acf37d`.
`HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_CLEANUP=1 brew install openjdk@21`
exited 0 and added one formula. The absolute command
`/opt/homebrew/opt/openjdk@21/bin/java -version` confirms 21.0.12.1.
This is a local development runtime; deployed image digest and JVM inventory
remain separate release evidence.

Official [PyPI metadata](https://pypi.org/pypi/opendataloader-pdf/2.5.7/json)
identifies Apache-2.0, Python >=3.10 and no base Python dependencies.
The [tagged README](https://github.com/opendataloader-project/opendataloader-pdf/blob/v2.5.7/README.md)
is the specified upstream reference. The installed distribution includes bundled
JAR and third-party notices; its inventory includes CDDL-1.1 components. Preserve
those notices in deployed artifacts and review the actual image inventory at
release; the package-level license is not a claim that every bundled file has it.

`uv add --package proofops --optional parsing 'opendataloader-pdf==2.5.7'`
exited 0; 64 packages resolved. No hybrid/OCR/model dependency was installed.
The lock/SBOM was refreshed, and the strict exported-requirements pip-audit
exited 0 with no known vulnerabilities found. This audit covers Python lock
packages, not every bundled Java component.

An actual temporary pypdf-generated blank PDF was passed through the installed
`opendataloader_pdf.convert(input_path=[...], output_dir=..., format="json,markdown", quiet=True)`
in a subprocess with a 45-second timeout and Java 21 selected only in that
subprocess's PATH. It exited 0 and produced `synthetic.json` and `synthetic.md`.
JSON parsing succeeded; keys include `number of pages` and `kids`. Temporary
input/output were removed. This establishes local invocation only, not extraction
accuracy or the TASK-003 adapter/manifest behavior. No hybrid, product model,
customer PDF, cloud operation or benchmark was run.

Installed `convert_generated.py` exposes a real `pages` string argument, and
`runner.py` captures Java output but has no process timeout. TASK-003 must verify
physical-page mapping in actual output and bound the process itself; it need not
invent an SDK argument or assume that SDK logging is safe for source material.
