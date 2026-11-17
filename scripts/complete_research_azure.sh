#!/usr/bin/env bash
# Evaluate the active Azure artifacts in a separate container. Do not restart
# or alter the running API. The deployed runtime supplies the model code.
set -euo pipefail
project="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
key="${BEATX_AZURE_KEY:-$HOME/.ssh/beatx-api_key.pem}"
target="${BEATX_AZURE_SSH:-azureuser@beatx-api-keshav.centralindia.cloudapp.azure.com}"
test -r "$key" || { echo "The existing Azure SSH key is needed at $key." >&2; exit 1; }
ssh_cmd=(ssh -i "$key" -o IdentitiesOnly=yes -o ConnectTimeout=10 "$target")
stage="$("${ssh_cmd[@]}" 'mktemp -d "$HOME/beatx-research.XXXXXXXX"')"
[[ "$stage" =~ ^/home/azureuser/beatx-research\.[a-zA-Z0-9]+$ ]] || { echo 'Unexpected staging path.' >&2; exit 1; }
cd "$project"
# Deliberately exclude local src and serving modules. The image running the
# live API supplies those modules, so inference uses that exact implementation.
tar -czf - \
  scripts/complete_research.py scripts/research_eda.py scripts/download_pilot.py \
  scripts/seed_study.py scripts/export_research_additions.py scripts/export_research_bundle.py \
  docs | "${ssh_cmd[@]}" "tar -xzf - -C '$stage'"
"${ssh_cmd[@]}" bash -s -- "$stage" <<'REMOTE'
set -euo pipefail
stage=$1
docker_cmd=(docker)
if ! docker inspect beatx-api >/dev/null 2>&1; then docker_cmd=(sudo -n docker); fi
image="$("${docker_cmd[@]}" inspect --format '{{.Image}}' beatx-api)"
data="$("${docker_cmd[@]}" inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' beatx-api)"
[[ "$data" == "$HOME/beatx-data" ]] || { echo 'Unexpected live data mount.' >&2; exit 1; }
model_id="$(curl -fsS --max-time 20 http://127.0.0.1:8080/api/status | python3 -c 'import json,sys; print(json.load(sys.stdin)["model_id"])')"
# One separate worker and no outbound network. /data is read-only.
"${docker_cmd[@]}" run --rm --network none --cpus=1 \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$data,target=/data,readonly" \
  --mount "type=bind,source=$stage,target=/work" \
  --workdir /work -e PYTHONPATH=/app/src:/app:/work \
  -e OPENBLAS_NUM_THREADS=1 -e OMP_NUM_THREADS=1 \
  "$image" python -m scripts.complete_research \
    --data /data --model /data/model --profiles /data/profiles-v2-expanded \
    --expected-model-id "$model_id" --output /work/runs/research-completion
echo "Private evaluation retained at $stage/runs/research-completion"
REMOTE
# Retrieve only public aggregates. Raw playlists and per-query records stay private.
for name in studio_evaluation.json eda_full.json; do
  scp -i "$key" -o IdentitiesOnly=yes "$target:$stage/docs/data/research/$name" "docs/data/research/$name"
done
python3 -m scripts.export_research_additions
python3 scripts/export_research_bundle.py
echo 'Measured reports are ready in docs/data/research. Review and commit these generated files.'
