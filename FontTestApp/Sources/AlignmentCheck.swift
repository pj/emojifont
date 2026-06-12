import AppKit
import SwiftUI
import CoreText

/// Diagnostic view that renders meme glyphs with CoreText so we know exact
/// baseline position, then draws alignment guide lines on top.
struct AlignmentDiagnosticView: View {
    let size: CGFloat
    let memeChars: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("\(Int(size))pt — Alignment Diagnostic")
                .font(.system(size: 12, weight: .semibold))
                .foregroundColor(.gray)

            Canvas { context, canvasSize in
                let font = FontLoader.shared.font(size: size)
                let ascender = font.ascender
                let descender = font.descender  // negative
                let capHeight = font.capHeight
                let xHeight = font.xHeight

                // Place baseline so the full line (ascender to descender) is centered
                // with padding above and below
                let padding: CGFloat = 8
                let baselineY = ascender + padding  // in canvas coords (y-down)

                // Guide lines — includes ascender and descender as the line boundaries
                let guides: [(String, CGFloat, Color)] = [
                    ("ascender",   baselineY - ascender,   .red),
                    ("cap height", baselineY - capHeight,  .orange),
                    ("x-height",   baselineY - xHeight,    .purple),
                    ("baseline",   baselineY,               .blue),
                    ("descender",  baselineY - descender,  .green),
                ]
                for (label, y, color) in guides {
                    var path = Path()
                    path.move(to: CGPoint(x: 0, y: y))
                    path.addLine(to: CGPoint(x: canvasSize.width, y: y))
                    context.stroke(path, with: .color(color.opacity(0.5)), lineWidth: 1)
                    context.draw(
                        Text(label).font(.system(size: 8)).foregroundColor(color),
                        at: CGPoint(x: canvasSize.width - 40, y: y - 6)
                    )
                }

                // Shade the regions above ascender and below descender
                let aboveAscender = CGRect(x: 0, y: 0,
                                           width: canvasSize.width,
                                           height: baselineY - ascender)
                let belowDescender = CGRect(x: 0, y: baselineY - descender,
                                            width: canvasSize.width,
                                            height: canvasSize.height - (baselineY - descender))
                context.fill(Path(aboveAscender), with: .color(.gray.opacity(0.08)))
                context.fill(Path(belowDescender), with: .color(.gray.opacity(0.08)))

                // Draw text using CoreText at our known baseline
                let testString = "Hgpy" + memeChars + "😀"
                let attrStr = NSAttributedString(
                    string: testString,
                    attributes: [
                        .font: font,
                        .foregroundColor: NSColor.black
                    ]
                )
                let line = CTLineCreateWithAttributedString(attrStr)

                // CoreText uses bottom-left origin; Canvas uses top-left — flip for drawing
                var cgContext = context
                cgContext.translateBy(x: 0, y: canvasSize.height)
                cgContext.scaleBy(x: 1, y: -1)

                let cgBaselineY = canvasSize.height - baselineY

                cgContext.withCGContext { cg in
                    cg.textPosition = CGPoint(x: padding, y: cgBaselineY)
                    CTLineDraw(line, cg)
                }
            }
            .frame(height: size + max(size * 0.5, 20) + 16)

            Divider()
        }
    }
}

// MARK: - Automated alignment analysis

enum AlignmentChecker {
    struct GlyphAnalysis {
        let codePoint: UInt32
        let character: String
        let boundingBox: CGRect
        let fontMetrics: FontMetrics
        let issues: [String]
    }

    struct FontMetrics {
        let ascender: CGFloat
        let descender: CGFloat  // negative
        let capHeight: CGFloat
        let xHeight: CGFloat
        let size: CGFloat
    }

    /// Analyze alignment of meme glyphs at a given size by rendering to a bitmap
    /// and finding the actual pixel bounds of non-white content.
    static func analyze(memeChars: String, fontSize: CGFloat) -> [GlyphAnalysis] {
        let font = FontLoader.shared.font(size: fontSize)
        let metrics = FontMetrics(
            ascender: font.ascender,
            descender: font.descender,
            capHeight: font.capHeight,
            xHeight: font.xHeight,
            size: fontSize
        )

        // First, measure the baseline reference using a capital letter
        let refOffset = measureBaseline(char: "H", font: font, metrics: metrics)

        var results: [GlyphAnalysis] = []
        for char in memeChars.unicodeScalars {
            let analysis = analyzeGlyph(char: char, font: font, metrics: metrics, baselineRef: refOffset)
            results.append(analysis)
        }
        return results
    }

    /// Render "H" and find where its bottom pixel is — that's the true baseline.
    private static func measureBaseline(char: String, font: NSFont, metrics: FontMetrics) -> CGFloat {
        let attrStr = NSAttributedString(
            string: char,
            attributes: [.font: font, .foregroundColor: NSColor.black]
        )
        let line = CTLineCreateWithAttributedString(attrStr)
        let padding: CGFloat = 40
        let width = Int(metrics.size * 3 + padding * 2)
        let height = Int(metrics.size * 3 + padding * 2)
        let baselineY = padding + metrics.size  // CG coords (bottom-left origin)

        guard let ctx = createContext(width: width, height: height) else { return baselineY }
        ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
        ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))
        ctx.textPosition = CGPoint(x: padding, y: baselineY)
        CTLineDraw(line, ctx)

        guard let data = ctx.data else { return baselineY }
        let bounds = findNonWhiteBounds(data: data, width: width, height: height)
        // bounds.minY in CG coords = bottom of "H" = baseline
        return bounds.minY
    }

    private static func analyzeGlyph(char: Unicode.Scalar, font: NSFont, metrics: FontMetrics, baselineRef: CGFloat) -> GlyphAnalysis {
        let string = String(char)
        let codePoint = char.value

        let attrStr = NSAttributedString(
            string: string,
            attributes: [.font: font, .foregroundColor: NSColor.black]
        )
        let line = CTLineCreateWithAttributedString(attrStr)

        let padding: CGFloat = 40
        let width = Int(metrics.size * 4 + padding * 2)
        let height = Int(metrics.size * 4 + padding * 2)
        let baselineY = padding + metrics.size  // same baseline position as reference

        guard let ctx = createContext(width: width, height: height) else {
            return GlyphAnalysis(codePoint: codePoint, character: string,
                                 boundingBox: .zero, fontMetrics: metrics,
                                 issues: ["Failed to create CGContext"])
        }

        ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
        ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))
        ctx.textPosition = CGPoint(x: padding, y: baselineY)
        CTLineDraw(line, ctx)

        guard let data = ctx.data else {
            return GlyphAnalysis(codePoint: codePoint, character: string,
                                 boundingBox: .zero, fontMetrics: metrics,
                                 issues: ["No image data"])
        }

        let pixelBounds = findNonWhiteBounds(data: data, width: width, height: height)

        // Convert to font coordinates relative to baseline (CG: y-up)
        // baselineRef = the actual measured baseline from "H" rendering
        let glyphBox = CGRect(
            x: pixelBounds.minX - padding,
            y: pixelBounds.minY - baselineY,  // relative to baseline, CG y-up
            width: pixelBounds.width,
            height: pixelBounds.height
        )
        // glyphBox.minY = bottom of image relative to baseline (negative = below)
        // glyphBox.maxY = top of image relative to baseline

        var issues: [String] = []

        if pixelBounds.width == 0 || pixelBounds.height == 0 {
            issues.append("Glyph rendered as empty/invisible")
        } else {
            let imgBottom = glyphBox.minY   // relative to baseline
            let imgTop = glyphBox.maxY      // relative to baseline
            let imgCenter = (imgBottom + imgTop) / 2

            // Expected center: midpoint between ascender and descender
            let expectedCenter = (metrics.ascender + metrics.descender) / 2

            let centerDelta = abs(imgCenter - expectedCenter)
            if centerDelta > metrics.size * 0.1 {
                issues.append(String(format: "Not centered: image center=%.1f, expected=%.1f (off by %.1f)",
                                     imgCenter, expectedCenter, centerDelta))
            }

            // Check clipping
            if pixelBounds.minX <= 1 || pixelBounds.minY <= 1 ||
               pixelBounds.maxX >= CGFloat(width - 2) || pixelBounds.maxY >= CGFloat(height - 2) {
                issues.append("Image may be CLIPPED (extends to render boundary)")
            }
        }

        if issues.isEmpty {
            issues.append("OK")
        }

        return GlyphAnalysis(codePoint: codePoint, character: string,
                             boundingBox: glyphBox, fontMetrics: metrics,
                             issues: issues)
    }

    private static func createContext(width: Int, height: Int) -> CGContext? {
        CGContext(
            data: nil,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: width * 4,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        )
    }

    /// Scan pixel buffer for non-white pixels. Returns bounds in CG coordinates (origin bottom-left).
    private static func findNonWhiteBounds(data: UnsafeMutableRawPointer, width: Int, height: Int) -> CGRect {
        let pixels = data.bindMemory(to: UInt8.self, capacity: width * height * 4)
        let threshold: UInt8 = 250

        var minX = width, minRow = height, maxX = 0, maxRow = 0

        for row in 0..<height {
            for col in 0..<width {
                let offset = (row * width + col) * 4
                let r = pixels[offset]
                let g = pixels[offset + 1]
                let b = pixels[offset + 2]
                let a = pixels[offset + 3]

                if a > 5 && (r < threshold || g < threshold || b < threshold) {
                    minX = min(minX, col)
                    maxX = max(maxX, col)
                    minRow = min(minRow, row)
                    maxRow = max(maxRow, row)
                }
            }
        }

        if minX > maxX || minRow > maxRow {
            return .zero
        }

        // Pixel rows are stored top-to-bottom, but CG origin is bottom-left
        let cgMinY = CGFloat(height - 1 - maxRow)
        let cgMaxY = CGFloat(height - 1 - minRow)

        return CGRect(x: CGFloat(minX), y: cgMinY,
                      width: CGFloat(maxX - minX + 1),
                      height: cgMaxY - cgMinY + 1)
    }

    /// Run analysis at all test sizes and return a formatted report.
    /// Measure the pixel bounds of a system emoji rendered at the given font size
    /// using the system font, to serve as a reference for meme sizing.
    static func measureSystemEmoji(_ emoji: String, fontSize: CGFloat) -> (bottom: CGFloat, top: CGFloat, height: CGFloat)? {
        let font = NSFont.systemFont(ofSize: fontSize)
        let attrStr = NSAttributedString(
            string: emoji,
            attributes: [.font: font, .foregroundColor: NSColor.black]
        )
        let line = CTLineCreateWithAttributedString(attrStr)

        let padding: CGFloat = 40
        let width = Int(fontSize * 4 + padding * 2)
        let height = Int(fontSize * 4 + padding * 2)
        let baselineY = padding + fontSize

        guard let ctx = createContext(width: width, height: height) else { return nil }
        ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
        ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))
        ctx.textPosition = CGPoint(x: padding, y: baselineY)
        CTLineDraw(line, ctx)

        guard let data = ctx.data else { return nil }
        let pixelBounds = findNonWhiteBounds(data: data, width: width, height: height)
        if pixelBounds.width == 0 { return nil }

        let bottom = pixelBounds.minY - baselineY
        let top = pixelBounds.maxY - baselineY
        return (bottom: bottom, top: top, height: top - bottom)
    }

    static func fullReport(memeChars: String, sizes: [CGFloat]) -> String {
        var lines: [String] = ["=== MemeFont Alignment Report ===", ""]

        for size in sizes {
            lines.append("--- \(Int(size))pt ---")

            // Measure system emoji reference
            if let ref = measureSystemEmoji("😀", fontSize: size) {
                lines.append("  System 😀 reference:")
                lines.append("    Image: bottom=\(String(format: "%.1f", ref.bottom)), top=\(String(format: "%.1f", ref.top)), height=\(String(format: "%.1f", ref.height))")
            }

            let results = analyze(memeChars: memeChars, fontSize: size)
            for r in results {
                let status = r.issues.first == "OK" ? "✓" : "✗"
                let imgBottom = r.boundingBox.minY
                let imgTop = r.boundingBox.maxY
                let imgHeight = imgTop - imgBottom
                let imgCenter = (imgBottom + imgTop) / 2
                let expectedCenter = (r.fontMetrics.ascender + r.fontMetrics.descender) / 2
                lines.append("  U+\(String(format: "%04X", r.codePoint)) \(status)")
                lines.append("    Image: bottom=\(String(format: "%.1f", imgBottom)), top=\(String(format: "%.1f", imgTop)), height=\(String(format: "%.1f", imgHeight)), center=\(String(format: "%.1f", imgCenter))")
                lines.append("    Expected center: \(String(format: "%.1f", expectedCenter)) (midpoint of ascender=\(String(format: "%.1f", r.fontMetrics.ascender)), descender=\(String(format: "%.1f", r.fontMetrics.descender)))")
                for issue in r.issues {
                    lines.append("    → \(issue)")
                }
            }
            lines.append("")
        }

        return lines.joined(separator: "\n")
    }

    /// Save the report to a file alongside snapshots.
    static func saveReport(memeChars: String, sizes: [CGFloat]) -> String {
        let report = fullReport(memeChars: memeChars, sizes: sizes)
        print(report)

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
        let reportPath = outDir.appendingPathComponent("alignment_report.txt")
        try? report.write(to: reportPath, atomically: true, encoding: .utf8)

        return reportPath.path
    }
}
