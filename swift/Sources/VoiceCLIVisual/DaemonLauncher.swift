import Foundation

/// Spawns the Python voice-cli daemon if it isn't already running.
/// Port of voice-cli-client's `spawn_daemon_in_background` — done in
/// Swift so VoiceCLIVisual.app becomes the responsible process for
/// TCC. macOS will prompt the user once for Accessibility +
/// Microphone permissions; future daemons inherit that grant.
enum DaemonLauncher {
    /// Defaults match Aaron's setup. Customise via env vars if needed.
    static let pythonPath = ProcessInfo.processInfo.environment["VOICE_CLI_PYTHON"]
        ?? "/Users/avini/.voice-cli-venv/bin/python"
    static let repoSrc = ProcessInfo.processInfo.environment["VOICE_CLI_SRC"]
        ?? "/Users/avini/Documents/GitHub/voice-cli/src"

    static var socketPath: String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return "\(home)/.voice-cli/voice-cli.sock"
    }

    static var daemonPidfile: String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return "\(home)/.voice-cli/daemon.pid"
    }

    /// True if the daemon socket exists AND a process is alive at the
    /// recorded PID. (The socket alone can be a leftover from a crashed
    /// daemon.)
    static func isDaemonAlive() -> Bool {
        guard FileManager.default.fileExists(atPath: socketPath) else { return false }
        guard let pidStr = try? String(contentsOfFile: daemonPidfile, encoding: .utf8) else {
            return false
        }
        let trimmed = pidStr.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let pid = pid_t(trimmed), pid > 0 else { return false }
        // kill(pid, 0) returns 0 if the process exists.
        return kill(pid, 0) == 0
    }

    /// Spawn the daemon in the background. Returns immediately —
    /// the daemon takes ~1.5s to preload models before it can serve
    /// commands.
    static func spawn() {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: pythonPath)
        task.arguments = ["-m", "daemon"]
        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = repoSrc + (env["PYTHONPATH"].map { ":\($0)" } ?? "")
        task.environment = env

        // Redirect stdio to the daemon stderr log so we don't tie up
        // VoiceCLIVisual's lifetime to the daemon's stdout pipe.
        let home = FileManager.default.homeDirectoryForCurrentUser
        let logURL = home.appendingPathComponent(".voice-cli/daemon.stderr.log")
        try? FileManager.default.createDirectory(
            at: logURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        // Open for appending (create if missing).
        let fd = open(logURL.path, O_WRONLY | O_CREAT | O_APPEND, 0o644)
        if fd >= 0 {
            let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
            task.standardOutput = handle
            task.standardError = handle
        }

        do {
            try task.run()
            NSLog("VoiceCLIVisual: spawned daemon pid=\(task.processIdentifier)")
        } catch {
            NSLog("VoiceCLIVisual: failed to spawn daemon: \(error)")
        }
    }

    /// Ensure a daemon exists. Spawns one if not. Caller may want to
    /// wait briefly before sending commands so the daemon binds the
    /// socket; in practice the OS schedules the new process quickly
    /// enough that the first user-driven send arrives well after.
    static func ensureRunning() {
        if isDaemonAlive() { return }
        spawn()
    }
}
