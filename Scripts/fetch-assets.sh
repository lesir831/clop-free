#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

if python3 Scripts/verify_assets.py >/dev/null 2>&1; then
    python3 Scripts/verify_assets.py
    exit 0
fi
# Downloaded source ZIPs have no Git metadata. Use an immutable upstream URL
# with pinned byte count and SHA-256; never synthesize a Git repository here.
if [[ "$(git rev-parse --show-toplevel 2>/dev/null || true)" != "$(pwd -P)" ]]; then
    python3 Scripts/fetch_source_assets.py
    python3 Scripts/verify_assets.py
    exit 0
fi
command -v git-lfs >/dev/null || { echo 'Install Git LFS, then run make assets again.' >&2; exit 1; }
git_lfs() {
    git -c filter.lfs.required=true \
        -c 'filter.lfs.clean=git-lfs clean -- %f' \
        -c 'filter.lfs.smudge=git-lfs smudge -- %f' \
        -c 'filter.lfs.process=git-lfs filter-process' "$@"
}
# A command-scoped public remote also works in independent forks without a
# duplicate LFS store. It neither rewrites origin nor stores credentials.
if [[ -n "${LFS_REMOTE:-}" ]]; then
    git remote get-url "$LFS_REMOTE" >/dev/null
    git_lfs lfs pull --include='Clop/bin.tar.lrz' --exclude='' "$LFS_REMOTE"
else
    git_lfs -c remote.clop-free-assets.url=https://github.com/FuzzyIdeas/Clop.git \
        lfs pull --include='Clop/bin.tar.lrz' --exclude='' clop-free-assets
fi
# The checkout also handles objects already fetched before LFS filters were set.
# All filter settings above are command-scoped; no global config or hooks change.
git_lfs lfs checkout Clop/bin.tar.lrz
python3 Scripts/verify_assets.py
