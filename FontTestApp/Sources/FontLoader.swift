import AppKit
import CoreText

class FontLoader {
    static let shared = FontLoader()

    /// The PostScript name used to create NSFont instances after registration.
    private(set) var registeredPostScriptName: String?

    /// CGFont loaded directly from file data (bypasses font name cache).
    private var cgFont: CGFont?

    /// Attempt to find font_build/MemeFont.ttf relative to the executable or via known paths.
    private func fontURL() -> URL? {
        // Walk up from the executable to find the repo root
        let exe = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
        var dir = exe.deletingLastPathComponent()
        for _ in 0..<6 {
            let candidate = dir.appendingPathComponent("font_build/MemeFont.ttf")
            if FileManager.default.fileExists(atPath: candidate.path) {
                return candidate
            }
            dir = dir.deletingLastPathComponent()
        }
        // Fallback: current working directory
        let cwd = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        let cwdCandidate = cwd.appendingPathComponent("font_build/MemeFont.ttf")
        if FileManager.default.fileExists(atPath: cwdCandidate.path) {
            return cwdCandidate
        }
        return nil
    }

    func registerFont() {
        guard let url = fontURL() else {
            print("Warning: font_build/MemeFont.ttf not found. Build it with: uv run emojifont")
            return
        }
        print("Loading font from: \(url.path)")

        // Load font from raw file data via CGDataProvider to bypass any name-based
        // font cache that macOS maintains. This ensures we always get the latest
        // version of the font file.
        guard let data = try? Data(contentsOf: url),
              let provider = CGDataProvider(data: data as CFData),
              let cg = CGFont(provider) else {
            print("Failed to load font from file data")
            return
        }
        self.cgFont = cg

        // Also register for CTFont/NSFont name lookups
        var errorRef: Unmanaged<CFError>?
        CTFontManagerRegisterFontsForURL(url as CFURL, .process, &errorRef)

        // Read PostScript name
        if let psName = cg.postScriptName as String? {
            registeredPostScriptName = psName
            print("Registered font: \(psName)")
        } else {
            print("Loaded font but could not read PostScript name")
        }
    }

    func font(size: CGFloat) -> NSFont {
        // Create from CGFont directly to bypass cache
        if let cg = cgFont {
            let ctFont = CTFontCreateWithGraphicsFont(cg, size, nil, nil)
            return ctFont as NSFont
        }
        if let psName = registeredPostScriptName,
           let f = NSFont(name: psName, size: size) {
            return f
        }
        return NSFont.monospacedSystemFont(ofSize: size, weight: .regular)
    }
}
