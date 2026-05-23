import SwiftUI

/// Audio-reactive blob that morphs with the user's voice level.
/// Renders a closed Bezier path with N control points around a circle;
/// each point's radius is perturbed by smooth noise + the audio level,
/// then a circular B-spline through those points gives the "organic"
/// look that's reminiscent of Siri / WhisperKit visualisations.
struct BlobView: View {
    @ObservedObject var viewModel: HUDViewModel
    @State private var phase: Double = 0

    private let pointCount = 64
    private let timer = Timer.publish(every: 1.0 / 60.0, on: .main, in: .common).autoconnect()

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 60.0)) { context in
            Canvas { ctx, size in
                let now = context.date.timeIntervalSinceReferenceDate
                draw(ctx: &ctx, size: size, now: now)
            }
        }
        .frame(width: 160, height: 160)
        .allowsHitTesting(false)
    }

    private func draw(ctx: inout GraphicsContext, size: CGSize, now: TimeInterval) {
        let center = CGPoint(x: size.width / 2, y: size.height / 2)
        let baseRadius = min(size.width, size.height) * 0.28
        let level = Double(viewModel.level)
        // Blob "energy" — how much the radius wobbles. Idle = quiet
        // breath; listening = audio-reactive; transcribing = fast spin.
        let energy: Double
        switch viewModel.state {
        case .idle:         energy = 0.08
        case .listening:    energy = 0.18 + level * 0.6
        case .transcribing: energy = 0.32
        }
        let spinSpeed: Double = (viewModel.state == .transcribing) ? 1.6 : 0.45
        let t = now * spinSpeed

        // Sample radii around the circle using 3 layered sines + small
        // pseudo-noise — gives an organic morph that never repeats.
        var points: [CGPoint] = []
        points.reserveCapacity(pointCount)
        for i in 0..<pointCount {
            let angle = (Double(i) / Double(pointCount)) * 2.0 * .pi
            let n1 = sin(angle * 3 + t * 1.0) * 0.6
            let n2 = sin(angle * 5 - t * 1.3) * 0.3
            let n3 = sin(angle * 7 + t * 0.7) * 0.15
            let wobble = (n1 + n2 + n3) * energy
            let r = baseRadius * (1 + wobble) + level * 18.0
            let x = center.x + cos(angle) * r
            let y = center.y + sin(angle) * r
            points.append(CGPoint(x: x, y: y))
        }

        // Closed Catmull-Rom-ish spline by connecting midpoints with
        // quadratic curves through each sampled point — cheap and smooth.
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

        let fill = gradient(for: viewModel.state, level: level)
        ctx.opacity = 0.92
        ctx.fill(path, with: .linearGradient(
            fill,
            startPoint: CGPoint(x: 0, y: 0),
            endPoint: CGPoint(x: size.width, y: size.height)
        ))

        // Faint outer halo that pulses with level — adds the "live" feel
        // without overwhelming the blob.
        let haloR = baseRadius * (1.6 + level * 0.6)
        let halo = Path(ellipseIn: CGRect(
            x: center.x - haloR, y: center.y - haloR,
            width: haloR * 2, height: haloR * 2
        ))
        ctx.opacity = 0.08 + level * 0.12
        ctx.fill(halo, with: .color(haloColor(for: viewModel.state)))
    }

    private func midpoint(_ a: CGPoint, _ b: CGPoint) -> CGPoint {
        CGPoint(x: (a.x + b.x) / 2, y: (a.y + b.y) / 2)
    }

    private func gradient(for state: SessionState, level: Double) -> Gradient {
        switch state {
        case .idle:
            return Gradient(colors: [
                Color(red: 0.45, green: 0.45, blue: 0.50, opacity: 0.6),
                Color(red: 0.25, green: 0.25, blue: 0.30, opacity: 0.6),
            ])
        case .listening:
            // Cyan → indigo, brighter as level rises.
            let bright = 0.55 + level * 0.35
            return Gradient(colors: [
                Color(red: 0.30, green: 0.75 * bright, blue: 0.95),
                Color(red: 0.40, green: 0.30, blue: 0.95),
            ])
        case .transcribing:
            // Warm amber to magenta — distinct from listening.
            return Gradient(colors: [
                Color(red: 1.0,  green: 0.65, blue: 0.20),
                Color(red: 0.90, green: 0.25, blue: 0.60),
            ])
        }
    }

    private func haloColor(for state: SessionState) -> Color {
        switch state {
        case .idle:         return Color.gray
        case .listening:    return Color(red: 0.35, green: 0.55, blue: 0.95)
        case .transcribing: return Color(red: 1.0,  green: 0.55, blue: 0.30)
        }
    }
}
