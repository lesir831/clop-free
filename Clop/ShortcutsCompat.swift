import Cocoa
import Combine
import Defaults
import Foundation
import Lowtech
import os
import SwiftUI

private let log = Logger(subsystem: LOG_SUBSYSTEM, category: "ShortcutsCompat")

func runShortcutProcess(_ shortcut: Shortcut, _ file: String, outFile: String) -> Process? {
    log.debug("Running shortcut \(shortcut.identifier) on \(file) -> \(outFile)")
    return ShortcutsFetcher.run(identifier: shortcut.identifier, inputPath: file, outputPath: outFile)
}

/// Probe the same database watched by Lowtech without opening it or requesting access.
/// Missing or inaccessible databases leave watching disabled; Shortcuts execution
/// continues to use the public `/usr/bin/shortcuts` interface through Lowtech.
private func hasShortcutsDB(homeDirectory: URL = URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)) -> Bool {
    guard #available(macOS 12.0, *) else { return false }
    let database = homeDirectory.appendingPathComponent("Library/Shortcuts/Shortcuts.sqlite")
    var isDirectory = ObjCBool(false)
    return FileManager.default.fileExists(atPath: database.path, isDirectory: &isDirectory)
        && !isDirectory.boolValue
        && FileManager.default.isReadableFile(atPath: database.path)
}

func startShortcutWatcher() {
    guard hasShortcutsDB() else { return }
    SHM.startWatching()
}
