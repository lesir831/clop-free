"""Portable tests for signing plans, resource checks, and conservative upstream merges."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import struct
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "Scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


signer = load("sign_app")
assets = load("verify_assets")
validator = load("validate_fork")


class AssetTests(unittest.TestCase):
    def test_verified_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = b"binary resource content"
            (root / "archive").write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            (root / "hash").write_text(digest + "\n")
            self.assertEqual(assets.verify_archive(root / "archive", root / "hash"), digest)

    def test_mismatch_and_pointer_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "hash").write_text("0" * 64)
            for payload, message in [(b"corrupted", "mismatch"), (assets.LFS_HEADER, "Git LFS pointer")]:
                (root / "archive").write_bytes(payload)
                with self.assertRaisesRegex(ValueError, message):
                    assets.verify_archive(root / "archive", root / "hash")


class BuildInvocationTests(unittest.TestCase):
    def test_build_propagates_deployment_target_to_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Scripts").mkdir()
            shutil.copyfile(ROOT / "Scripts/build.sh", root / "Scripts/build.sh")
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            commands = {
                "uname": "#!/bin/bash\nprintf 'Darwin\\n'\n",
                "python3": "#!/bin/bash\nexit 0\n",
                "xcodebuild": (
                    "#!/bin/bash\n"
                    "if [[ $1 == -version ]]; then printf 'Xcode 26.3\\n'; exit 0; fi\n"
                    "printf '%s\\n' \"$@\" >> \"$XCODE_TEST_LOG\"\n"
                    "for arg in \"$@\"; do if [[ $arg == -resolvePackageDependencies ]]; then exit 0; fi; done\n"
                    "exit 73\n"
                ),
            }
            for name, source in commands.items():
                command = fake_bin / name
                command.write_text(source)
                command.chmod(0o755)
            log = root / "xcode-arguments.txt"
            env = os.environ.copy()
            env.update(PATH=str(fake_bin) + os.pathsep + env["PATH"],
                       XCODE_TEST_LOG=str(log), BUILD_DIR=str(root / "build"))
            env.pop("NOTARY_PROFILE", None)
            env.pop("SIGN_IDENTITY", None)
            env.pop("CONFIGURATION", None)
            result = subprocess.run(["bash", "Scripts/build.sh"], cwd=root, env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 73, result.stdout + result.stderr)
            args = log.read_text().splitlines()
            self.assertIn("MACOSX_DEPLOYMENT_TARGET=13.0", args)
            self.assertNotIn("SWIFT_ENABLE_EXPLICIT_MODULES=NO", args)
            self.assertEqual(args.count("-onlyUsePackageVersionsFromResolvedFile"), 2)
            self.assertLess(args.index("-resolvePackageDependencies"), args.index("build"))
            self.assertIn("CODE_SIGNING_ALLOWED=NO", args)


class SigningTests(unittest.TestCase):
    def test_process_entitlements_only_for_executables(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, filetype in (("tool", 2), ("lib.dylib", 6), ("plugin.bundle", 8)):
                path = root / name
                path.write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 8 + struct.pack("<I", filetype) + b"\0" * 16)
                self.assertEqual(signer.is_executable_macho(path), filetype == 2)
            universal = root / "universal"
            header = b"\xca\xfe\xba\xbe" + struct.pack(">I", 2)
            header += struct.pack(">IIIII", 0, 0, 48, 32, 0)
            header += struct.pack(">IIIII", 0, 0, 80, 32, 0)
            universal.write_bytes(header + (root / "tool").read_bytes() * 2)
            self.assertTrue(signer.is_executable_macho(universal))
            universal.write_bytes(header + (root / "tool").read_bytes() + (root / "lib.dylib").read_bytes())
            self.assertFalse(signer.is_executable_macho(universal))

    def test_explicit_inside_out_signing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Clop Free.app"
            binary = root / "Contents/Frameworks/Example.framework/Versions/A/Example"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"\xcf\xfa\xed\xfe" + b"x" * 10)
            alias = binary.parent / "Alias"
            alias.symlink_to(binary.name)
            order = signer.signing_order(root)
            framework = root / "Contents/Frameworks/Example.framework"
            self.assertLess(order.index(binary), order.index(framework))
            self.assertNotIn(alias, order)
            self.assertNotIn(root, order)

    def test_default_ad_hoc_and_optional_developer_id(self):
        ad_hoc = signer.sign_command(Path("Example.app"), "-")
        self.assertIn("--timestamp=none", ad_hoc)
        self.assertEqual(ad_hoc[ad_hoc.index("--options") + 1], "0")
        self.assertNotIn("--deep", ad_hoc)
        developer = signer.sign_command(Path("Example.app"), "Developer ID Application: Example", Path("e.plist"))
        self.assertIn("--timestamp", developer)
        self.assertEqual(developer[developer.index("--options") + 1], "runtime")
        self.assertIn("--entitlements", developer)
        self.assertNotIn("--deep", developer)

    def test_notary_rejection_never_staples(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "Clop Free.app"
            (app / "Contents").mkdir(parents=True)
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.clop-free.Clop"}))
            calls = []

            def fake_run(*args, **kwargs):
                calls.append(args)
                if args[:2] == ("codesign", "--display"):
                    return subprocess.CompletedProcess(args, 0, "", "Authority=Developer ID Application: Example\n")
                if args[:3] == ("xcrun", "notarytool", "submit"):
                    return subprocess.CompletedProcess(args, 0, json.dumps({"status": "Invalid", "id": "test"}), "")
                return subprocess.CompletedProcess(args, 0, "", "")

            with patch.object(signer, "prepare_helpers"), patch.object(signer, "run", side_effect=fake_run):
                with self.assertRaisesRegex(ValueError, "not accepted"):
                    signer.sign_app(app, "Developer ID Application: Example", "existing-profile")
            self.assertFalse(any("stapler" in call for call in calls))

    def test_notarization_rejects_ad_hoc(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "Example.app"
            (app / "Contents").mkdir(parents=True)
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.clop-free.Clop"}))
            with self.assertRaisesRegex(ValueError, "Developer ID"):
                signer.sign_app(app, "-", "profile")


class ArchiveTests(unittest.TestCase):
    def make_archive(self, root, entries):
        archive = root / "input.tar"
        with tarfile.open(archive, "w") as stream:
            for name, link in entries:
                info = tarfile.TarInfo(name)
                if link is not None:
                    info.type = tarfile.SYMTYPE
                    info.linkname = link
                    stream.addfile(info)
                else:
                    info.size = 4
                    info.mode = 0o4755
                    stream.addfile(info, io.BytesIO(b"data"))
        return archive

    def test_safe_files_and_relative_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self.make_archive(root, [("arm64/helper", None), ("arm64/alias", "helper")])
            signer.extract_safe(archive, root / "out")
            self.assertEqual((root / "out/arm64/alias").read_bytes(), b"data")
            self.assertEqual((root / "out/arm64/helper").stat().st_mode & 0o4000, 0)

    def test_safe_sibling_directory_links(self):
        entries = [("arm64/lib", "../lib"), ("x86/lib", "../lib"),
                   ("arch/nested/lib", "../../lib"), ("lib/helper", None)]
        for ordered_entries in (entries, list(reversed(entries))):
            with self.subTest(entries=ordered_entries), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive = self.make_archive(root, ordered_entries)
                destination = root / "out"
                signer.extract_safe(archive, destination)
                for name, target in entries[:-1]:
                    link = destination / name
                    self.assertTrue(link.is_symlink())
                    self.assertEqual(os.readlink(link), target)
                    self.assertEqual(link.resolve(), (destination / "lib").resolve())
                    self.assertEqual((link / "helper").read_bytes(), b"data")

    def test_path_and_link_traversal_rejected_before_extraction(self):
        attacks = [
            [("../escape", None)], [("/absolute", None)],
            [("link", "../escape")], [("link", "safe"), ("link/file", None)],
            [("duplicate", None), ("duplicate", None)],
            [("link", "inside/../sibling")],
            [("arm64/lib", "../../escape")], [("arm64/lib", "../..")],
            [("arm64/lib", "/absolute")],
            [("arm64/lib", "../inside/../sibling")],
            [("arm64/lib", "../alias/../escape"), ("alias", ".")],
            [("arm64", "safe"), ("arm64/lib", "../lib")],
            [("arm64/lib", "../lib"), ("arm64/lib/helper", None)],
        ]
        for entries in attacks:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive = self.make_archive(root, entries)
                with self.assertRaises(ValueError):
                    signer.extract_safe(archive, root / "out")
                self.assertFalse((root / "out").exists())


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Build Tool Test")
        self.git("config", "user.email", "test@example.invalid")
        (self.root / ".gitignore").write_text("build/\n")
        for directory in ("Scripts", "Clop", "ClopCLI", "Clop.xcodeproj"):
            (self.root / directory).mkdir()
        for name in ("sync-upstream.sh", "validate_fork.py"):
            shutil.copyfile(ROOT / "Scripts" / name, self.root / "Scripts" / name)
        shutil.copyfile(ROOT / "LICENSE", self.root / "LICENSE")
        for name in ("Clop/ClopApp.swift", "Clop/OptimisationUtils.swift", "Shared.swift"):
            (self.root / name).write_text("// independent source\n")
        (self.root / "Scripts/test_feature_policy.py").write_text("# checked by macOS CI\n")
        (self.root / "Clop.xcodeproj/project.pbxproj").write_text(
            "PRODUCT_BUNDLE_IDENTIFIER = com.clop-free.Clop;\n"
            "PRODUCT_BUNDLE_IDENTIFIER = com.clop-free.Clop.CLI;\nDEVELOPMENT_TEAM = \"\";\n")
        for name in ("Clop/Info.plist", "Clop/Clop.entitlements", "ClopCLI/ClopCLI.entitlements"):
            (self.root / name).write_bytes(plistlib.dumps({}))
        (self.root / "shared.txt").write_text("base\n")
        self.commit("common base")
        self.git("branch", "upstream")
        (self.root / "fork.txt").write_text("preserve fork behavior\n")
        self.commit("fork change")
        self.original = self.git("rev-parse", "HEAD").stdout.strip()

    def git(self, *args, check=True):
        return subprocess.run(["git", *args], cwd=self.root, text=True, capture_output=True, check=check)

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "-qm", message)

    def upstream_change(self, path="upstream.txt", content="new upstream behavior\n"):
        self.git("checkout", "-q", "upstream")
        (self.root / path).write_text(content)
        self.commit("upstream change")
        self.git("checkout", "-q", "main")

    def sync(self):
        env = os.environ.copy()
        env["UPSTREAM_REF"] = "upstream"
        env.pop("GITHUB_OUTPUT", None)
        env.pop("SYNC_OUTPUT_DIR", None)
        return subprocess.run(["bash", "Scripts/sync-upstream.sh"], cwd=self.root,
                              env=env, text=True, capture_output=True)

    def assert_untouched(self):
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.original)
        self.assertEqual(self.git("branch", "--show-current").stdout.strip(), "main")
        self.assertEqual(self.git("status", "--porcelain").stdout, "")
        self.assertEqual(len(self.git("worktree", "list", "--porcelain").stdout.split("worktree ")) - 1, 1)

    def test_merge_preserves_fork_and_includes_upstream(self):
        self.upstream_change()
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        metadata = json.loads((self.root / "build/upstream-sync/candidate.json").read_text())
        self.assertEqual(self.git("show", f"{metadata['candidate']}:fork.txt").stdout, "preserve fork behavior\n")
        self.assertEqual(self.git("show", f"{metadata['candidate']}:upstream.txt").stdout, "new upstream behavior\n")
        self.assertEqual(self.git("rev-parse", f"{metadata['candidate']}^1").stdout.strip(), self.original)
        self.assertTrue((self.root / "build/upstream-sync/candidate.bundle").is_file())
        self.assert_untouched()

    def test_conflict_leaves_no_candidate(self):
        (self.root / "shared.txt").write_text("fork version\n")
        self.commit("fork edit")
        self.original = self.git("rev-parse", "HEAD").stdout.strip()
        self.upstream_change("shared.txt", "upstream version\n")
        result = self.sync()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("shared.txt", (self.root / "build/upstream-sync/conflicts.txt").read_text())
        self.assertEqual(self.git("branch", "--list", "sync/*").stdout, "")
        self.assert_untouched()

    def test_restored_gate_fails_validation(self):
        self.upstream_change("Clop/ClopApp.swift", "func proactive() {}\n")
        result = self.sync()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("legacy paid gate", result.stderr)
        self.assertEqual(self.git("branch", "--list", "sync/*").stdout, "")
        self.assert_untouched()

    def test_numbered_gate_and_count_budget_fail_validation(self):
        self.upstream_change("Clop/ClopApp.swift", "func invalidReq2() {}\nlet remaining = count.take()\n")
        result = self.sync()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("legacy paid gate", result.stderr)
        self.assertEqual(self.git("branch", "--list", "sync/*").stdout, "")
        self.assert_untouched()

    def test_validation_cannot_replace_itself(self):
        self.upstream_change("Scripts/validate_fork.py", "print('pretend everything is safe')\n")
        result = self.sync()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("protected build/test controls", result.stderr)
        self.assertNotIn("pretend everything is safe", result.stdout)
        self.assert_untouched()

    def test_already_current_is_noop(self):
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("already included", result.stdout)
        self.assertEqual(self.git("branch", "--list", "sync/*").stdout, "")
        self.assert_untouched()

    def test_dirty_checkout_rejected(self):
        (self.root / "untracked.txt").write_text("keep me")
        result = self.sync()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("clean working tree", result.stderr)
        self.assertEqual((self.root / "untracked.txt").read_text(), "keep me")


class WorkflowTests(unittest.TestCase):
    def test_ci_withholds_binary_upload_pending_license_review(self):
        text = (ROOT / ".github/workflows/build.yml").read_text()
        self.assertIn("run: make package", text)
        self.assertNotIn("actions/upload-artifact", text)
        self.assertNotIn("git archive", text)

    def test_no_mutating_pr_target_workflow_or_secrets(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            text = path.read_text()
            self.assertNotIn("pull_request_target", text)
            self.assertNotIn("secrets.", text)
            for line in text.splitlines():
                if "uses: actions/" in line:
                    self.assertRegex(line, r"@[a-f0-9]{40}\s")

    def test_publish_job_never_executes_candidate_code(self):
        text = (ROOT / ".github/workflows/upstream-sync.yml").read_text()
        publish = text.split("  propose:", 1)[1]
        self.assertNotIn("run: make", publish)
        self.assertNotIn("run: python", publish)
        self.assertNotIn("--force", publish)
        self.assertIn("--draft", publish)
        self.assertIn("needs.validate.result == 'success'", publish)


if __name__ == "__main__":
    unittest.main()
