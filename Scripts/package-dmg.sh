#!/bin/bash
# Package an already-built, signed app. Never changes the app, tag, or release.
set -euo pipefail
[[ "$(uname -s)" == Darwin ]] || { echo 'DMG packaging requires macOS.' >&2; exit 1; }
[[ $# == 5 ]] || { echo 'Usage: package-dmg.sh APP SOURCE_CHECKOUT VERSION EXPECTED_SOURCE_COMMIT OUTPUT_DIR' >&2; exit 1; }
APP="$1"
SOURCE="$(cd "$2" && pwd)"
VERSION="$3"
EXPECTED="$4"
OUT="$5"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && "$EXPECTED" =~ ^[0-9a-f]{40}$ ]] || {
    echo 'Invalid version or expected commit.' >&2; exit 1;
}
[[ -d "$APP" && ! -L "$APP" ]] || { echo 'App must be a real directory.' >&2; exit 1; }
APP="$(cd "$APP" && pwd)"
[[ "$(git -C "$SOURCE" rev-parse HEAD)" == "$EXPECTED" ]] || { echo 'Source commit mismatch.' >&2; exit 1; }
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
NAME="Clop-Free-$VERSION-universal"
DMG="$OUT/$NAME.dmg"
[[ ! -e "$DMG" ]] || { echo "Refusing to replace $DMG" >&2; exit 1; }
WORK="$(mktemp -d)"
MOUNT="$WORK/mount"
mkdir "$MOUNT"
ATTACHED=0
cleanup() {
    if [[ "$ATTACHED" == 1 ]]; then hdiutil detach "$MOUNT" >/dev/null; fi
    rm -rf "$WORK"
}
trap cleanup EXIT

verify_app() {
    local target="$1"
    python3 - "$target" "$VERSION" <<'PY'
import pathlib, plistlib, sys
app = pathlib.Path(sys.argv[1])
with (app / 'Contents/Info.plist').open('rb') as stream:
    info = plistlib.load(stream)
assert info['CFBundleIdentifier'] == 'com.clop-free.Clop', 'Unexpected bundle identity'
assert info['CFBundleShortVersionString'] == sys.argv[2], 'Unexpected application version'
assert info['CFBundleExecutable'] == 'Clop', 'Unexpected executable'
assert (app / 'Contents/MacOS/Clop').is_file(), 'Missing application executable'
PY
    codesign --verify --deep --strict --verbose=2 "$target"
    lipo "$target/Contents/MacOS/Clop" -verify_arch arm64 x86_64
    lipo -archs "$target/Contents/MacOS/Clop"
}
verify_app "$APP"
mkdir "$WORK/payload"
ditto "$APP" "$WORK/payload/Clop Free.app"
ln -s /Applications "$WORK/payload/Applications"
cp "$SOURCE/LICENSE" "$WORK/payload/LICENSE.txt"
cp "$SOURCE/NOTICE.md" "$WORK/payload/NOTICE.md"
cp "$SOURCE/FORK_CHANGELOG.md" "$WORK/payload/FORK_CHANGELOG.md"
cat > "$WORK/payload/READ-ME.txt" <<TEXT
Clop Free $VERSION

Drag Clop Free.app to Applications, then eject this disk image.
This independent fork is not affiliated with or endorsed by the upstream authors.

Source commit: $EXPECTED
Source: https://github.com/lesir831/clop-free/tree/$EXPECTED

This application is ad-hoc signed, not Developer ID signed or Apple notarized.
Gatekeeper may block this downloaded build. No system security setting is changed.

LICENSE.txt, NOTICE.md and FORK_CHANGELOG.md preserve the source notices.
Lowtech and swift-ignore redistribution grants remain unverified; bundled tools
and binary frameworks have unresolved corresponding-source/provenance obligations.
This build and its source snapshot do not resolve or certify those obligations.
NOTICE.md is preserved verbatim from the source tag, including its earlier
artifact-withholding statement. This separately requested build does not assert
that missing third-party rights have been obtained.

CI verifies build, signatures, universal executable and disk-image contents.
Interactive UI, real-media optimization and all supported macOS versions have
not been comprehensively runtime-tested.
TEXT
hdiutil create -volname "Clop Free $VERSION" -srcfolder "$WORK/payload" -format UDZO -ov "$DMG"
hdiutil verify "$DMG"
hdiutil attach -readonly -nobrowse -mountpoint "$MOUNT" "$DMG"
ATTACHED=1
[[ -L "$MOUNT/Applications" && "$(readlink "$MOUNT/Applications")" == /Applications ]]
verify_app "$MOUNT/Clop Free.app"
cmp "$SOURCE/LICENSE" "$MOUNT/LICENSE.txt"
cmp "$SOURCE/NOTICE.md" "$MOUNT/NOTICE.md"
# Compare the complete signed bundle after the image's compression/mount roundtrip.
diff -qr "$APP" "$MOUNT/Clop Free.app"
# UDZO is compressed read-only. Also require the mounted filesystem to reject writes.
if touch "$MOUNT/.write-test" 2>/dev/null; then
    rm -f "$MOUNT/.write-test"
    echo 'DMG unexpectedly writable.' >&2; exit 1
fi
hdiutil detach "$MOUNT"
ATTACHED=0
cp "$WORK/payload/READ-ME.txt" "$OUT/$NAME.READ-ME.txt"
# Git archive emits the exact tracked source tree, including LFS pointers and lrzip.
git -C "$SOURCE" archive --format=tar --prefix="clop-free-$VERSION/" "$EXPECTED" | gzip -n > "$OUT/clop-free-$VERSION-source.tar.gz"
python3 - "$OUT" "$EXPECTED" "$VERSION" <<'PY'
import json, os, pathlib, platform, subprocess, sys
out, commit, version = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
manifest = {
    'version': version, 'source_commit': commit,
    'source_url': f'https://github.com/lesir831/clop-free/tree/{commit}',
    'workflow_commit': os.environ.get('GITHUB_SHA'),
    'workflow_run': f"https://github.com/{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ.get('GITHUB_RUN_ID')}",
    'runner_os': platform.platform(),
    'xcode': subprocess.check_output(['xcodebuild', '-version'], text=True).strip(),
    'architectures': ['arm64', 'x86_64'],
    'signing': 'ad-hoc', 'notarized': False,
    'verified': ['source commit', 'bundle ID and version', 'strict nested signatures',
                 'universal app executable', 'DMG checksum', 'read-only mount',
                 'Applications symlink', 'license and notice preservation',
                 'byte-for-byte app contents after DMG mount'],
    'limitations': ['No comprehensive interactive or media-processing runtime test',
                    'Not a byte-for-byte reproducible-build guarantee',
                    'Unresolved Lowtech/swift-ignore redistribution grants and bundled-binary provenance',
                    'Source snapshot is not complete corresponding source for every dependency'],
}
(out / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
PY
(
    cd "$OUT"
    shasum -a 256 "$NAME.dmg" "clop-free-$VERSION-source.tar.gz" "$NAME.READ-ME.txt" build-manifest.json > SHA256SUMS
    shasum -a 256 -c SHA256SUMS
    cat SHA256SUMS
    cat build-manifest.json
)
printf '\nVerified DMG: %s\n' "$DMG"
