#!/bin/bash
# Prepare a merge candidate only. Never push, publish, reset the fork, or resolve
# conflicts by choosing one side. The workflow reviews/tests before its PR step.
set -euo pipefail
ROOT="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)"
cd "$ROOT"
UPSTREAM_REF="${UPSTREAM_REF:-}"
OUTPUT_DIR="${SYNC_OUTPUT_DIR:-$ROOT/build/upstream-sync}"
if [[ $# -gt 0 ]]; then
    echo 'Usage: UPSTREAM_REF=upstream/main make sync-upstream (ref is optional)' >&2
    exit 2
fi
if [[ -n "$(git status --porcelain)" ]]; then
    echo 'Start from a clean working tree, including untracked files.' >&2
    exit 1
fi
if [[ "$(git rev-parse --is-shallow-repository)" == true ]]; then
    echo 'Full history is required; fetch --unshallow before syncing.' >&2
    exit 1
fi
BASE="$(git rev-parse HEAD)"
python3 Scripts/validate_fork.py --root "$ROOT"
if [[ -z "$UPSTREAM_REF" ]]; then
    git -c core.hooksPath=/dev/null -c remote.clop-free-upstream.url=https://github.com/FuzzyIdeas/Clop.git \
        fetch --no-tags clop-free-upstream main
    UPSTREAM="$(git rev-parse 'FETCH_HEAD^{commit}')"
else
    UPSTREAM="$(git rev-parse --verify "${UPSTREAM_REF}^{commit}")"
fi
mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
if git merge-base --is-ancestor "$UPSTREAM" "$BASE"; then
    echo 'Upstream is already included; no candidate was created.'
    if [[ -n "${GITHUB_OUTPUT:-}" ]]; then echo 'changed=false' >> "$GITHUB_OUTPUT"; fi
    exit 0
fi
git merge-base "$BASE" "$UPSTREAM" >/dev/null || {
    echo 'Upstream does not share history with this fork; refusing to merge.' >&2; exit 1;
}
BRANCH="sync/upstream-${UPSTREAM:0:12}-${BASE:0:12}"
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    echo "Candidate branch $BRANCH already exists. Review it or remove it deliberately before retrying." >&2
    exit 1
fi
TEMP="$(mktemp -d "${TMPDIR:-/tmp}/clop-free-sync.XXXXXX")"
WORKTREE="$TEMP/candidate"
cleanup() {
    git -c core.hooksPath=/dev/null worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
    rm -rf "$TEMP"
}
trap cleanup EXIT
# Copy the checker before merging. Never execute a replacement from upstream.
cp Scripts/validate_fork.py "$TEMP/validate_fork.py"
GIT_LFS_SKIP_SMUDGE=1 git -c core.hooksPath=/dev/null worktree add --detach "$WORKTREE" "$BASE"
if ! GIT_LFS_SKIP_SMUDGE=1 git -C "$WORKTREE" -c core.hooksPath=/dev/null \
    -c user.name='clop-free upstream sync' -c user.email='sync@clop-free.invalid' \
    merge --no-ff --no-commit "$UPSTREAM"; then
    git -C "$WORKTREE" diff --name-only --diff-filter=U > "$OUTPUT_DIR/conflicts.txt"
    cat "$OUTPUT_DIR/conflicts.txt" >&2
    echo 'Upstream merge failed. No branch or PR was created; resolve manually on a review branch.' >&2
    exit 1
fi
# A clean merge must not silently weaken its own validation/build controls.
PROTECTED="$(git -C "$WORKTREE" diff --name-only "$BASE" -- .github Scripts tests Makefile docs/BUILDING.md)"
if [[ -n "$PROTECTED" ]]; then
    printf '%s\n' "$PROTECTED" > "$OUTPUT_DIR/manual-review.txt"
    printf 'Upstream changes protected build/test controls; manual review required:\n%s\n' "$PROTECTED" >&2
    exit 1
fi
python3 "$TEMP/validate_fork.py" --root "$WORKTREE"
git -C "$WORKTREE" diff --check
COMMIT_DATE="$(git show -s --format=%cI "$UPSTREAM")"
GIT_AUTHOR_DATE="$COMMIT_DATE" GIT_COMMITTER_DATE="$COMMIT_DATE" \
git -C "$WORKTREE" -c core.hooksPath=/dev/null \
    -c user.name='clop-free upstream sync' -c user.email='sync@clop-free.invalid' \
    -c commit.gpgsign=false commit -m "Merge upstream Clop ${UPSTREAM:0:12} for review"
CANDIDATE="$(git -C "$WORKTREE" rev-parse HEAD)"
git branch "$BRANCH" "$CANDIDATE"
git bundle create "$OUTPUT_DIR/candidate.bundle" "$BRANCH" "^$BASE"
python3 - "$OUTPUT_DIR/candidate.json" "$BRANCH" "$BASE" "$UPSTREAM" "$CANDIDATE" <<'PY'
import json, pathlib, sys
path, branch, base, upstream, candidate = sys.argv[1:]
pathlib.Path(path).write_text(json.dumps(dict(branch=branch, base=base, upstream=upstream, candidate=candidate), indent=2) + '\n')
PY
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    printf 'changed=true\nbranch=%s\nbase=%s\nupstream=%s\ncandidate=%s\n' \
        "$BRANCH" "$BASE" "$UPSTREAM" "$CANDIDATE" >> "$GITHUB_OUTPUT"
fi
printf 'Prepared %s at %s\nReview the merge and run make check and make build before publishing.\n' "$BRANCH" "$CANDIDATE"
