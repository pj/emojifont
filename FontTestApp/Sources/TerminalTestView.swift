import SwiftUI
import SwiftTerm
import AppKit

/// Wraps SwiftTerm's LocalProcessTerminalView in a SwiftUI-compatible NSViewRepresentable.
/// Launches a shell that prints test strings using MemeFont characters.
struct TerminalTestView: NSViewRepresentable {
    let fontSize: CGFloat

    func makeNSView(context: Context) -> LocalProcessTerminalView {
        let tv = LocalProcessTerminalView(frame: .zero)

        // Use MemeFont if available, otherwise fall back to a monospace font
        let font: NSFont
        if let psName = FontLoader.shared.registeredPostScriptName,
           let f = NSFont(name: psName, size: fontSize) {
            font = f
        } else {
            font = NSFont.monospacedSystemFont(ofSize: fontSize, weight: .regular)
        }
        tv.font = font
        tv.nativeBackgroundColor = .white
        tv.nativeForegroundColor = .black

        // Set terminal size
        tv.getTerminal().resize(cols: 80, rows: 24)

        // Start a bash shell
        let env = ProcessInfo.processInfo.environment
        tv.startProcess(executable: "/bin/zsh", args: [], environment: env.map { "\($0.key)=\($0.value)" })

        // Send test commands after a short delay to let the shell initialize
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            let cmds = [
                "# MemeFont terminal test",
                "echo 'Normal text: ABCabc123'",
                "echo 'Meme chars: \\uF900 \\uF901'",
                "echo 'Mixed: Hello \\uF900 world \\uF901 done'",
                "echo 'With emoji: \\uF900 😀 \\uF901 🔥'",
                ""
            ]
            let script = cmds.joined(separator: "\n")
            tv.send(txt: script)
        }

        return tv
    }

    func updateNSView(_ nsView: LocalProcessTerminalView, context: Context) {
    }
}

/// A view that shows the terminal test alongside the diagnostic view
struct TerminalTab: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Terminal Preview")
                .font(.system(size: 18, weight: .bold))
                .foregroundColor(.black)
            Text("MemeFont rendered in an embedded terminal emulator")
                .font(.system(size: 12))
                .foregroundColor(.gray)

            TerminalTestView(fontSize: 16)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .border(Color.gray.opacity(0.3))
        }
        .padding()
    }
}
