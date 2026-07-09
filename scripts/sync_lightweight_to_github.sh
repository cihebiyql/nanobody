#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

REMOTE_URL="${NANOBODY_REMOTE_URL:-git@github.com:cihebiyql/nanobody.git}"
KEY="${NANOBODY_GIT_KEY:-/root/.ssh/id_ed25519_github_yuqiule}"
BRANCH="${NANOBODY_BRANCH:-main}"
MANIFEST="${NANOBODY_SYNC_MANIFEST:-docs/lightweight_sync_manifest.txt}"
INTENT_LINE="${1:-Preserve lightweight nanobody work without uploading heavy datasets}"

if [[ ! -f "$KEY" ]]; then
  echo "Missing SSH key: $KEY" >&2
  exit 2
fi

if [[ ! -d .git ]]; then
  git init -b "$BRANCH"
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
git add -f --pathspec-from-file="$MANIFEST"

if git diff --cached --quiet; then
  echo "No lightweight changes to commit."
else
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
