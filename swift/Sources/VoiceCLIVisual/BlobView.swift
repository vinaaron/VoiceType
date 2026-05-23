import SwiftUI

/// Audio-reactive blob that morphs with the user's voice level, sitting
/// inside a macOS 26 Liquid-Glass circular pill. The blob and halo are
/// sized to comfortably fit inside the glass so nothing ever clips.
struct BlobView: View {
    @ObservedObject var viewModel: HUDViewModel

    /// Outer pill diameter. Everything is sized as a fraction of this so
    /// changing it scales the whole thing without re-tuning constants.
    private let pillSize: CGFloat = 96

    /// Maximum radius the blob+halo can reach. Kept comfortably inside
    /// `pillSize / 2` so the blob never touches the glass edge.
    private var maxOuterRadius: CGFloat { pillSize * 0.42 }

    private let pointCount = 64

    var body: some View {
        ZStack {
            TimelineView(.animation(minimumInterval: 1.0 / 60.0)) { context in
                Canvas { ctx, size in
                    let now = context.date.timeIntervalSinceReferenceDate
                    draw(ctx: &ctx, size: size, now: now)
                }
                .frame(width: pillSize, height: pillSize)
            }
        }
        .frame(width: pillSize, height: pillSize)
        .glassEffect(.regular.tint(tint).interactive(false), in: .circle)
        // Outer frame leaves a tiny breathing margin around the glass so
        // soft glass-edge bloom isn't clipped by the NSPanel boundary.
        .frame(width: pillSize + 12, height: pillSize + 12)
        .allowsHitTesting(false)
    }

    private var tint: Color {
        switch viewModel.state {
        case .idle:         return Color.white.opacity(0.06)
        case .listening:    return Color(red: 0.45, green: 0.55, blue: 0.95).opacity(0.18)
        case .transcribing: return Color(red: 0.95, green: 0.55, blue: 0.35).opacity(0.18)
        }
    }

    private func draw(ctx: inout GraphicsContext, size: CGSize, now: TimeInterval) {
        let center = CGPoint(x: size.width / 2, y: size.height / 2)
        let level = Double(viewModel.level)

        // Energy controls wobble. Cap it tightly so the blob never grows
        // past `maxOuterRadius` (which is well inside the glass).
        let energy: Double
        switch viewModel.state {
        case .idle:         energy = 0.06
        case .listening:    energy = 0.10 + level * 0.35
        case .transcribing: energy = 0.22
        }
        let spinSpeed: Double = (viewModel.state == .transcribing) ? 1.5 : 0.42
        let t = now * spinSpeed

        // Base radius shrinks slightly as energy/level rises so the blob
        // breathes within a fixed bounding circle instead of expanding it.
        let bumpFromLevel = level * (Double(maxOuterRadius) * 0.18)
        let baseRadius = Double(maxOuterRadius) * 0.62

        var points: [CGPoint] = []
        points.reserveCapacity(pointCount)
        for i in 0..<pointCount {
            let angle = (Double(i) / Double(pointCount)) * 2.0 * .pi
            let n1 = sin(angle * 3 + t * 1.0) * 0.6
            let n2 = sin(angle * 5 - t * 1.3) * 0.3
            let n3 = sin(angle * 7 + t * 0.7) * 0.15
            let wobble = (n1 + n2 + n3) * energy
            let r = baseRadius * (1 + wobble) + bumpFromLevel
            // Defensive clamp — never let the blob exceed our budget.
            let clampedR = min(r, Double(maxOuterRadius) * 0.95)
            let x = center.x + cos(angle) * clampedR
            let y = center.y + sin(angle) * clampedR
            points.append(CGPoint(x: x, y: y))
        }

        var path = Path()
        let n = points.count
        let m0 = midpoint(points[n - 1], points[0])
        path.move(to: m0)
        for i in 0..<n {
            let p = points[i]
            let next = points[(i + 1) % n]
            let m = midpoint(p, next)
            path.addQuadCurve(to: m, control: p)
        }
        path.closeSubpath()

        let gradient = self.gradient(for: viewModel.state, level: level)
        ctx.opacity = 0.92
        ctx.fill(path, with: .linearGradient(
            gradient,
            startPoint: CGPoint(x: 0, y: 0),
            endPoint: CGPoint(x: size.width, y: size.height)
        ))
    }

    private func midpoint(_ a: CGPoint, _ b: CGPoint) -> CGPoint {
        CGPoint(x: (a.x + b.x) / 2, y: (a.y + b.y) / 2)
    }

    private func gradient(for state: SessionState, level: Double) -> Gradient {
        switch state {
        case .idle:
            return Gradient(colors: [
                Color(red: 0.55, green: 0.55, blue: 0.60).opacity(0.75),
                Color(red: 0.32, green: 0.32, blue: 0.38).opacity(0.75),
            ])
        case .listening:
            let bright = 0.55 + level * 0.35
            return Gradient(colors: [
                Color(red: 0.35, green: 0.78 * bright, blue: 0.98),
                Color(red: 0.45, green: 0.35, blue: 0.98),
            ])
        case .transcribing:
            return Gradient(colors: [
                Color(red: 1.00, green: 0.65, blue: 0.20),
                Color(red: 0.90, green: 0.25, blue: 0.60),
            ])
        }
    }
}
