#!/usr/bin/env bash
set -euo pipefail

project="${BEATX_PROJECT_DIR:-$HOME/projects/playlist-model}"
key="${BEATX_AZURE_KEY:-$HOME/.ssh/beatx-api_key.pem}"
ssh_target="${BEATX_AZURE_SSH:-azureuser@beatx-api-keshav.centralindia.cloudapp.azure.com}"
azure_api=https://beatx-api-keshav.centralindia.cloudapp.azure.com
page_origin=https://keshtib07-ghost.github.io
ssh_cmd=(ssh -i "$key" -o IdentitiesOnly=yes -o ConnectTimeout=10 "$ssh_target")

cd "$project/runs/million"
model=model-full-titles
profiles=profiles-v2-expanded-full-titles
files=(
  "$model"/{tags,frozen_settings.json,validation_metrics.json,test_metrics.json}
  "$profiles"/{tags,tag_report.json,tag_coverage.csv,title_tag_review.csv}
)
test -r "$key" || { echo "SSH key unavailable at $key" >&2; exit 1; }
for file in "${files[@]}"; do
  test -r "$file" || { echo "Training artifact unavailable at $file" >&2; exit 1; }
done
expected="$(sha256sum "$model/frozen_settings.json" | cut -d ' ' -f 1)"
stage="$("${ssh_cmd[@]}" 'set -eu; cd "$HOME/beatx-data"; mktemp -d .full-titles.XXXXXXXX')"
if [[ ! "$stage" =~ ^\.full-titles\.[a-zA-Z0-9]+$ ]]; then
  echo 'Azure returned an unexpected staging directory.' >&2
  exit 1
fi

echo "Uploading the full-title artifacts to Azure."
tar -czf - -- "${files[@]}" | "${ssh_cmd[@]}" 'cd "$HOME/beatx-data" && tar -xzf - -C '"$stage"

"${ssh_cmd[@]}" bash -s -- "$stage" "$expected" <<'REMOTE'
set -euo pipefail
expected=$2
data="$HOME/beatx-data"
stage="$data/$1"
container=beatx-api
candidate="$stage/model-full-titles"
new_tags="$stage/profiles-v2-expanded-full-titles"
profile_name=profiles-v2-expanded
profile_candidate="$stage/$profile_name"
internal_api=http://127.0.0.1:8080
tag_files=(summary.json title_tagger.joblib track_tag_votes.npy track_axis_totals.npy tag_priors.npy)

exec 9>"$data/.model-deploy.lock"
flock -x 9
mount="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' "$container")"
if [[ "$mount" != "$data" ]]; then
  echo "Unexpected model mount: $mount" >&2
  exit 1
fi

for name in "${tag_files[@]}"; do
  test -s "$candidate/tags/$name"
  test -s "$new_tags/tags/$name"
done
python3 - "$data" "$stage" "$expected" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

data, stage = map(Path, sys.argv[1:3])
expected = sys.argv[3]
model = stage / "model-full-titles"
profiles = stage / "profiles-v2-expanded-full-titles"

def read(path):
    return json.loads(path.read_bytes())

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def require(condition, message):
    if not condition:
        raise SystemExit(message)

frozen = read(model / "frozen_settings.json")
test = read(model / "test_metrics.json")
require(digest(model / "frozen_settings.json") == expected == test["freeze_sha256"],
        "The transferred frozen settings do not match the completed test.")
require(frozen["training_summary_sha256"] == {
    "index": digest(data / "model/index/summary.json"),
    "tags": digest(model / "tags/summary.json"),
}, "The new title fit does not match the existing collaborative index.")

for directory, active in ((model, data / "model"), (profiles, data / "profiles-v2-expanded")):
    summary = read(directory / "tags/summary.json")
    old = read(active / "tags/summary.json")
    require(summary["classifier_training_titles"] == 804485
            and summary["train_playlists_scored_for_song_tags"] == 804485,
            f"{directory.name} does not contain the full-title fit.")
    require(summary["identity"]["split"] == frozen["identity"]["split"] == old["identity"]["split"],
            f"{directory.name} has a mismatched dataset split.")
    for field in ("taxonomy_version", "tag_groups", "cross_category_baseline"):
        require(summary["identity"].get(field) == old["identity"].get(field),
                f"{directory.name} has a mismatched {field}.")
PY

cp -al -- "$data/model/index" "$candidate/index"
cp -al -- "$data/$profile_name" "$profile_candidate"
mv -- "$profile_candidate/tags" "$stage/previous-profile-tags"
for name in tags tag_report.json tag_coverage.csv title_tag_review.csv; do
  mv -fT -- "$new_tags/$name" "$profile_candidate/$name"
done

backup="$(mktemp -d "$data/.model-backup.XXXXXXXX")"
rollback() {
  local result=$?
  if (( result == 0 )); then
    return
  fi
  trap - EXIT
  set +e
  echo 'Deployment check failed. Restoring the previous model.' >&2
  for name in model "$profile_name"; do
    if [[ -e "$backup/$name" ]]; then
      if [[ -e "$data/$name" ]]; then
        mv -- "$data/$name" "$stage/failed-$name"
      fi
      mv -- "$backup/$name" "$data/$name"
    fi
  done
  docker restart "$container" >/dev/null
  exit "$result"
}
trap rollback EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP

mv -- "$data/model" "$backup/model"
mv -- "$candidate" "$data/model"
mv -- "$data/$profile_name" "$backup/$profile_name"
mv -- "$profile_candidate" "$data/$profile_name"
echo 'Restarting the BeatX API.'
docker restart "$container" >/dev/null

model_is_ready() {
  curl -fsS --max-time 5 "$internal_api/api/status" |
    python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(d.get("model_id") != sys.argv[1] or not d.get("song_profiles"))' "$expected"
}
for attempt in {1..30}; do
  if model_is_ready 2>/dev/null; then
    break
  fi
  sleep 2
done
model_is_ready
curl -fsS --max-time 45 "$internal_api/api/recommend" \
  -H 'Content-Type: application/json' \
  -d '{"title":"study focus","seeds":[],"method":"unified","filters":{}}' |
  python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(d.get("method") != "unified" or not d.get("tracks"))'
trap - EXIT
rm -rf -- "$stage"
echo "Azure loaded model $expected. Previous model saved at $backup."
REMOTE

curl -fsS --max-time 20 -H "Origin: $page_origin" "$azure_api/api/status" |
  python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(d.get("model_id") != sys.argv[1] or not d.get("song_profiles"))' "$expected"
echo "Live model verified: $expected"
