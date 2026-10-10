#!/usr/bin/env python3
"""Fetch the exact upstream optimizer resource for source ZIPs without Git history."""
from __future__ import annotations
import argparse
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import urllib.error
import urllib.request

# Update all three together only after reviewing a new upstream binary payload.
UPSTREAM_REVISION = "af3cdb95faf330f16508ab6cd0b334053478a827"
EXPECTED_SHA256 = "0eac2f2ffe4ca4ffedd216229e07198196c0994a908215c3e98acd6b0eb4c75f"
EXPECTED_SIZE = 65_922_782
ASSET_URL = f"https://media.githubusercontent.com/media/FuzzyIdeas/Clop/{UPSTREAM_REVISION}/Clop/bin.tar.lrz"
ROOT = Path(__file__).resolve().parents[1]


def fetch(root: Path) -> None:
    archive = root / "Clop/bin.tar.lrz"
    checksum = root / "Clop/bin.tar.lrz.sha256"
    if checksum.read_text().strip() != EXPECTED_SHA256:
        raise ValueError("Archive checksum differs from the pinned source-ZIP download. Review and update the pin; no download attempted.")
    if archive.is_file() and archive.stat().st_size == EXPECTED_SIZE:
        with archive.open("rb") as stream:
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() == EXPECTED_SHA256:
            print("Optimizer archive already verified")
            return
    descriptor, temporary = tempfile.mkstemp(prefix=".clop-free-assets-", suffix=".tmp", dir=archive.parent)
    temporary = Path(temporary)
    try:
        total = 0
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "wb") as output, urllib.request.urlopen(ASSET_URL, timeout=120) as response:
            for block in iter(lambda: response.read(1024 * 1024), b""):
                total += len(block)
                if total > EXPECTED_SIZE:
                    raise ValueError("Downloaded archive exceeds the pinned size")
                digest.update(block)
                output.write(block)
        if total != EXPECTED_SIZE or digest.hexdigest() != EXPECTED_SHA256:
            raise ValueError("Downloaded archive did not match the pinned size and SHA-256")
        temporary.chmod(0o644)
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Optimizer archive downloaded and verified: {EXPECTED_SHA256}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        fetch(args.root)
    except (OSError, ValueError, urllib.error.URLError) as error:
        print(f"Source archive asset preparation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
