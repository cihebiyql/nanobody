#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

REMOTE_URL="${NANOBODY_REMOTE_URL:-git@github.com:cihebiyql/nanobody.git}"
KEY="${NANOBODY_GIT_KEY:-/root/.ssh/id_ed25519_github_yuqiule}"
BRANCH="${NANOBODY_BRANCH:-main}"
MANIFEST="${NANOBODY_SYNC_MANIFEST:-docs/lightweight_sync_manifest.txt}"
STATUS_DOC="${NANOBODY_SYNC_STATUS_DOC:-docs/LIGHTWEIGHT_SYNC_STATUS.md}"
INTENT_LINE="${1:-Preserve lightweight nanobody work without uploading heavy datasets}"

if [[ ! -f "$KEY" ]]; then
  echo "Missing SSH key: $KEY" >&2
  exit 2
fi

if [[ ! -d .git ]]; then
  git init -b "$BRANCH"
fi

SYNC_LOCK="${NANOBODY_SYNC_LOCK:-$ROOT/.git/lightweight-sync.lock}"
mkdir -p "$(dirname "$SYNC_LOCK")"
exec 9>"$SYNC_LOCK"
if ! flock -n 9; then
  echo "Another lightweight sync is already running; skipping this cycle."
  exit 0
fi

git config user.name "cihebiyql"
git config user.email "yuqiule@gmail.com"

if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE_URL"
else
  git remote add origin "$REMOTE_URL"
fi

python3 scripts/build_lightweight_sync_manifest.py --output "$MANIFEST" --summary

git add -u
git add -f .gitignore .gitattributes scripts/build_lightweight_sync_manifest.py scripts/sync_lightweight_to_github.sh "$MANIFEST"

BACKUP_ROOT=""
EMBEDDED_GIT_BACKUPS=()
restore_embedded_git() {
  local pair gitdir backup
  for pair in "${EMBEDDED_GIT_BACKUPS[@]:-}"; do
    gitdir="${pair%%::*}"
    backup="${pair#*::}"
    if [[ -e "$backup" && ! -e "$gitdir" ]]; then
      mkdir -p "$(dirname "$gitdir")"
      mv "$backup" "$gitdir"
    fi
  done
  if [[ -n "$BACKUP_ROOT" && -d "$BACKUP_ROOT" ]]; then
    rmdir "$BACKUP_ROOT" 2>/dev/null || true
  fi
}

mapfile -t EMBEDDED_GIT_DIRS < <(python3 - "$MANIFEST" <<'PY'
from pathlib import Path
import sys
manifest = Path(sys.argv[1])
seen = set()
for rel in manifest.read_text(encoding='utf-8').splitlines():
    path = Path(rel)
    for parent in reversed(path.parents):
        if str(parent) in ('', '.'):
            continue
        gitdir = parent / '.git'
        if gitdir.is_dir():
            text = gitdir.as_posix()
            if text not in seen:
                seen.add(text)
                print(text)
PY
)

if (( ${#EMBEDDED_GIT_DIRS[@]} > 0 )); then
  BACKUP_ROOT="$(mktemp -d /tmp/nanobody-embedded-git.XXXXXX)"
  trap restore_embedded_git EXIT
  idx=0
  for gitdir in "${EMBEDDED_GIT_DIRS[@]}"; do
    backup="$BACKUP_ROOT/gitdir_$idx"
    mv "$gitdir" "$backup"
    EMBEDDED_GIT_BACKUPS+=("$gitdir::$backup")
    idx=$((idx + 1))
  done
fi

git add -f --pathspec-from-file="$MANIFEST"
restore_embedded_git
trap - EXIT

if git diff --cached --quiet; then
  echo "No lightweight changes to commit."
else
  python3 scripts/update_lightweight_sync_status.py \
    --manifest "$MANIFEST" \
    --output "$STATUS_DOC" \
    --synced-at "$(date --iso-8601=seconds)"
  git add -f "$STATUS_DOC" scripts/update_lightweight_sync_status.py
  COMMIT_MSG="$(mktemp)"
  cat > "$COMMIT_MSG" <<EOF
$INTENT_LINE

Constraint: Workspace contains hundreds of GB of datasets, environments, model weights, and docking outputs.
Rejected: Mirroring the full working tree | would upload large generated/downloaded artifacts instead of maintainable source/docs.
Confidence: high
Scope-risk: narrow
Directive: Re-run scripts/sync_lightweight_to_github.sh for future lightweight updates; do not git add the full workspace.
Tested: Manifest regenerated; git staged only manifest-selected lightweight files; push uses the yuqiule GitHub SSH key.
Not-tested: Remote CI is not configured in this lightweight snapshot.
EOF
  git commit -F "$COMMIT_MSG"
  rm -f "$COMMIT_MSG"
fi

GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new" \
  git push -u origin "$BRANCH"
