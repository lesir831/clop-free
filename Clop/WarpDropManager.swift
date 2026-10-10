import Cocoa
import Combine
import Foundation
import os

private let log = Logger(subsystem: LOG_SUBSYSTEM, category: "WarpDrop")

/// Upstream references an author-local package that is not part of this source tree.
/// Clop Free does not silently contact the upstream relay or claim to create a link.
/// The session model remains so existing settings and pipeline files still decode.
let WARP_DROP_AVAILABLE = false
let WARP_DROP_UNAVAILABLE_MESSAGE = "Secure link sharing is unavailable in Clop Free because no independent sharing backend is configured. Use AirDrop or another sharing app."

// MARK: - Link expiration

/// Snap points for the "link expires after" picker, 1 minute up to 3 days.
/// The transfer is peer-to-peer (the room is only alive while this Mac serves it), so
/// "expiring" a link means automatically stopping the session after this interval.
let LINK_EXPIRATION_PRESETS: [TimeInterval] = [
    60, 2 * 60, 5 * 60, 10 * 60, 15 * 60, 30 * 60, 45 * 60,
    3600, 2 * 3600, 3 * 3600, 6 * 3600, 12 * 3600,
    86400, 2 * 86400, 3 * 86400,
]

/// Sentinel for "never expire" (the link lives until the app quits or it is stopped manually).
let LINK_EXPIRATION_NEVER: TimeInterval = 0

func nearestExpirationPresetIndex(_ t: TimeInterval) -> Int {
    LINK_EXPIRATION_PRESETS.indices.min(by: { abs(LINK_EXPIRATION_PRESETS[$0] - t) < abs(LINK_EXPIRATION_PRESETS[$1] - t) }) ?? 0
}

/// Long label for menus/overlays: "1 minute", "45 minutes", "1 hour", "3 days".
func expirationDurationLabel(_ t: TimeInterval) -> String {
    let s = Int(t.rounded())
    guard s > 0 else { return "never" }
    if s % 86400 == 0 { let d = s / 86400; return "\(d) day\(d == 1 ? "" : "s")" }
    if s % 3600 == 0 { let h = s / 3600; return "\(h) hour\(h == 1 ? "" : "s")" }
    let m = max(1, s / 60); return "\(m) minute\(m == 1 ? "" : "s")"
}

/// Short label for compact buttons: 1m, 45m, 1h, 3d (∞ for never).
func expirationShortLabel(_ t: TimeInterval) -> String {
    let s = Int(t.rounded())
    guard s > 0 else { return "∞" }
    if s % 86400 == 0 { return "\(s / 86400)d" }
    if s % 3600 == 0 { return "\(s / 3600)h" }
    return "\(max(1, s / 60))m"
}

/// Parse a duration token like "30s", "5m", "1h", "2d", "never" (the copyLinkForSending step param).
func parseExpirationDuration(_ str: String) -> TimeInterval? {
    let s = str.trimmingCharacters(in: .whitespaces).lowercased()
    if s == "never" || s == "0" { return 0 }
    let units: [(String, TimeInterval)] = [("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]
    for (suffix, mult) in units where s.hasSuffix(suffix) {
        if let n = Double(s.dropLast(suffix.count)), n >= 0 { return n * mult }
    }
    if let n = Double(s), n >= 0 { return n } // bare seconds
    return nil
}

struct WarpDropSession: Identifiable {
    let id: String // room ID
    let files: [URL]
    let task: Task<String, Error>
    var downloadCount = 0
    /// When the link auto-stops, or nil for no expiration.
    var expiresAt: Date?

    /// Human label for the remaining time, e.g. "Expires in 42 minutes". nil when no expiration.
    var expiresInLabel: String? {
        guard let expiresAt else { return nil }
        let remaining = expiresAt.timeIntervalSinceNow
        guard remaining > 0 else { return "Expiring now" }
        return "Expires in \(expirationDurationLabel(remaining))"
    }

    /// A future independent provider must supply its real URLs explicitly.
    let directURL: String
    let roomURL: String

    var shareURL: String {
        files.count == 1 ? directURL : roomURL
    }

    var fileNames: String {
        files.map(\.lastPathComponent).joined(separator: ", ")
    }

    func copyLink() {
        withGeneralPasteboard { pb in
            pb.clearContents()
            pb.setString(shareURL, forType: .string)
        }
    }

    func stop() {
        task.cancel()
    }
}

@MainActor
class WarpDropManager: ObservableObject {
    static let shared = WarpDropManager()

    @Published private(set) var sessions: [WarpDropSession] = []

    var hasSessions: Bool {
        !sessions.isEmpty
    }

    func session(forPath path: String) -> WarpDropSession? {
        sessions.first { s in s.files.contains { $0.path == path } }
    }

    func session(forOptimiser optimiser: Optimiser) -> WarpDropSession? {
        guard let path = optimiser.url?.path else { return nil }
        return session(forPath: path)
    }

    /// Change the expiration of a live session (from the active-link menu).
    func rescheduleExpiry(_ session: WarpDropSession, to expiration: TimeInterval) {
        guard let idx = sessions.firstIndex(where: { $0.id == session.id }) else { return }
        let newExpiry = expiration > 0 ? Date().addingTimeInterval(expiration) : nil
        sessions[idx].expiresAt = newExpiry
        scheduleExpiry(roomID: session.id, expiresAt: newExpiry)
    }

    func stopSession(_ session: WarpDropSession) {
        expiryTimers[session.id]?.cancel()
        expiryTimers[session.id] = nil
        session.stop()
        sessions.removeAll { $0.id == session.id }
    }

    func stopAll() {
        for timer in expiryTimers.values {
            timer.cancel()
        }
        expiryTimers.removeAll()
        for session in sessions {
            session.stop()
        }
        sessions.removeAll()
    }

    /// Auto-stop timers keyed by room ID. Cancelled when a session is stopped early or re-scheduled.
    private var expiryTimers: [String: Task<Void, Never>] = [:]

    /// (Re)arm the auto-stop timer for a room. A nil date disarms it (no expiration).
    private func scheduleExpiry(roomID: String, expiresAt: Date?) {
        expiryTimers[roomID]?.cancel()
        expiryTimers[roomID] = nil
        guard let expiresAt else { return }

        expiryTimers[roomID] = Task { @MainActor [weak self] in
            let delay = max(0, expiresAt.timeIntervalSinceNow)
            try? await Task.sleep(for: .seconds(delay))
            guard !Task.isCancelled, let self, let session = sessions.first(where: { $0.id == roomID }) else { return }
            log.debug("WarpDrop link expired, stopping room \(roomID)")
            stopSession(session)
        }
    }

}

@MainActor let WDM = WarpDropManager.shared

@MainActor
private func reportUnavailableSharing(_ optimiser: Optimiser) {
    optimiser.warpDropConnecting = false
    optimiser.overlayMessage = WARP_DROP_UNAVAILABLE_MESSAGE
    log.error("\(WARP_DROP_UNAVAILABLE_MESSAGE, privacy: .public)")
}

@MainActor
func warpDropSend(optimiser: Optimiser, expiration _: TimeInterval? = nil) {
    reportUnavailableSharing(optimiser)
}

@MainActor
func warpDropSend(optimisers: [Optimiser], expiration _: TimeInterval? = nil) {
    for optimiser in optimisers {
        reportUnavailableSharing(optimiser)
    }
}

/// Always fails explicitly while no independent provider is configured. In particular,
/// this does not overwrite the clipboard with a fabricated or upstream service URL.
@MainActor
func warpDropSendAndWait(url _: URL, optimiser: Optimiser, expiration _: TimeInterval? = nil) async -> String? {
    reportUnavailableSharing(optimiser)
    return nil
}
