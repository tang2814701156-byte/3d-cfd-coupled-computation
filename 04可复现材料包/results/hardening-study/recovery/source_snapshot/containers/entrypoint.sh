#!/usr/bin/env bash
task_args=("$@")
set --
source /usr/lib/openfoam/openfoam2512/etc/bashrc
set -e
test -n "${WM_PROJECT_DIR:-}"
export LD_LIBRARY_PATH="/opt/cfd:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="/work/src:${PYTHONPATH:-}"
exec "${task_args[@]}"

