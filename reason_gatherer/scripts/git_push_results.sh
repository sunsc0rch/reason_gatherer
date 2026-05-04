#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# The git repo root is one level above reason_gatherer/
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
RESULTS_SUBPATH="reason_gatherer/results"

cd "$REPO_DIR"

git add "${RESULTS_SUBPATH}/known_good.txt" "${RESULTS_SUBPATH}"/run_*.txt 2>/dev/null || true

if git diff --cached --quiet; then
    echo "$(date): no changes in results/, skipping push"
    exit 0
fi

git commit -m "results: auto-push verified configs $(date +%Y-%m-%d)"
git push origin main
echo "$(date): pushed results to origin"
