#!/usr/bin/env bash
# Integration bundle: no marker filter, including historical pins and slow checks.
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run --frozen pytest "$@"
