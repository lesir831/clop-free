"""Regression tests for the narrowly scoped swift-ignore package workaround."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prepare_packages", ROOT / "Scripts/prepare_packages.py")
packages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packages)

OUTER = b'module IgnoreRust {\n    header "libIgnore/SwiftBridgeCore.h"\n    header "libIgnore/ignore.h"\n    export *\n}\n'
NESTED = b'module IgnoreRust {\n    header "SwiftBridgeCore.h"\n    header "ignore.h"\n    export *\n}\n'
INFO = b'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>AvailableLibraries</key>
	<array>
		<dict>
			<key>BinaryPath</key>
			<string>libIgnore.a</string>
			<key>HeadersPath</key>
			<string>Headers</string>
			<key>LibraryIdentifier</key>
			<string>macos-arm64_x86_64</string>
			<key>LibraryPath</key>
			<string>libIgnore.a</string>
			<key>SupportedArchitectures</key>
			<array>
				<string>arm64</string>
				<string>x86_64</string>
			</array>
			<key>SupportedPlatform</key>
			<string>macos</string>
		</dict>
	</array>
	<key>CFBundlePackageType</key>
	<string>XFWK</string>
	<key>XCFrameworkFormatVersion</key>
	<string>1.0</string>
</dict>
</plist>
'''


class PackagePreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.derived = self.root / "DerivedData"
        self.checkout = self.derived / "SourcePackages/checkouts/swift-ignore"
        self.headers = self.checkout / packages.ARTIFACT / "Headers"
        self.outer = self.headers / "module.modulemap"
        self.nested = self.headers / "libIgnore/module.modulemap"
        self.info = self.checkout / "IgnoreRust.xcframework/Info.plist"
        self.lock = self.root / packages.LOCKFILE
        self.pin = {
            "identity": "swift-ignore", "kind": "remoteSourceControl",
            "location": "https://github.com/alin23/swift-ignore",
            "state": {"revision": packages.PINNED_REVISION, "version": "0.1.4"},
        }
        self.write_lock([self.pin])
        (self.checkout / ".git").mkdir(parents=True)
        (self.headers / "libIgnore").mkdir(parents=True)
        self.outer.write_bytes(OUTER)
        self.nested.write_bytes(NESTED)
        self.info.write_bytes(INFO)
        (self.headers / "libIgnore/SwiftBridgeCore.h").write_bytes(b"core header\n")
        (self.headers / "libIgnore/ignore.h").write_bytes(b"ignore header\n")
        (self.checkout / packages.ARTIFACT / "libIgnore.a").write_bytes(b"static library\n")
        self.head = patch.object(packages, "checkout_revision", return_value=packages.PINNED_REVISION)
        self.mock_head = self.head.start()
        self.addCleanup(self.head.stop)

    def write_lock(self, pins):
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        self.lock.write_text(json.dumps({"pins": pins, "version": 2}))

    def prepare(self):
        return packages.prepare_packages(self.derived, self.root)

    def generated(self, configuration="Release"):
        include = self.derived / "Build/Products" / configuration / "include"
        (include / "libIgnore").mkdir(parents=True)
        (include / "module.modulemap").write_bytes(OUTER)
        (include / "libIgnore/module.modulemap").write_bytes(NESTED)
        (include / "libIgnore/ignore.h").write_bytes(b"generated header\n")
        return include

    def snapshot(self):
        # Do not follow links when recording fixtures for fail-closed assertions.
        result = {}
        for directory, subdirs, files in os.walk(self.root, followlinks=False):
            for name in subdirs + files:
                path = Path(directory) / name
                relative = path.relative_to(self.root)
                if path.is_symlink():
                    result[relative] = ("symlink", os.readlink(path))
                elif path.is_file():
                    result[relative] = ("file", path.read_bytes())
        return result

    def assert_rejected_without_mutation(self, message):
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, message):
            self.prepare()
        self.assertEqual(self.snapshot(), before)

    def test_fixture_matches_pinned_git_blob_hashes(self):
        self.assertEqual(packages.git_blob(OUTER), packages.OUTER_BLOB)
        self.assertEqual(packages.git_blob(NESTED), packages.NESTED_BLOB)
        self.assertEqual(packages.git_blob(INFO), packages.INFO_BLOB)

    def test_removes_only_duplicate_maps_and_is_idempotent(self):
        release = self.generated()
        debug = self.generated("Debug")
        before = self.snapshot()
        removed = self.prepare()
        expected = {self.nested, release / "libIgnore/module.modulemap", debug / "libIgnore/module.modulemap"}
        self.assertEqual(set(removed), expected)
        for path in expected:
            del before[path.relative_to(self.root)]
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.prepare(), [])
        self.assertEqual(self.snapshot(), before)

    def test_source_only_and_missing_generated_layout(self):
        self.assertEqual(self.prepare(), [self.nested])
        self.assertEqual(self.prepare(), [])

    def test_already_patched_source_still_cleans_generated_copy(self):
        self.nested.unlink()
        include = self.generated()
        self.assertEqual(self.prepare(), [include / "libIgnore/module.modulemap"])

    def test_changed_source_map_bytes_preserve_all_files(self):
        self.generated()
        for path in (self.outer, self.nested, self.info):
            with self.subTest(path=path):
                original = path.read_bytes()
                path.write_bytes(original + b"unexpected\n")
                self.assert_rejected_without_mutation("Unexpected bytes")
                path.write_bytes(original)

    def test_late_generated_mismatch_preserves_source_and_earlier_copy(self):
        self.generated("A-valid")
        include = self.generated("Z-invalid")
        for path in (include / "module.modulemap", include / "libIgnore/module.modulemap"):
            with self.subTest(path=path):
                original = path.read_bytes()
                path.write_bytes(b"unexpected bytes\n")
                self.assert_rejected_without_mutation("Unexpected bytes")
                path.write_bytes(original)

    def test_missing_generated_outer_preserves_everything(self):
        include = self.generated()
        (include / "module.modulemap").unlink()
        self.assert_rejected_without_mutation("layout is missing")

    def test_pin_changes_preserve_files(self):
        for pins in ([], [self.pin, self.pin],
                     [dict(self.pin, location="https://example.invalid/fork")],
                     [dict(self.pin, kind="localSourceControl")],
                     [dict(self.pin, state={"revision": "0" * 40, "version": "0.1.4"})],
                     [dict(self.pin, state={"revision": packages.PINNED_REVISION, "version": "0.1.5"})]):
            with self.subTest(pins=pins):
                self.write_lock(pins)
                self.assert_rejected_without_mutation("lockfile pin changed")

    def test_malformed_lockfile_preserves_files(self):
        for document in ("not json", "[]", '{"pins": {}}', '{"pins": [null]}'):
            with self.subTest(document=document):
                self.lock.write_text(document)
                self.assert_rejected_without_mutation(".")

    def test_checkout_revision_mismatch_preserves_files(self):
        self.mock_head.return_value = "0" * 40
        self.assert_rejected_without_mutation("checkout HEAD")

    def test_missing_required_layout_preserves_files(self):
        for path in (self.outer, self.info, self.headers / "libIgnore/SwiftBridgeCore.h",
                     self.headers / "libIgnore/ignore.h", self.checkout / packages.ARTIFACT / "libIgnore.a"):
            with self.subTest(path=path):
                original = path.read_bytes()
                path.unlink()
                self.assert_rejected_without_mutation("layout is missing")
                path.write_bytes(original)

    def test_unexpected_additional_module_map_preserves_files(self):
        (self.headers / "libIgnore/extra.modulemap").write_bytes(NESTED)
        self.assert_rejected_without_mutation("Unexpected module map")

    def test_symlink_files_preserve_link_targets_and_other_candidates(self):
        include = self.generated()
        targets = (self.lock, self.outer, self.nested, self.info,
                   self.headers / "libIgnore/ignore.h", self.checkout / packages.ARTIFACT / "libIgnore.a",
                   include / "module.modulemap", include / "libIgnore/module.modulemap")
        for path in targets:
            with self.subTest(path=path):
                backup = self.root / "link-target"
                path.rename(backup)
                path.symlink_to(backup)
                self.assert_rejected_without_mutation("Symlink")
                path.unlink()
                backup.rename(path)

    def test_symlink_directories_reject_escapes_before_any_deletion(self):
        include = self.generated()
        targets = (self.checkout / ".git", self.checkout, self.headers / "libIgnore",
                   self.derived / "Build/Products/Release", include,
                   self.derived / "SourcePackages", self.derived)
        for path in targets:
            with self.subTest(path=path):
                backup = self.root / "link-target"
                path.rename(backup)
                path.symlink_to(backup, target_is_directory=True)
                self.assert_rejected_without_mutation("Symlink")
                path.unlink()
                backup.rename(path)

    def test_dangling_generated_symlink_is_not_treated_as_missing(self):
        include = self.generated()
        nested = include / "libIgnore/module.modulemap"
        nested.unlink()
        nested.symlink_to(self.root / "nonexistent")
        self.assert_rejected_without_mutation("Symlink")

    def test_path_traversal_and_absolute_paths_rejected(self):
        for relative in (Path("../escape"), self.root / "absolute"):
            with self.subTest(relative=relative):
                with self.assertRaisesRegex(ValueError, "escapes"):
                    packages.checked(self.derived, relative, "file", optional=True)
        self.assertTrue(self.nested.exists())

    def test_generated_duplicate_directory_is_rejected(self):
        include = self.generated()
        nested = include / "libIgnore/module.modulemap"
        nested.unlink()
        nested.mkdir()
        self.assert_rejected_without_mutation("Expected file")


class CheckoutRevisionTests(unittest.TestCase):
    def test_checks_repository_and_clears_git_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory).resolve()
            output = subprocess.CompletedProcess([], 0, f"{checkout}\n{packages.PINNED_REVISION}\n", "")
            with patch.dict(os.environ, {"GIT_DIR": "/wrong", "GIT_CONFIG_COUNT": "1"}), \
                    patch.object(packages.subprocess, "run", return_value=output) as run:
                self.assertEqual(packages.checkout_revision(checkout), packages.PINNED_REVISION)
                args, kwargs = run.call_args
                self.assertEqual(args[0][-3:], ["rev-parse", "--show-toplevel", "HEAD"])
                self.assertNotIn("GIT_DIR", kwargs["env"])
                self.assertNotIn("GIT_CONFIG_COUNT", kwargs["env"])
                self.assertTrue(kwargs["check"])

    def test_rejects_parent_repository_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory).resolve() / "not-a-checkout"
            output = subprocess.CompletedProcess([], 0, f"{checkout.parent}\n{packages.PINNED_REVISION}\n", "")
            with patch.object(packages.subprocess, "run", return_value=output):
                with self.assertRaisesRegex(ValueError, "Unexpected checkout repository"):
                    packages.checkout_revision(checkout)


if __name__ == "__main__":
    unittest.main()
