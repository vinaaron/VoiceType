// swift-tools-version:6.2
// VoiceCLIVisual — the Siri-style floating blob that visualises the
// voice-cli daemon's recording sessions. Connects to the daemon's
// Unix socket as a subscriber, listens for level / state events.

import PackageDescription

let package = Package(
    name: "VoiceCLIVisual",
    // macOS 26 (Tahoe) required for SwiftUI .glassEffect() — Liquid Glass.
    platforms: [.macOS(.v26)],
    products: [
        .executable(name: "VoiceCLIVisual", targets: ["VoiceCLIVisual"]),
    ],
    targets: [
        .executableTarget(
            name: "VoiceCLIVisual",
            path: "Sources/VoiceCLIVisual",
            swiftSettings: [
                .swiftLanguageMode(.v5),
            ]
        ),
    ]
)
