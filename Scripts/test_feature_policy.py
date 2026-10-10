#!/usr/bin/env python3
"""Compile actual application policy and CLI argument functions in a macOS harness.

This verifies extracted functions in isolation, not the entire AppKit application
or MCP transport, video elicitation, path expansion, and command execution.
Use --check-only to validate source extraction when Xcode is unavailable.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def static_function(source: str, name: str) -> str:
    """Extract one complete method using the production file's four-space indent.

    Nested scopes are indented further, so the first equally indented closing
    brace ends the method. Fail if a source refactor changes this convention.
    """
    match = re.search(rf"^    static func {re.escape(name)}\(.*?^    }}$", source, re.MULTILINE | re.DOTALL)
    if match is None:
        raise ValueError(f"Could not extract production method {name}")
    return match.group(0)


def pipeline_argument_sources(root: Path = ROOT) -> str:
    table = (root / "ClopCLI/MCPToolTable.swift").read_text()
    tools = (root / "ClopCLI/MCPTools.swift").read_text()
    methods = [static_function(table, "pipelineRunArguments")]
    methods.extend(static_function(tools, name) for name in ("argument", "opt", "flag"))
    # Only the enclosing type is a stub; the builder and all argument helpers
    # are extracted unchanged so their runtime behavior is checked together.
    return "\nenum MCPServer {\n" + "\n\n".join(methods) + "\n}\n"


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
import CoreFoundation

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
''' + policy_sources(root) + pipeline_argument_sources(root) + r'''
@main struct PolicyTests {
    @MainActor static func main() async throws {
        let pipeline = "changeSpeed(factor: 2, frames: keep) | convert(to: mp4)"
        let files = ["/Users/Test User/a b.mov", "/Users/O'Neil/second.mov", "https://example.com/c%20d.mov"]
        let basicArguments = ["pipeline", "run", pipeline] + files + ["--no-progress"]
        precondition(MCPServer.pipelineRunArguments([:], pipeline: pipeline, files: files) == basicArguments,
                     "Pipeline argv without options must preserve the pipeline and file boundaries")
        let allOptions: [String: Any] = [
            "pipeline": "unsettled input must not replace the selected pipeline",
            "paths": ["raw input must not replace the expanded files"],
            "recursive": true, "skipErrors": true, "hideResult": true,
            "types": "video,image", "optimiseBehaviour": "inPlace", "convertBehaviour": "sameFolder",
        ]
        let fullArguments = [
            "pipeline", "run", pipeline,
            "/Users/Test User/a b.mov", "/Users/O'Neil/second.mov", "https://example.com/c%20d.mov",
            "--recursive", "--skip-errors", "--hide-result", "--types", "video,image",
            "--optimise-behaviour", "inPlace", "--convert-behaviour", "sameFolder", "--no-progress",
        ]
        precondition(MCPServer.pipelineRunArguments(allOptions, pipeline: pipeline, files: files) == fullArguments,
                     "Pipeline argv must retain CLI option order and the settled pipeline and expanded files")
        let unsetOptions: [String: Any] = [
            "recursive": false, "skipErrors": NSNull(), "hideResult": "true",
            "types": NSNull(), "optimiseBehaviour": "", "convertBehaviour": NSNull(),
        ]
        precondition(MCPServer.pipelineRunArguments(unsetOptions, pipeline: pipeline, files: files) == basicArguments,
                     "Pipeline argv must omit unset or empty options and non-boolean flags")
        precondition(MCPServer.pipelineRunArguments(["hideResult": true], pipeline: "Saved pipeline with spaces", files: [files[0]])
                     == ["pipeline", "run", "Saved pipeline with spaces", files[0], "--hide-result", "--no-progress"],
                     "Pipeline argv must handle independently enabled flags and a saved name with spaces")
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
        print("PASS: 50 optimisations, tool readiness, error propagation, MCP and script consent, pipeline CLI arguments")
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
        print("PASS: extracted production policy and CLI argument functions (runtime tests not run)")
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
