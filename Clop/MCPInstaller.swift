import AppKit
import Defaults
import Foundation
import os

private let mcpLog = Logger(subsystem: Bundle.main.bundleIdentifier ?? "com.clop-free.Clop", category: "MCP")

// MARK: - MCPInstaller

/// Registers Clop's MCP server with the agents people actually use, by merging one entry into each
/// client's own config file. Everything else in those files is preserved: they are read, one key is
/// added, and they are written back.
///
/// The clients and the editing live in `MCPClients.swift`, shared as is with rcmd, Lunar and Crank.
/// This half is what is Clop's own.
enum MCPInstaller {
    // MARK: - State

    enum InstallError: LocalizedError {
        case missingServer

        var errorDescription: String? {
            switch self {
            case .missingServer: "Clop's CLI is missing from the app bundle, so the MCP server cannot run."
            }
        }
    }

    static let serverName = "clop-free"

    /// The arguments that turn the CLI into the server.
    static let serveArgs = ["mcp", "serve"]

    // MARK: - Paths

    /// The CLI, which IS the MCP server. Bundled beside the app, so an agent drives the same binary
    /// the user's own `clop` command does.
    ///
    /// It used to be a bundled script that needed an interpreter found at launch, and on a Mac with
    /// no Command Line Tools and no Homebrew the server did not run at all. The CLI is already
    /// signed with the app according to the chosen build mode.
    static var cliPath: String {
        let bundled = Bundle.main.bundleURL
            .appendingPathComponent("Contents/SharedSupport/ClopCLI").path
        if FileManager.default.isExecutableFile(atPath: bundled) {
            return bundled
        }
        return ("~/.local/bin/clop-free" as NSString).expandingTildeInPath
    }

    /// Whether the server can actually run. Installing without it writes a config entry that looks
    /// fine and starts nothing, so every caller checks this first.
    static var scriptExists: Bool {
        FileManager.default.isExecutableFile(atPath: cliPath)
    }

    /// The one-liner for a client that is driven from a terminal.
    static var cliCommand: String {
        "claude mcp add --scope user clop-free -- \(mcpShellQuotedArgument(cliPath)) \(serveArgs.joined(separator: " "))"
    }

    static var cardURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".well-known/mcp/clop-free.json")
    }

    static var supportDirectory: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Clop Free", isDirectory: true)
    }

    // MARK: - The switch

    @MainActor static func setEnabled(_ enabled: Bool) {
        Defaults[.mcpEnabled] = enabled
        writeServerCard()
        mcpLog.info("MCP \(enabled ? "enabled" : "disabled", privacy: .public)")
    }

    /// Handles `clop-free://mcp/start` and `clop-free://mcp/stop`. Returns false for a URL that is not ours, so
    /// the caller can keep handling it.
    ///
    /// Start ASKS. The URL is what an agent opens when a tool of its own was refused, so nothing but
    /// this alert stands between "an agent decided to" and the switch being on. Turning it back on
    /// behind someone who just turned it off would make every line of copy about this a lie. Stop
    /// needs no alert: it only ever takes permission away.
    @MainActor static func handle(url: URL) -> Bool {
        guard url.scheme == "clop-free", url.host == "mcp" else { return false }
        switch url.lastPathComponent {
        case "start":
            guard !Defaults[.mcpEnabled] else { return true }
            if askToEnable() {
                setEnabled(true)
            }
        case "stop": setEnabled(false)
        default: return false
        }
        return true
    }

    // MARK: - Server card

    /// A card an agent can read to find Clop, written on every launch whether or not the switch is on.
    ///
    /// There is no shipped standard for discovering a local MCP server, so this follows the shape of
    /// the proposed `.well-known/mcp` card and drops it in two places an agent is likely to look. It
    /// carries no credentials: Clop's transport is a Mach port that any process of this user can
    /// already open.
    ///
    @MainActor static func writeServerCard() {
        let card: [String: Any] = [
            "name": serverName,
            "displayName": "Clop Free",
            "description": "Image, video, PDF and audio optimisation. Run pipelines over files, downscale, convert, crop, author new pipelines, and read or change any Clop setting.",
            "version": Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?",
            "app": ["bundleID": "com.clop-free.Clop", "path": Bundle.main.bundlePath],
            "enabled": Defaults[.mcpEnabled],
            "requiresPro": false,
            "edition": "free",
            "transport": [
                "type": "stdio",
                "command": cliPath,
                "args": serveArgs,
            ],
            "control": [
                "start": "open clop-free://mcp/start",
                "stop": "open clop-free://mcp/stop",
                "note": "Reading works whether or not MCP is started; changes are refused until the user enables it. Starting sticks across launches until it is stopped.",
            ],
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: card, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]) else { return }

        // Both cards go through the symlink resolver for the same reason the client configs do:
        // `~/.well-known` is a folder people keep in a dotfiles repo.
        for url in [supportDirectory.appendingPathComponent("mcp.json"), cardURL].map(resolvedConfigURL) {
            try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try? data.write(to: url)
        }
    }

    /// Whether an entry names something that is no longer on disk.
    ///
    /// The test is "does this still work", not "does this match what Clop would write now". An entry
    /// pointing at another copy of Clop is somebody's deliberate choice, and repointing it because
    /// this copy launched from somewhere else would hijack a working config. Running a build out of
    /// a temp folder once did exactly that during testing.
    static func entryIsBroken(_ command: String, _ args: [String]) -> Bool {
        guard FileManager.default.isExecutableFile(atPath: command) else { return true }
        // Only arguments that are absolute paths, so `mcp` and `serve` are never mistaken for files.
        return args.contains { $0.hasPrefix("/") && !FileManager.default.fileExists(atPath: $0) }
    }

    /// Repairs entries that no longer start anything.
    ///
    /// 3.4.0 moved the server from a bundled Python script into the CLI, so every config written
    /// before it names an interpreter and a `clop_mcp.py` that the update deleted. Nothing would have
    /// told those users: the member is still called `clop`, so Settings kept saying Installed while
    /// the agent's server failed to start.
    ///
    /// Only entries that already exist and are already broken are touched. This never installs Clop
    /// into a client the user did not choose, and never moves one that still works.
    static func migrateInstalledClients() {
        guard scriptExists else { return }

        for client in clients {
            guard let current = installedCommand(client), entryIsBroken(current.command, current.args) else { continue }
            mcpLog.info("Repairing dead MCP entry in \(client.name, privacy: .public): \(current.command, privacy: .public)")
            _ = install(client)
        }
    }

    @MainActor private static func askToEnable() -> Bool {
        let alert = NSAlert()
        alert.messageText = "Let agents control Clop through MCP?"
        alert.informativeText = """
        An AI agent asked for MCP access which allows it to optimise, convert and downscale your files, change any setting, and write or run pipelines.

        You can also toggle this in Clop's Settings -> MCP.
        """
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Allow")
        alert.addButton(withTitle: "Not now")
        NSApp.activate(ignoringOtherApps: true)
        return alert.runModal() == .alertFirstButtonReturn
    }
}

/// Quote one argument for a POSIX shell, including app names with spaces or apostrophes.
func mcpShellQuotedArgument(_ value: String) -> String {
    "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
}
