#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# The git repo root is one level above reason_gatherer/
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
RESULTS_SUBPATH="reason_gatherer/results"
README="${REPO_DIR}/reason_gatherer/README.md"
RAW_BASE="https://raw.githubusercontent.com/sunsc0rch/reason_gatherer/main/reason_gatherer/results"
MAX_FILES=5

cd "$REPO_DIR"

# Rotate: keep only the MAX_FILES most recent run_*.txt and recheck_*.txt in git.
rotate_in_git() {
    local pattern="$1"
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

# Update the results table in README.md.
update_readme() {
    # Collect run and recheck files on disk, newest-first, capped at MAX_FILES.
    mapfile -t run_files    < <(ls "${RESULTS_SUBPATH}"/run_*.txt    2>/dev/null | sort -r | head -"$MAX_FILES")
    mapfile -t recheck_files < <(ls "${RESULTS_SUBPATH}"/recheck_*.txt 2>/dev/null | sort -r | head -"$MAX_FILES")

    # Build the table body lines.
    local table=""
    table+="| [**known_good.txt**](${RAW_BASE}/known_good.txt) | All verified configs ever collected — use as subscription URL |\n"

    local labels=("Latest run" "Previous run" "Earlier run" "Earlier run" "Earlier run")
    local idx=0
    for f in "${run_files[@]}"; do
        local name
        name="$(basename "$f")"
        local label="${labels[$idx]:-Earlier run}"
        table+="| [${name}](${RAW_BASE}/${name}) | ${label} |\n"
        (( idx++ )) || true
    done

    if (( ${#recheck_files[@]} > 0 )); then
        local rname
        rname="$(basename "${recheck_files[0]}")"
        table+="| [${rname}](${RAW_BASE}/${rname}) | Latest recheck (configs re-verified from known_good) |\n"
    fi

    # Replace everything between the table header and the next blank line.
    python3 - "$README" "$table" <<'PYEOF'
import sys, re
path, table = sys.argv[1], sys.argv[2]
content = open(path).read()
# Match the two-line table header + all subsequent | lines
pattern = r'(\| File \| Description \|\n\|---\|---\|\n)(\|.*\n)+'
replacement = r'\g<1>' + table.replace('\\n', '\n')
new_content = re.sub(pattern, replacement, content)
open(path, 'w').write(new_content)
PYEOF

    echo "$(date): updated README.md results table"
}

update_readme
git add "${README}"

if git diff --cached --quiet; then
    echo "$(date): no changes in results/, skipping push"
    exit 0
fi

git commit -m "results: auto-push verified configs $(date +%Y-%m-%d)"
git push origin main
echo "$(date): pushed results to origin"
