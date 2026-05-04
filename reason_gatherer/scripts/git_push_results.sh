#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

# Nothing to push if results haven't changed
if git diff --quiet HEAD -- results/ && git ls-files --others --exclude-standard results/ | grep -q .; then
    :  # untracked new run files exist, fall through
elif git diff --quiet HEAD -- results/; then
    echo "$(date): no changes in results/, skipping push"
    exit 0
fi

git add results/known_good.txt results/run_*.txt 2>/dev/null || true

if git diff --cached --quiet; then
    echo "$(date): nothing staged, skipping push"
    exit 0
fi

git commit -m "results: auto-push verified configs $(date +%Y-%m-%d)"
git push origin main
echo "$(date): pushed results to origin"
