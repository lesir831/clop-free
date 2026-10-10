#!/usr/bin/env python3
"""Verify resource bytes before a build; never download or execute a resource."""
import argparse
import hashlib
from pathlib import Path
import re
import sys

LFS_HEADER = b"version https://git-lfs.github.com/spec/v1"


def verify_archive(archive: Path, checksum: Path) -> str:
    expected = checksum.read_text().strip()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError(f"Invalid SHA-256 file: {checksum}")
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        head = stream.read(1024)
        if head.startswith(LFS_HEADER):
            raise ValueError("Optimizer archive is a Git LFS pointer. Run `make assets` first.")
        digest.update(head)
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != expected:
        raise ValueError(f"SHA-256 mismatch for {archive}; refusing to build")
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        digest = verify_archive(args.root / "Clop/bin.tar.lrz", args.root / "Clop/bin.tar.lrz.sha256")
        if not (args.root / "lrzip").is_file():
            raise ValueError("Bundled lrzip decompressor is missing")
    except (OSError, ValueError) as error:
        print(f"Asset verification failed: {error}", file=sys.stderr)
        return 1
    print(f"Optimizer archive verified: {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
