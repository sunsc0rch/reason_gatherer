#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# The git repo root is one level above reason_gatherer/
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
RESULTS_SUBPATH="reason_gatherer/results"
MAX_FILES=5

cd "$REPO_DIR"

# Rotate: keep only the MAX_FILES most recent run_*.txt and recheck_*.txt in git.
rotate_in_git() {
    local pattern="$1"
    # Files currently tracked in git matching the pattern, sorted oldest-first.
    mapfile -t tracked < <(git ls-files "${RESULTS_SUBPATH}/${pattern}" | sort)
    local excess=$(( ${#tracked[@]} - MAX_FILES ))
    if (( excess > 0 )); then
        for f in "${tracked[@]:0:$excess}"; do
            git rm --cached --force "$f" 2>/dev/null || true
            echo "$(date): rotated out $f"
        done
    fi
}

rotate_in_git "run_*.txt"
rotate_in_git "recheck_*.txt"

git add "${RESULTS_SUBPATH}/known_good.txt" \
        "${RESULTS_SUBPATH}"/run_*.txt \
        "${RESULTS_SUBPATH}"/recheck_*.txt 2>/dev/null || true

if git diff --cached --quiet; then
    echo "$(date): no changes in results/, skipping push"
    exit 0
fi

git commit -m "results: auto-push verified configs $(date +%Y-%m-%d)"
git push origin main
echo "$(date): pushed results to origin"
