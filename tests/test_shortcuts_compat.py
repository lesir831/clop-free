"""Shortcuts compatibility checks, with a native probe test when Swift is available.

The native harness compiles the actual production probe using Foundation only.
It does not run a shortcut or touch the user's real Shortcuts database.
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Clop/ShortcutsCompat.swift"


def database_probe(source=None):
    if source is None:
        source = SOURCE.read_text()
    match = re.search(r"^private func hasShortcutsDB\(.*?^}$", source, re.MULTILINE | re.DOTALL)
    if match is None:
        raise ValueError("Could not extract production hasShortcutsDB function")
    return match.group(0)


class ShortcutsCompatibilityTests(unittest.TestCase):
    def test_database_probe_is_local_and_read_only(self):
        probe = database_probe()
        self.assertIn("NSHomeDirectory()", probe)
        self.assertIn('appendingPathComponent("Library/Shortcuts/Shortcuts.sqlite")', probe)
        self.assertIn("guard #available(macOS 12.0, *) else { return false }", probe)
        self.assertIn("FileManager.default.fileExists(atPath: database.path, isDirectory: &isDirectory)", probe)
        self.assertIn("&& !isDirectory.boolValue", probe)
        self.assertIn("&& FileManager.default.isReadableFile(atPath: database.path)", probe)
        for forbidden in ("return true", "Process(", "shell(", "createFile", "createDirectory",
                          "setAttributes", "chmod", "sqlite3", "requestAccess", "required.swift"):
            self.assertNotIn(forbidden, probe)

    def test_watcher_remains_guarded_and_execution_uses_public_api(self):
        source = SOURCE.read_text()
        self.assertRegex(source, r"func startShortcutWatcher\(\) \{\s*guard hasShortcutsDB\(\) else \{ return }\s*SHM.startWatching\(\)\s*}")
        self.assertIn("return ShortcutsFetcher.run(identifier: shortcut.identifier, inputPath: file, outputPath: outFile)", source)

    def test_harness_extracts_production_probe(self):
        marked = SOURCE.read_text().replace("    var isDirectory", "    // production probe\n    var isDirectory", 1)
        self.assertIn("// production probe", database_probe(marked))
        with self.assertRaisesRegex(ValueError, "hasShortcutsDB"):
            database_probe("import Foundation\n")

    @unittest.skipUnless(shutil.which("swiftc"), "Swift compiler is unavailable")
    def test_native_probe_handles_missing_directory_and_readability(self):
        harness = "import Foundation\n" + database_probe() + r'''

let fm = FileManager.default
let home = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let directory = home.appendingPathComponent("Library/Shortcuts")
let database = directory.appendingPathComponent("Shortcuts.sqlite")
precondition(!hasShortcutsDB(homeDirectory: home), "Missing Shortcuts directory must fail closed")
try fm.createDirectory(at: directory, withIntermediateDirectories: true)
precondition(!hasShortcutsDB(homeDirectory: home), "An empty Shortcuts directory is not a database")
try fm.createDirectory(at: database, withIntermediateDirectories: false)
precondition(!hasShortcutsDB(homeDirectory: home), "A directory named Shortcuts.sqlite is not a database")
try fm.removeItem(at: database)
let original = Data("read-only probe fixture".utf8)
try original.write(to: database)
precondition(hasShortcutsDB(homeDirectory: home), "An existing readable database must enable watching")
let afterProbe = try Data(contentsOf: database)
precondition(afterProbe == original, "The probe must not modify database contents")

try fm.setAttributes([.posixPermissions: 0], ofItemAtPath: database.path)
if fm.isReadableFile(atPath: database.path) {
    // A privileged test process may still read mode-000 files; do not claim a denial test.
    print("SKIP: filesystem denies no reads to this process")
} else {
    precondition(!hasShortcutsDB(homeDirectory: home), "An unreadable database must fail closed")
    let permissions = try fm.attributesOfItem(atPath: database.path)[.posixPermissions] as! NSNumber
    precondition(permissions.intValue == 0, "The probe must not change access permissions")
}
try fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: database.path)
try fm.removeItem(at: database)
precondition(!hasShortcutsDB(homeDirectory: home), "A removed database must disable watching")
print("PASS: production Shortcuts database probe")
'''
        with tempfile.TemporaryDirectory(prefix="clop-free-shortcuts-") as directory:
            directory = Path(directory)
            source = directory / "ShortcutsProbe.swift"
            binary = directory / "ShortcutsProbe"
            home = directory / "Home with spaces"
            home.mkdir()
            source.write_text(harness)
            subprocess.run([shutil.which("swiftc"), "-swift-version", "5", str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary), str(home)], check=True)


if __name__ == "__main__":
    unittest.main()
