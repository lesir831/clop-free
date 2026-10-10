#!/usr/bin/env python3
"""Sign a staged app and its optimizer helpers, optionally notarizing with a local profile."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import plistlib
import posixpath
import shutil
import subprocess
import struct
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MACH_MAGICS = {
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
}
BUNDLE_SUFFIXES = {".app", ".framework", ".xpc", ".appex"}


def run(*args: str, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def is_macho(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    with path.open("rb") as stream:
        return stream.read(4) in MACH_MAGICS


def is_executable_macho(path: Path) -> bool:
    """Only MH_EXECUTE images receive process entitlements, never library code."""
    thin = {b"\xfe\xed\xfa\xce": ">", b"\xce\xfa\xed\xfe": "<",
            b"\xfe\xed\xfa\xcf": ">", b"\xcf\xfa\xed\xfe": "<"}
    fat = {b"\xca\xfe\xba\xbe": (">", 20), b"\xbe\xba\xfe\xca": ("<", 20),
           b"\xca\xfe\xba\xbf": (">", 32), b"\xbf\xba\xfe\xca": ("<", 32)}
    if not is_macho(path):
        return False
    with path.open("rb") as stream:
        magic = stream.read(4)
        if magic in thin:
            stream.seek(12)
            field = stream.read(4)
            return len(field) == 4 and struct.unpack(thin[magic] + "I", field)[0] == 2
        endian, size = fat[magic]
        field = stream.read(4)
        if len(field) != 4:
            return False
        count = struct.unpack(endian + "I", field)[0]
        if not 1 <= count <= 64:
            return False
        for index in range(count):
            stream.seek(8 + index * size + 8)
            offset_field = stream.read(8 if size == 32 else 4)
            if len(offset_field) != (8 if size == 32 else 4):
                return False
            offset = struct.unpack(endian + ("Q" if size == 32 else "I"), offset_field)[0]
            stream.seek(offset)
            slice_magic = stream.read(4)
            if slice_magic not in thin:
                return False
            stream.seek(offset + 12)
            filetype = stream.read(4)
            if len(filetype) != 4 or struct.unpack(thin[slice_magic] + "I", filetype)[0] != 2:
                return False
    return True


def signing_order(root: Path):
    """Physical files first; nested bundles afterwards, deepest before outermost."""
    paths = list(root.rglob("*"))
    files = sorted((path for path in paths if is_macho(path)), key=str)
    bundles = sorted(
        (path for path in paths if not path.is_symlink() and path.is_dir() and path.suffix in BUNDLE_SUFFIXES),
        key=lambda path: (-len(path.parts), str(path)),
    )
    return files + bundles


def sign_command(path: Path, identity: str, entitlements=None):
    # Teamless ad-hoc code cannot satisfy hardened-runtime library validation.
    # Keep that local mode separate from Developer ID distribution signatures.
    command = ["codesign", "--force", "--sign", identity, "--options", "0" if identity == "-" else "runtime"]
    command += ["--timestamp=none"] if identity == "-" else ["--timestamp"]
    if entitlements is not None:
        command += ["--entitlements", str(entitlements), "--generate-entitlement-der"]
    return command + [str(path)]


def sign(path: Path, identity: str, entitlements=None):
    run(*sign_command(path, identity, entitlements))


def extract_safe(archive: Path, destination: Path):
    """Validate the entire tar before extraction, including link traversal."""
    with tarfile.open(archive, "r:*") as stream:
        members = stream.getmembers()
        links = set()
        names = set()
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Unsafe archive path: {member.name}")
            normalized = posixpath.normpath(member.name)
            if normalized in names:
                raise ValueError(f"Duplicate archive path: {member.name}")
            names.add(normalized)
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise ValueError(f"Unsupported archive member: {member.name}")
            if member.issym() or member.islnk():
                base = str(path.parent) if member.issym() else "."
                target = posixpath.normpath(posixpath.join(base, member.linkname))
                target_parts = PurePosixPath(member.linkname).parts
                if member.issym():
                    # Leading parents start from the link's physical directory:
                    # member parents are forbidden from traversing links below.
                    # A parent after a named component could follow another link,
                    # so lexical normalization alone cannot prove it stays inside.
                    while target_parts and target_parts[0] == "..":
                        target_parts = target_parts[1:]
                if (target.startswith("/") or target == ".." or target.startswith("../")
                        or ".." in target_parts):
                    raise ValueError(f"Unsafe archive link: {member.name!r} -> {member.linkname!r} (normalized: {target!r})")
                links.add(normalized)
        for member in members:
            path = PurePosixPath(member.name)
            if any(str(parent) in links for parent in path.parents):
                raise ValueError(f"Archive member traverses a link: {member.name}")
            if member.islnk() and posixpath.normpath(member.linkname) in links:
                raise ValueError(f"Chained hard link in archive: {member.name}")
        destination.mkdir(parents=True, exist_ok=True)
        if any(destination.iterdir()):
            raise ValueError("Extraction destination must be empty")
        for member in members:
            # Never preserve archive ownership or privileged permission bits.
            member.uid = member.gid = 0
            member.uname = member.gname = ""
            member.mode &= 0o777
        # Paths, link targets and parents have all been checked above. This also
        # supports the Python bundled with Xcode, predating tarfile filters.
        if hasattr(tarfile, "data_filter"):
            stream.extractall(destination, members=members, filter="data")
        else:
            stream.extractall(destination, members=members)


def prepare_helpers(app: Path, workspace: Path, identity: str) -> Path:
    resources = app / "Contents/Resources"
    archive = resources / "bin.tar.lrz"
    checksum = resources / "bin.tar.lrz.sha256"
    sys.path.insert(0, str(ROOT / "Scripts"))
    from verify_assets import verify_archive
    verify_archive(archive, checksum)
    lrzip = resources / "lrzip"
    if not is_macho(lrzip):
        raise ValueError("Bundled lrzip is missing or is not a Mach-O executable")
    sign(lrzip, identity, ROOT / "Clop/bin.entitlements")
    # A previous run produces gzip at the same resource path. BSD tar detects
    # compression from the header, so the app's extraction code stays unchanged.
    with archive.open("rb") as stream:
        is_lrzip = stream.read(4) == b"LRZI"
    expanded_archive = workspace / "helpers.tar"
    if is_lrzip:
        run(lrzip, "-d", "-o", expanded_archive, archive)
    else:
        shutil.copyfile(archive, expanded_archive)
    helpers = workspace / "submission/OptimizerHelpers"
    extract_safe(expanded_archive, helpers)
    signed = 0
    for path in signing_order(helpers):
        sign(path, identity, ROOT / "Clop/bin.entitlements" if is_executable_macho(path) else None)
        run("codesign", "--verify", "--strict", path)
        signed += 1
    if not signed:
        raise ValueError("Optimizer archive contains no Mach-O helpers")
    temporary = workspace / "signed-helpers.tar.gz"
    with tarfile.open(temporary, "w:gz", compresslevel=6) as stream:
        for path in sorted(helpers.iterdir()):
            stream.add(path, arcname=path.name)
    shutil.copyfile(temporary, archive)
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    checksum.write_text(digest.hexdigest() + "\n")
    return helpers


def sign_app(app: Path, identity: str, notary_profile=None):
    if not app.is_dir() or app.is_symlink() or app.suffix != ".app":
        raise ValueError("Provide a real, staged .app directory")
    with (app / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    if info.get("CFBundleIdentifier") != "com.clop-free.Clop":
        raise ValueError("Refusing to sign a bundle without the independent clop-free identity")
    if notary_profile and identity == "-":
        raise ValueError("Notarization requires a Developer ID Application identity")
    with tempfile.TemporaryDirectory(prefix="clop-free-sign-") as temporary:
        workspace = Path(temporary)
        prepare_helpers(app, workspace, identity)
        for path in signing_order(app):
            entitlements = ROOT / "ClopCLI/ClopCLI.entitlements" if path.name == "ClopCLI" else None
            if path.name == "lrzip":
                entitlements = ROOT / "Clop/bin.entitlements"
            sign(path, identity, entitlements)
        sign(app, identity, ROOT / "Clop/Clop.entitlements")
        # --deep is appropriate for verification, not for recursively signing.
        run("codesign", "--verify", "--deep", "--strict", "--verbose=2", app)
        if identity != "-":
            details = run("codesign", "--display", "--verbose=4", app, capture_output=True, text=True)
            if "Authority=Developer ID Application:" not in details.stderr:
                raise ValueError("The supplied identity is not a Developer ID Application certificate")
        if notary_profile:
            run("ditto", app, workspace / "submission" / app.name)
            payload = workspace / "notarization.zip"
            run("ditto", "-c", "-k", "--keepParent", workspace / "submission", payload)
            result = run("xcrun", "notarytool", "submit", payload, "--wait", "--keychain-profile",
                         notary_profile, "--output-format", "json", capture_output=True, text=True)
            report = json.loads(result.stdout)
            print(json.dumps({"id": report.get("id"), "status": report.get("status")}))
            if report.get("status") != "Accepted":
                raise ValueError("Notarization was not accepted; inspect the submission with notarytool log")
            run("xcrun", "stapler", "staple", app)
            run("xcrun", "stapler", "validate", app)
            run("spctl", "--assess", "--type", "execute", "--verbose=2", app)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("--identity", default="-", help="'-' (default) or your installed Developer ID identity")
    parser.add_argument("--notary-profile", help="Existing local notarytool Keychain profile; never created here")
    args = parser.parse_args()
    try:
        if platform.system() != "Darwin":
            raise ValueError("Signing requires macOS")
        sign_app(args.app.absolute(), args.identity, args.notary_profile)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Signing failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
