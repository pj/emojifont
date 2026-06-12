import SwiftUI

@main
struct FontTestApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    init() {
        // Register the font before any views render so they pick it up immediately
        FontLoader.shared.registerFont()
    }

    var body: some Scene {
        WindowGroup {
            TabView {
                ContentView()
                    .tabItem { Label("Font Test", systemImage: "textformat") }
                TerminalTab()
                    .tabItem { Label("Terminal", systemImage: "terminal") }
            }
            .frame(minWidth: 900, minHeight: 700)
        }
    }
}

class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        // Ensure dock icon and menu bar appear even when run as a bare executable
        NSApplication.shared.setActivationPolicy(.regular)
        NSApplication.shared.activate(ignoringOtherApps: true)

        let args = CommandLine.arguments
        let memeChars = "\u{F900}\u{F901}"
        let sizes: [CGFloat] = [16, 24, 32, 48, 64, 96]

        if args.contains("--capture") || args.contains("--diagnose") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                if args.contains("--diagnose") {
                    // Capture diagnostic views with alignment guides
                    let result = ImageCapture.captureDiagnostics(
                        sizes: sizes, memeChars: memeChars
                    )
                    print(result)

                    // Run automated alignment analysis
                    let reportPath = AlignmentChecker.saveReport(
                        memeChars: memeChars, sizes: sizes
                    )
                    print("Report saved: \(reportPath)")
                } else {
                    let result = ImageCapture.captureAllSizes(
                        sizes: sizes, memeChars: memeChars
                    )
                    print(result)
                }
                NSApplication.shared.terminate(nil)
            }
        }
    }
}
