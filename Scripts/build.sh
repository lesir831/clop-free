#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[[ "$(uname -s)" == Darwin ]] || { echo 'A macOS host with full Xcode is required.' >&2; exit 1; }
command -v xcodebuild >/dev/null || { echo 'Select a full Xcode installation first.' >&2; exit 1; }
command -v python3 >/dev/null || { echo 'Python 3.9 or newer is required.' >&2; exit 1; }
XCODE_MAJOR="$(xcodebuild -version | awk '/^Xcode / {split($2, version, "."); print version[1]}')"
if [[ ! "$XCODE_MAJOR" =~ ^[0-9]+$ || "$XCODE_MAJOR" -lt 26 ]]; then
    echo 'Xcode 26 or newer is required for the macOS 26 SDK. Select it with DEVELOPER_DIR.' >&2
    exit 1
fi

CONFIGURATION="${CONFIGURATION:-Release}"
case "$CONFIGURATION" in Debug|Release) ;; *) echo 'CONFIGURATION must be Debug or Release' >&2; exit 1;; esac
IDENTITY="${SIGN_IDENTITY:--}"
if [[ -n "${NOTARY_PROFILE:-}" && "$IDENTITY" == - ]]; then
    echo 'Notarization needs your Developer ID Application identity, not ad-hoc signing.' >&2
    exit 1
fi
BUILD_DIR="${BUILD_DIR:-$ROOT/build}"
mkdir -p "$BUILD_DIR"
BUILD_DIR="$(cd "$BUILD_DIR" && pwd)"
python3 Scripts/validate_fork.py
python3 Scripts/verify_assets.py

# Signing is explicit after the complete bundle is assembled. No Apple account,
# provisioning profile, signing team or automatic credential lookup is needed.
XCODE_ARGS=(-project Clop.xcodeproj -scheme Clop
    -configuration "$CONFIGURATION" -destination 'generic/platform=macOS'
    -derivedDataPath "$BUILD_DIR/DerivedData"
    -disableAutomaticPackageResolution -onlyUsePackageVersionsFromResolvedFile)
# Prepare the locked package checkout before compilation. The guarded repair
# removes a redundant module map, not any library code or dependency version.
xcodebuild "${XCODE_ARGS[@]}" -resolvePackageDependencies
python3 Scripts/prepare_packages.py "$BUILD_DIR/DerivedData"
xcodebuild "${XCODE_ARGS[@]}" \
    build "ARCHS=${ARCHS:-arm64 x86_64}" ONLY_ACTIVE_ARCH=NO MACOSX_DEPLOYMENT_TARGET=13.0 \
    CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY= DEVELOPMENT_TEAM=

STAGE="$(mktemp -d "$BUILD_DIR/stage.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
ditto "$BUILD_DIR/DerivedData/Build/Products/$CONFIGURATION/Clop.app" "$STAGE/Clop Free.app"
ARGS=(--identity "$IDENTITY")
if [[ -n "${NOTARY_PROFILE:-}" ]]; then ARGS+=(--notary-profile "$NOTARY_PROFILE"); fi
python3 Scripts/sign_app.py "$STAGE/Clop Free.app" "${ARGS[@]}"
rm -rf "$BUILD_DIR/Clop Free.app"
mv "$STAGE/Clop Free.app" "$BUILD_DIR/Clop Free.app"
if [[ "${PACKAGE:-0}" == 1 || -n "${NOTARY_PROFILE:-}" ]]; then
    rm -f "$BUILD_DIR/clop-free.zip"
    ditto -c -k --keepParent "$BUILD_DIR/Clop Free.app" "$BUILD_DIR/clop-free.zip"
    shasum -a 256 "$BUILD_DIR/clop-free.zip" > "$BUILD_DIR/clop-free.zip.sha256"
fi
printf '\nBuilt: %s/Clop Free.app\n' "$BUILD_DIR"
if [[ "$IDENTITY" == - ]]; then
    echo 'Ad-hoc signed for local use; this is not a notarized distribution.'
fi
