import AppKit

// Run as a regular app but without dock icon / menu bar presence.
// Accessory activation policy keeps us out of the dock; the HUD
// window is what's visible to the user.
let app = NSApplication.shared
app.setActivationPolicy(.accessory)

let delegate = AppDelegate()
app.delegate = delegate
app.run()
