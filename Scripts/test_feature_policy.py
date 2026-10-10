#!/usr/bin/env python3
"""Compile actual application policy functions in a small macOS Swift harness.

This verifies the extracted policy in isolation, not the entire AppKit application.
Use --check-only to validate source extraction when Xcode is unavailable.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def policy_sources(root: Path = ROOT) -> str:
    optimisation = (root / "Clop/OptimisationUtils.swift").read_text()
    begin = optimisation.index("@discardableResult @inline(__always)\n@MainActor func performOptimisation")
    end = optimisation.index("@MainActor func downloadFile", begin)
    permissions = (root / "Clop/MCPSettings.swift").read_text()
    begin_permissions = permissions.index("@MainActor func mcpRefusal")
    installer = (root / "Clop/MCPInstaller.swift").read_text()
    shell_quote = installer[installer.index("func mcpShellQuotedArgument"):]
    return optimisation[begin:end] + "\n" + permissions[begin_permissions:] + "\n" + shell_quote


def harness(root: Path = ROOT) -> str:
    return r'''
import Foundation

enum ClopError: Error { case decompressingBinariesError }
enum TestError: Error { case expected }
@MainActor final class BinaryManager { var decompressingBinaries = false }
@MainActor let BM = BinaryManager()
@MainActor enum Defaults {
    enum Key: Hashable { case mcpEnabled, mcpAllowScriptSteps }
    static var values: [Key: Bool] = [:]
    static subscript(_ key: Key) -> Bool {
        get { values[key] ?? false }
        set { values[key] = newValue }
    }
}
''' + policy_sources(root) + r'''
@main struct PolicyTests {
    @MainActor static func main() async throws {
        precondition(mcpShellQuotedArgument("/Applications/Clop Free.app/Contents/SharedSupport/ClopCLI")
                     == "'/Applications/Clop Free.app/Contents/SharedSupport/ClopCLI'")
        precondition(mcpShellQuotedArgument("/Users/O'Neil/Clop Free.app")
                     == "'/Users/O'\\''Neil/Clop Free.app'")
        var completed = 0
        for value in 0..<50 {
            let result = try await performOptimisation { completed += 1; return value }
            precondition(result == value, "Operation result changed")
        }
        precondition(completed == 50, "Optimisations must not have a five-file limit")

        var entered = false
        BM.decompressingBinaries = true
        do {
            try await performOptimisation { entered = true }
            fatalError("Tool-readiness guard was removed")
        } catch ClopError.decompressingBinariesError {}
        precondition(!entered, "Operation ran before tools were ready")
        BM.decompressingBinaries = false
        do {
            try await performOptimisation { throw TestError.expected }
            fatalError("Operation errors must propagate")
        } catch TestError.expected {}

        precondition(mcpRefusal(origin: nil, pipeline: "runScript(code: x)") == nil)
        precondition(mcpRefusal(origin: "cli", pipeline: nil) == nil)
        precondition(mcpRefusal(origin: "mcp", pipeline: nil) != nil,
                     "MCP changes need the user's opt-in")
        Defaults[.mcpEnabled] = true
        precondition(mcpRefusal(origin: "mcp", pipeline: nil) == nil)
        precondition(mcpRefusal(origin: "mcp", pipeline: "convert(to: webp)") == nil)
        precondition(mcpRefusal(origin: "mcp", pipeline: "runScript(code: x)") != nil,
                     "Script permission must remain separate")
        Defaults[.mcpAllowScriptSteps] = true
        precondition(mcpRefusal(origin: "mcp", pipeline: "runScript(code: x)") == nil)
        Defaults[.mcpEnabled] = false
        precondition(mcpRefusal(origin: "mcp", pipeline: "runScript(code: x)") != nil,
                     "Disabling MCP must revoke changes even when scripts were enabled")
        print("PASS: 50 optimisations, tool readiness, error propagation, MCP and script consent")
    }
}
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    source = harness(args.root)
    if args.check_only:
        print("PASS: extracted production policy functions (runtime tests not run)")
        return
    compiler = shutil.which("swiftc")
    if compiler is None:
        parser.error("swiftc not found; install/select Xcode on macOS or use --check-only")
    with tempfile.TemporaryDirectory(prefix="clop-free-policy-") as directory:
        directory = Path(directory)
        swift = directory / "PolicyTests.swift"
        binary = directory / "PolicyTests"
        swift.write_text(source)
        subprocess.run([compiler, "-swift-version", "5", "-parse-as-library", str(swift), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
