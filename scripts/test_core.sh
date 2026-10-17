#!/usr/bin/env bash
# Development bundle. The full suite remains the integration gate.
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run --frozen pytest -m 'not legacy_pin and not slow' "$@"
