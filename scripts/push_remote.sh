#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/push_remote.sh <remote-url>

Example:
  scripts/push_remote.sh git@github.com:OWNER/noteai.git
  scripts/push_remote.sh https://github.com/OWNER/noteai.git

The script verifies that the working tree is clean, configures origin, and
pushes main, tags, and Git LFS objects.
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -ne 1 ]]; then
  usage
  exit 1
fi

remote_url="$1"
current_branch="$(git rev-parse --abbrev-ref HEAD)"

if [[ "$current_branch" != "main" ]]; then
  echo "Expected branch main, got: $current_branch" >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree is not clean. Commit or stash changes before pushing." >&2
  git status --short >&2
  exit 1
fi

if ! command -v git-lfs >/dev/null 2>&1; then
  echo "git-lfs is required before pushing NoteAI model artifacts." >&2
  exit 1
fi

git lfs install --local >/dev/null

if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$remote_url"
else
  git remote add origin "$remote_url"
fi

echo "Remote origin:"
git remote -v

echo "Pushing branch main..."
git push -u origin main

echo "Pushing tags..."
git push origin --tags

echo "Pushing Git LFS objects..."
git lfs push origin --all

echo "Done. Verify the remote repository contains commit, tags, and LFS files."
