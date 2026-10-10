#!/usr/bin/env python3
"""Check pinned optimizer archive paths before spending time compiling the app."""
from pathlib import Path
import shutil
import subprocess
import tempfile

from sign_app import extract_safe, is_macho
from verify_assets import verify_archive

ROOT = Path(__file__).resolve().parents[1]


def main():
    archive = ROOT / "Clop/bin.tar.lrz"
    verify_archive(archive, ROOT / "Clop/bin.tar.lrz.sha256")
    with tempfile.TemporaryDirectory(prefix="clop-free-archive-check-") as temporary:
        workspace = Path(temporary)
        expanded = workspace / "helpers.tar"
        with archive.open("rb") as stream:
            compressed = stream.read(4) == b"LRZI"
        if compressed:
            decompressor = ROOT / "lrzip"
            if not is_macho(decompressor):
                raise ValueError("Bundled lrzip decompressor is missing or invalid")
            subprocess.run([str(decompressor), "-d", "-o", str(expanded), str(archive)], check=True)
        else:
            shutil.copyfile(archive, expanded)
        extract_safe(expanded, workspace / "expanded")
    print("PASS: pinned optimizer archive path and link validation")


if __name__ == "__main__":
    main()
