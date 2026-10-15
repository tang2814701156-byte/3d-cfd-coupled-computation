#!/usr/bin/env bash
set -euo pipefail
project_path="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
image='cfd-coupling:submission-v1'
expected="$(cat "$project_path/environment/image-id.txt")"
command -v docker >/dev/null || { echo 'Install Docker Engine first.' >&2; exit 1; }
mkdir -p "$project_path/results"
[[ -w "$project_path/results" ]] || { echo 'The current user needs write access to the project results directory.' >&2; exit 1; }
[[ "$(docker info --format '{{.OSType}}')" == linux ]] || { echo 'A running Linux container engine is required.' >&2; exit 1; }
present="$(docker image ls --no-trunc --quiet "$image")"
if [[ "$present" != "$expected" ]]; then
    (cd "$project_path" && sha256sum -c environment/image-archive.sha256)
    docker load --input "$project_path/../02可运行的双向耦合原型/images/cfd-coupling-submission.tar.gz"
    [[ "$(docker image inspect --format '{{.Id}}' "$image")" == "$expected" ]] || { echo 'Image identity mismatch.' >&2; exit 1; }
fi
docker run --rm --platform linux/amd64 --user "$(id -u):$(id -g)" \
    --mount "type=bind,source=$project_path,target=/work" \
    -e HOME=/tmp -e USER=cfd -e CFD_RUN_IN_CONTAINER=1 -e "CFD_IMAGE_REF=$image" -e "CFD_IMAGE_ID=$expected" \
    "$image" python /work/scripts/portable_run.py "$@"
