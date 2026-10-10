#!/usr/bin/env python3
"""Fail closed if a merge restores known paid gates or upstream account coupling.

This is a regression guard, not a substitute for reviewing new upstream logic.
It is deliberately self-contained so sync can run the trusted baseline copy.
"""
import argparse
import hashlib
from pathlib import Path
import plistlib
import re
import sys

LICENSE_SHA256 = "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"
FORBIDDEN_SWIFT = {
    "paid/licensing module": r"\bimport\s+(?:LowtechPro\w*|Paddle\w*|Sentry|AntiCrack)\b",
    "licensing manager": r"\b(?:ProManager|LicenceManager|LicenseManager|Anticrack|AntiCrack)\b",
    "legacy paid gate": (r"\b(?:proactive|proGuard|validReq\d*|invalidReq\d*|OptimisationCounter)\b"
                         r"|\b(?:count|counter)\s*\.\s*take\s*\("),
    "paid entitlement state": r"\b(?:PRO_ACTIVE|PRO_EXPIRED|IS_TRIAL|TRIAL_EXPIRED)\b",
    "upstream telemetry/payment endpoint": r"(?:sentry\.io|api\.paddle\.com|vendors\.paddle\.com)",
}


def check(root: Path):
    errors = []
    required = ["LICENSE", "Clop/ClopApp.swift", "Clop/OptimisationUtils.swift", "Shared.swift",
                "Clop.xcodeproj/project.pbxproj", "Clop/Info.plist", "Clop/Clop.entitlements",
                "ClopCLI/ClopCLI.entitlements", "Scripts/test_feature_policy.py"]
    for name in required:
        path = root / name
        if not path.is_file() or path.is_symlink():
            errors.append(f"Missing or symlinked required file: {name}")
    if errors:
        return errors
    if hashlib.sha256((root / "LICENSE").read_bytes()).hexdigest() != LICENSE_SHA256:
        errors.append("GPL-3.0 LICENSE was removed or changed; requires manual legal review")
    files = [root / "Shared.swift"]
    for directory in ("Clop", "ClopCLI", "Shared"):
        files += sorted((root / directory).rglob("*.swift"))
    for path in files:
        if path.is_symlink():
            errors.append(f"Unexpected source symlink: {path.relative_to(root)}")
            continue
        text = path.read_text()
        for name, pattern in FORBIDDEN_SWIFT.items():
            if re.search(pattern, text):
                errors.append(f"{path.relative_to(root)}: found {name}")
    project = (root / "Clop.xcodeproj/project.pbxproj").read_text()
    for pattern, reason in [
        (r"\bLowtechPro\w*\b", "paid package product"),
        (r"RDDXV84A73|com\.lowtechguys\.Clop", "upstream signing or bundle identity"),
        (r"relativePath\s*=\s*\"?(?:/|\.\./)", "external local package path"),
        (r"DEVELOPMENT_TEAM\s*=\s*(?!\"\"\s*;)[^;\s]+", "embedded signing team"),
    ]:
        if re.search(pattern, project):
            errors.append(f"Xcode project: found {reason}")
    for bundle_id in ("com.clop-free.Clop", "com.clop-free.Clop.CLI"):
        if not re.search(r"PRODUCT_BUNDLE_IDENTIFIER\s*=\s*\"?" + re.escape(bundle_id) + r'"?\s*;', project):
            errors.append(f"Xcode project: missing independent bundle ID {bundle_id}")
    with (root / "Clop/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    for key in ("SUFeedURL", "SUPublicEDKey"):
        if key in info:
            errors.append(f"App metadata restores updater configuration: {key}")
    if info.get("NSPrincipalClass", "NSApplication") != "NSApplication":
        errors.append("App metadata has a nonstandard principal class")
    for name in ("Clop/Clop.entitlements", "ClopCLI/ClopCLI.entitlements"):
        with (root / name).open("rb") as stream:
            entitlements = plistlib.load(stream)
        if any(key.startswith("com.apple.developer.") for key in entitlements):
            errors.append(f"{name}: provisioning-dependent entitlement restored")
        if "com.lowtechguys.Clop" in str(entitlements):
            errors.append(f"{name}: upstream IPC namespace restored")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        errors = check(args.root.resolve())
    except (OSError, ValueError, plistlib.InvalidFileException) as error:
        errors = [f"Could not validate fork: {error}"]
    if errors:
        print("Fork validation failed:\n- " + "\n- ".join(errors), file=sys.stderr)
        return 1
    print("Fork invariants passed (known gates, identity, signing, metadata and GPL license)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
