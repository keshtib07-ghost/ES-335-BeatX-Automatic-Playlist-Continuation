#!/usr/bin/env bash
# Measure the existing deployed pipeline in a separate read-only worker.
set -euo pipefail
project="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
key="${BEATX_AZURE_KEY:-$HOME/.ssh/beatx-api_key.pem}"
target="${BEATX_AZURE_SSH:-azureuser@beatx-api-keshav.centralindia.cloudapp.azure.com}"
test -r "$key" || { echo "The existing Azure SSH key is needed at $key." >&2; exit 1; }
ssh_cmd=(ssh -i "$key" -o IdentitiesOnly=yes -o ConnectTimeout=10 "$target")
stage="$("${ssh_cmd[@]}" 'mktemp -d "$HOME/beatx-seeds.XXXXXXXX"')"
[[ "$stage" =~ ^/home/azureuser/beatx-seeds\.[a-zA-Z0-9]+$ ]] || { echo 'Unexpected staging path.' >&2; exit 1; }
cd "$project"
tar -czf - scripts/studio_seed_study.py scripts/complete_research.py scripts/seed_study.py \
  scripts/export_research_additions.py scripts/export_research_bundle.py docs | \
  "${ssh_cmd[@]}" "tar -xzf - -C '$stage'"
"${ssh_cmd[@]}" bash -s -- "$stage" <<'REMOTE'
set -euo pipefail
stage=$1
docker_cmd=(docker)
if ! docker inspect beatx-api >/dev/null 2>&1; then docker_cmd=(sudo -n docker); fi
image="$("${docker_cmd[@]}" inspect --format '{{.Image}}' beatx-api)"
data="$("${docker_cmd[@]}" inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' beatx-api)"
[[ "$data" == "$HOME/beatx-data" ]] || { echo 'Unexpected live data mount.' >&2; exit 1; }
model_id="$(curl -fsS --max-time 20 http://127.0.0.1:8080/api/status | python3 -c 'import json,sys; print(json.load(sys.stdin)["model_id"])')"
echo "Private checkpoints stay in $stage/runs/final-seed-study"
"${docker_cmd[@]}" run --rm --network none --cpus=1 --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$data,target=/data,readonly" \
  --mount "type=bind,source=$stage,target=/work" --workdir /work \
  -e PYTHONPATH=/work:/app/src:/app -e OPENBLAS_NUM_THREADS=1 -e OMP_NUM_THREADS=1 \
  "$image" python -m scripts.studio_seed_study --data /data --model /data/model \
    --profiles /data/profiles-v2-expanded --expected-model-id "$model_id" \
    --output /work/runs/final-seed-study
REMOTE
scp -i "$key" -o IdentitiesOnly=yes "$target:$stage/docs/data/research/studio_seed_study.json" \
  docs/data/research/studio_seed_study.json
PYTHONPATH=src python3 -m scripts.studio_seed_study --export-only --output docs/data/research
echo 'Final-pipeline seed results are ready. Commit the generated docs files to publish them.'
