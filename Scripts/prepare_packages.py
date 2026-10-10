#!/usr/bin/env python3
"""Remove a verified duplicate module map from the pinned swift-ignore package.

Run after locked package resolution and before xcodebuild, never concurrently
with a build. Only the redundant module-map files are removed; the dependency
revision, outer module map, headers and static library stay unchanged.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PINNED_REVISION = "4fc142964621eda7835a4524e567388f5ef6f1a0"
OUTER_BLOB = "9ea1a822ecdae472f4139271bb31f3febca37c96"
NESTED_BLOB = "25ff4f0e9dfeaeffc9527a600a6e8bf173234521"
INFO_BLOB = "1cdf0870974b3c5a4d49e381d0a9ec6fcebedfb3"
LOCKFILE = Path("Clop.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved")
ARTIFACT = Path("IgnoreRust.xcframework/macos-arm64_x86_64")


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def anchor(path: Path) -> Path:
    """Trust the supplied location, but never accept a symlink as that root."""
    if path.is_symlink():
        raise ValueError(f"Symlink is not allowed: {path}")
    result = path.resolve(strict=True)
    if not result.is_dir():
        raise ValueError(f"Expected directory: {path}")
    return result


def checked(base: Path, relative: Path, kind: str, optional: bool = False):
    """Check every component beneath an anchor without following symlinks."""
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError(f"Path escapes its root: {relative}")
    current = base
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            if optional:
                return None
            raise ValueError(f"Required package layout is missing: {current}") from None
        if stat.S_ISLNK(mode):
            raise ValueError(f"Symlink is not allowed: {current}")
        expected = kind if index == len(relative.parts) - 1 else "directory"
        matches = stat.S_ISDIR(mode) if expected == "directory" else stat.S_ISREG(mode)
        if not matches:
            raise ValueError(f"Expected {expected}: {current}")
    if not current.resolve().is_relative_to(base):
        raise ValueError(f"Path escapes its root: {current}")
    return current


def verify_blob(path: Path, expected: str) -> None:
    if git_blob(path.read_bytes()) != expected:
        raise ValueError(f"Unexpected bytes in {path}; refusing package cleanup")


def checkout_revision(checkout: Path) -> str:
    # Avoid accidentally inspecting the caller's repository through GIT_DIR,
    # GIT_WORK_TREE or injected command-line configuration environment variables.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(checkout),
         "rev-parse", "--show-toplevel", "HEAD"],
        check=True, capture_output=True, text=True, env=env,
    )
    lines = result.stdout.splitlines()
    if len(lines) != 2 or Path(lines[0]).resolve() != checkout:
        raise ValueError(f"Unexpected checkout repository: {checkout}")
    return lines[1]


def prepare_packages(derived_data: Path, root: Path = ROOT):
    root = anchor(root)
    derived_data = anchor(derived_data)
    lock = checked(root, LOCKFILE, "file")
    document = json.loads(lock.read_text())
    pins = document.get("pins") if isinstance(document, dict) else None
    if not isinstance(pins, list) or any(not isinstance(pin, dict) for pin in pins):
        raise ValueError("Unexpected Package.resolved format")
    matches = [pin for pin in pins if pin.get("identity") == "swift-ignore"]
    expected_pin = {
        "identity": "swift-ignore",
        "kind": "remoteSourceControl",
        "location": "https://github.com/alin23/swift-ignore",
        "state": {"revision": PINNED_REVISION, "version": "0.1.4"},
    }
    if matches != [expected_pin]:
        raise ValueError("swift-ignore lockfile pin changed; review the package workaround")

    checkout = checked(derived_data, Path("SourcePackages/checkouts/swift-ignore"), "directory")
    checked(checkout, Path(".git"), "directory")
    if checkout_revision(checkout) != PINNED_REVISION:
        raise ValueError("swift-ignore checkout HEAD does not match the expected pinned revision")
    info = checked(checkout, Path("IgnoreRust.xcframework/Info.plist"), "file")
    verify_blob(info, INFO_BLOB)
    headers = checked(checkout, ARTIFACT / "Headers", "directory")
    for name in ("libIgnore/SwiftBridgeCore.h", "libIgnore/ignore.h"):
        checked(headers, Path(name), "file")
    checked(checkout, ARTIFACT / "libIgnore.a", "file")
    # Unknown module maps or links mean the packaging layout needs fresh review.
    allowed_maps = {Path("module.modulemap"), Path("libIgnore/module.modulemap")}
    for directory, subdirs, files in os.walk(headers, followlinks=False):
        for name in subdirs + files:
            path = Path(directory) / name
            relative = path.relative_to(headers)
            checked(headers, relative, "directory" if name in subdirs else "file")
            if path.suffix == ".modulemap" and relative not in allowed_maps:
                raise ValueError(f"Unexpected module map: {path}")
    outer = checked(headers, Path("module.modulemap"), "file")
    verify_blob(outer, OUTER_BLOB)
    nested = checked(headers, Path("libIgnore/module.modulemap"), "file", optional=True)
    deletions = []
    if nested is not None:
        verify_blob(nested, NESTED_BLOB)
        deletions.append(nested)

    products = checked(derived_data, Path("Build/Products"), "directory", optional=True)
    if products is not None:
        for configuration in sorted(products.iterdir()):
            if configuration.is_symlink():
                raise ValueError(f"Symlink is not allowed: {configuration}")
            if not configuration.is_dir():
                continue
            relative = configuration.relative_to(derived_data) / "include"
            copied = checked(derived_data, relative / "libIgnore/module.modulemap", "file", optional=True)
            if copied is not None:
                copied_outer = checked(derived_data, relative / "module.modulemap", "file")
                verify_blob(copied_outer, OUTER_BLOB)
                verify_blob(copied, NESTED_BLOB)
                deletions.append(copied)

    # Complete the entire preflight before any deletion. A stale or surprising
    # generated copy must not leave the source checkout partially patched.
    for path in deletions:
        path.unlink()
    return deletions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("derived_data", type=Path, help="DerivedData used for locked package resolution")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        removed = prepare_packages(args.derived_data, args.root)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Package preparation failed: {error}", file=sys.stderr)
        return 1
    print(f"Verified swift-ignore 0.1.4; removed {len(removed)} redundant module map(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
