import AppKit
import SwiftUI

enum ImageCapture {
    /// Render each font size row to a separate PNG, plus one combined image.
    /// Images are saved at the repo root in a snapshots/ directory.
    static func captureAllSizes(sizes: [CGFloat], memeChars: String) -> String {
        let fm = FileManager.default
        let repoRoot: URL = {
            let exe = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
            var dir = exe.deletingLastPathComponent()
            for _ in 0..<6 {
                if fm.fileExists(atPath: dir.appendingPathComponent("font_build/MemeFont.ttf").path) {
                    return dir
                }
                dir = dir.deletingLastPathComponent()
            }
            return URL(fileURLWithPath: fm.currentDirectoryPath)
        }()

        let outDir = repoRoot.appendingPathComponent("snapshots")
        try? fm.createDirectory(at: outDir, withIntermediateDirectories: true)

        var saved: [String] = []

        // Render individual sizes
        for size in sizes {
            let view = FontSizeRow(size: size, memeChars: memeChars)
                .padding(16)
                .background(Color.white)
                .environment(\.colorScheme, .light)

            if let image = renderToImage(view: view, width: 900) {
                let path = outDir.appendingPathComponent("size_\(Int(size))pt.png")
                if savePNG(image: image, to: path) {
                    saved.append(path.lastPathComponent)
                }
            }
        }

        // Render combined view
        let combined = VStack(alignment: .leading, spacing: 16) {
            Text("MemeFont Test — All Sizes")
                .font(.system(size: 20, weight: .bold))
                .foregroundColor(.black)
            if let psName = FontLoader.shared.registeredPostScriptName {
                Text("Font: \(psName)")
                    .font(.system(size: 12))
                    .foregroundColor(.green)
            }
            ForEach(sizes, id: \.self) { size in
                FontSizeRow(size: size, memeChars: memeChars)
            }
        }
        .padding(24)
        .background(Color.white)
        .environment(\.colorScheme, .light)

        if let image = renderToImage(view: combined, width: 900) {
            let path = outDir.appendingPathComponent("all_sizes.png")
            if savePNG(image: image, to: path) {
                saved.append(path.lastPathComponent)
            }
        }

        if saved.isEmpty {
            return "Failed to capture any snapshots"
        }
        return "Saved \(saved.count) snapshots to snapshots/"
    }

    /// Capture diagnostic views with alignment guide overlays.
    static func captureDiagnostics(sizes: [CGFloat], memeChars: String) -> String {
        let fm = FileManager.default
        let repoRoot: URL = {
            let exe = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
            var dir = exe.deletingLastPathComponent()
            for _ in 0..<6 {
                if fm.fileExists(atPath: dir.appendingPathComponent("font_build/MemeFont.ttf").path) {
                    return dir
                }
                dir = dir.deletingLastPathComponent()
            }
            return URL(fileURLWithPath: fm.currentDirectoryPath)
        }()

        let outDir = repoRoot.appendingPathComponent("snapshots")
        try? fm.createDirectory(at: outDir, withIntermediateDirectories: true)

        var saved: [String] = []

        // Individual diagnostic sizes
        for size in sizes {
            let view = AlignmentDiagnosticView(size: size, memeChars: memeChars)
                .padding(16)
                .background(Color.white)
                .environment(\.colorScheme, .light)

            if let image = renderToImage(view: view, width: 900) {
                let path = outDir.appendingPathComponent("diag_\(Int(size))pt.png")
                if savePNG(image: image, to: path) {
                    saved.append(path.lastPathComponent)
                }
            }
        }

        // Combined diagnostic
        let combined = VStack(alignment: .leading, spacing: 20) {
            Text("MemeFont Alignment Diagnostic")
                .font(.system(size: 20, weight: .bold))
                .foregroundColor(.black)
            ForEach(sizes, id: \.self) { size in
                AlignmentDiagnosticView(size: size, memeChars: memeChars)
            }
        }
        .padding(24)
        .background(Color.white)
        .environment(\.colorScheme, .light)

        if let image = renderToImage(view: combined, width: 900) {
            let path = outDir.appendingPathComponent("diag_all_sizes.png")
            if savePNG(image: image, to: path) {
                saved.append(path.lastPathComponent)
            }
        }

        if saved.isEmpty {
            return "Failed to capture any diagnostics"
        }
        return "Saved \(saved.count) diagnostic snapshots to snapshots/"
    }

    private static func renderToImage<V: View>(view: V, width: CGFloat) -> NSImage? {
        let hostingView = NSHostingView(rootView: view)

        // Use a fixed width and let height be determined by content
        let fittingSize = hostingView.fittingSize
        let viewWidth = max(fittingSize.width, width)
        let viewHeight = max(fittingSize.height, 50)

        hostingView.frame = NSRect(x: 0, y: 0, width: viewWidth, height: viewHeight)
        hostingView.layoutSubtreeIfNeeded()

        // Re-measure after layout
        let finalSize = hostingView.fittingSize
        let finalWidth = max(finalSize.width, width)
        let finalHeight = max(finalSize.height, 50)
        hostingView.frame = NSRect(x: 0, y: 0, width: finalWidth, height: finalHeight)
        hostingView.layoutSubtreeIfNeeded()

        guard let bitmapRep = hostingView.bitmapImageRepForCachingDisplay(in: hostingView.bounds) else {
            print("Failed to create bitmap rep")
            return nil
        }
        hostingView.cacheDisplay(in: hostingView.bounds, to: bitmapRep)

        let image = NSImage(size: hostingView.bounds.size)
        image.addRepresentation(bitmapRep)
        return image
    }

    private static func savePNG(image: NSImage, to url: URL) -> Bool {
        guard let tiffData = image.tiffRepresentation,
              let bitmapRep = NSBitmapImageRep(data: tiffData),
              let pngData = bitmapRep.representation(using: .png, properties: [:]) else {
            return false
        }
        do {
            try pngData.write(to: url)
            print("Saved: \(url.path)")
            return true
        } catch {
            print("Error saving \(url.lastPathComponent): \(error)")
            return false
        }
    }
}
