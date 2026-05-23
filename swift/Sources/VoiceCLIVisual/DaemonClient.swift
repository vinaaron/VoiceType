import Foundation
import Network

/// Events emitted by the daemon's session pipeline (matches the JSON
/// schema written by src/session.py's _publish() calls).
enum DaemonEvent {
    case subscribed
    case recordingStarted
    case level(value: Double)
    case transcribing
    case pasteDone(text: String)
    case recordingEnded
    case sessionFailed(reason: String)
}

/// Long-lived subscriber to the voice-cli daemon's Unix socket.
/// Sends {"op":"subscribe"} once connected, then parses newline-
/// delimited JSON events. Auto-reconnects with backoff if the daemon
/// goes away (e.g. user restarts it).
///
/// @unchecked Sendable: all mutable state is touched only from the
/// private serial queue (NWConnection callbacks are dispatched there
/// too). UI updates hop to the main queue explicitly via DispatchQueue.
final class DaemonClient: @unchecked Sendable {
    private let socketPath: String
    private let queue = DispatchQueue(label: "voicecli.daemon-client")
    private var connection: NWConnection?
    private var partialBuffer = Data()
    private var reconnectDelay: TimeInterval = 0.5
    private weak var viewModel: HUDViewModel?
    private let onEvent: (DaemonEvent) -> Void

    /// EMA-smoothed level so the blob doesn't jitter on every chunk.
    private var smoothedLevel: Double = 0
    private let smoothing: Double = 0.35  // 0 = no smoothing, 1 = freeze

    init(viewModel: HUDViewModel, onEvent: @escaping (DaemonEvent) -> Void) {
        self.viewModel = viewModel
        self.onEvent = onEvent
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        self.socketPath = "\(home)/.voice-cli/voice-cli.sock"
    }

    func start() {
        connect()
    }

    private func connect() {
        let endpoint = NWEndpoint.unix(path: socketPath)
        let conn = NWConnection(to: endpoint, using: .tcp)
        connection = conn

        conn.stateUpdateHandler = { [weak self] state in
            guard let self else { return }
            switch state {
            case .ready:
                self.reconnectDelay = 0.5
                self.sendSubscribe()
                self.receiveLoop()
            case .failed, .cancelled:
                self.scheduleReconnect()
            default:
                break
            }
        }
        conn.start(queue: queue)
    }

    private func scheduleReconnect() {
        connection?.cancel()
        connection = nil
        let delay = reconnectDelay
        reconnectDelay = min(reconnectDelay * 1.7, 10.0)
        queue.asyncAfter(deadline: .now() + delay) { [weak self] in
            self?.connect()
        }
    }

    private func sendSubscribe() {
        let payload = Data("{\"op\":\"subscribe\"}\n".utf8)
        connection?.send(content: payload, completion: .contentProcessed { _ in })
    }

    private func receiveLoop() {
        connection?.receive(minimumIncompleteLength: 1, maximumLength: 16 * 1024) {
            [weak self] data, _, isComplete, error in
            guard let self else { return }
            if let data, !data.isEmpty {
                self.partialBuffer.append(data)
                self.drainBuffer()
            }
            if isComplete || error != nil {
                self.scheduleReconnect()
                return
            }
            self.receiveLoop()
        }
    }

    /// Pull complete JSON-newline lines out of partialBuffer and dispatch.
    private func drainBuffer() {
        let newline = UInt8(ascii: "\n")
        while let nlIndex = partialBuffer.firstIndex(of: newline) {
            let lineData = partialBuffer[..<nlIndex]
            partialBuffer.removeSubrange(...nlIndex)
            guard !lineData.isEmpty else { continue }
            if let event = parseEvent(Data(lineData)) {
                handle(event)
            }
        }
    }

    private func parseEvent(_ data: Data) -> DaemonEvent? {
        guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        if let state = obj["state"] as? String, state == "subscribed" {
            return .subscribed
        }
        guard let eventName = obj["event"] as? String else { return nil }
        switch eventName {
        case "recording_started": return .recordingStarted
        case "recording_ended":   return .recordingEnded
        case "transcribing":      return .transcribing
        case "session_failed":
            return .sessionFailed(reason: obj["reason"] as? String ?? "")
        case "paste_done":
            return .pasteDone(text: obj["text"] as? String ?? "")
        case "level":
            let raw = (obj["value"] as? Double) ?? 0
            return .level(value: max(0, min(1, raw)))
        default:
            return nil
        }
    }

    private func handle(_ event: DaemonEvent) {
        // Apply EMA smoothing for levels before publishing to SwiftUI.
        if case let .level(value) = event {
            smoothedLevel = smoothing * smoothedLevel + (1 - smoothing) * value
            DispatchQueue.main.async { [weak self] in
                self?.viewModel?.level = CGFloat(self?.smoothedLevel ?? 0)
            }
        }
        if case .recordingStarted = event {
            DispatchQueue.main.async { [weak self] in self?.viewModel?.state = .listening }
        }
        if case .transcribing = event {
            DispatchQueue.main.async { [weak self] in self?.viewModel?.state = .transcribing }
        }
        if case .recordingEnded = event {
            // Stay in "transcribing" visual until the daemon emits paste_done.
        }
        if case .pasteDone = event {
            DispatchQueue.main.async { [weak self] in
                self?.viewModel?.level = 0
                self?.viewModel?.state = .idle
            }
        }
        onEvent(event)
    }
}
