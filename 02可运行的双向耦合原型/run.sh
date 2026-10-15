#!/usr/bin/env bash
set -euo pipefail
prototype_path="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$prototype_path/../04可复现材料包/run.sh" "$@"
