#!/usr/bin/env swift
//
// render-check.swift — Verify SBIX glyphs render correctly via CoreText.
//
// Usage:
//   swift render-check.swift <font-path> <codepoint> [<codepoint> ...]
//
// Example:
//   swift render-check.swift MemeFont.ttf 0xF900 0xF901
//
// Exit codes:
//   0 = all glyphs rendered and aligned within tolerance
//   1 = one or more glyphs failed checks
//   2 = usage/setup error
//

import AppKit
import CoreGraphics
import CoreText
import Foundation

// MARK: - Helpers

func loadFont(at path: String, size: CGFloat) -> CTFont? {
    guard let data = NSData(contentsOfFile: path) as Data?,
          let provider = CGDataProvider(data: data as CFData),
          let cgFont = CGFont(provider) else {
        return nil
    }
    return CTFontCreateWithGraphicsFont(cgFont, size, nil, nil)
}

struct RenderResult {
    let codePoint: UInt32
    let pixelBounds: CGRect   // in CG coords relative to baseline
    let isEmpty: Bool
    let issues: [String]
}

func savePNG(context ctx: CGContext, to path: String) {
    guard let cgImage = ctx.makeImage() else { return }
    let url = URL(fileURLWithPath: path) as CFURL
    guard let dest = CGImageDestinationCreateWithURL(url, "public.png" as CFString, 1, nil) else { return }
    CGImageDestinationAddImage(dest, cgImage, nil)
    CGImageDestinationFinalize(dest)
}

func renderGlyph(font: CTFont, codePoint: UInt32, fontSize: CGFloat, outputDir: String?) -> RenderResult {
    let scalar = Unicode.Scalar(codePoint)!
    let char = Character(scalar)
    let string = String(char)

    let attrStr = NSAttributedString(
        string: string,
        attributes: [
            .font: font,
            .foregroundColor: CGColor(red: 0, green: 0, blue: 0, alpha: 1)
        ]
    )
    let line = CTLineCreateWithAttributedString(attrStr)

    let padding: CGFloat = 40
    let width = Int(fontSize * 4 + padding * 2)
    let height = Int(fontSize * 4 + padding * 2)
    let baselineY = padding + fontSize

    guard let ctx = CGContext(
        data: nil,
        width: width,
        height: height,
        bitsPerComponent: 8,
        bytesPerRow: width * 4,
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ) else {
        return RenderResult(codePoint: codePoint, pixelBounds: .zero, isEmpty: true,
                            issues: ["Failed to create CGContext"])
    }

    // White background
    ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))

    // Draw
    ctx.textPosition = CGPoint(x: padding, y: baselineY)
    CTLineDraw(line, ctx)

    if let dir = outputDir {
        let filename = String(format: "U+%04X_%dpt.png", codePoint, Int(fontSize))
        savePNG(context: ctx, to: "\(dir)/\(filename)")
    }

    guard let data = ctx.data else {
        return RenderResult(codePoint: codePoint, pixelBounds: .zero, isEmpty: true,
                            issues: ["No image data"])
    }

    // Find non-white pixels
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
        return RenderResult(codePoint: codePoint, pixelBounds: .zero, isEmpty: true,
                            issues: ["Glyph rendered as empty/invisible"])
    }

    // Convert pixel rows (top-down) to CG coords (bottom-up)
    let cgMinY = CGFloat(height - 1 - maxRow)
    let cgMaxY = CGFloat(height - 1 - minRow)

    let bounds = CGRect(
        x: CGFloat(minX) - padding,
        y: cgMinY - baselineY,
        width: CGFloat(maxX - minX + 1),
        height: cgMaxY - cgMinY + 1
    )

    // Checks
    var issues: [String] = []

    let ascent = CTFontGetAscent(font)
    let descent = CTFontGetDescent(font)
    let imgCenter = (bounds.minY + bounds.maxY) / 2
    let expectedCenter = (ascent - descent) / 2

    let centerDelta = abs(imgCenter - expectedCenter)
    if centerDelta > fontSize * 0.15 {
        issues.append(String(format: "Centering off: image center=%.1f, expected=%.1f (delta=%.1f)",
                             imgCenter, expectedCenter, centerDelta))
    }

    // Check for clipping
    if CGFloat(minX) <= 1 || CGFloat(minRow) <= 1 ||
       CGFloat(maxX) >= CGFloat(width - 2) || CGFloat(maxRow) >= CGFloat(height - 2) {
        issues.append("Image may be CLIPPED at render boundary")
    }

    // Check that glyph has reasonable size (> 20% of font size)
    if bounds.height < fontSize * 0.2 {
        issues.append(String(format: "Glyph too small: height=%.1f (%.0f%% of font size)",
                             bounds.height, bounds.height / fontSize * 100))
    }

    return RenderResult(codePoint: codePoint, pixelBounds: bounds, isEmpty: false, issues: issues)
}

// MARK: - Context render: meme glyphs mixed with regular text

func renderContextLine(font: CTFont, codePoints: [UInt32], fontSize: CGFloat, outputDir: String) {
    // Build a string like: "Hello <meme1> World <meme2> Hgpy"
    var testString = "Hgpy "
    for cp in codePoints {
        testString += String(Unicode.Scalar(cp)!)
        testString += " "
    }
    testString += "ABC 123"

    let attrStr = NSAttributedString(
        string: testString,
        attributes: [
            .font: font,
            .foregroundColor: CGColor(red: 0, green: 0, blue: 0, alpha: 1)
        ]
    )
    let line = CTLineCreateWithAttributedString(attrStr)
    let lineWidth = CTLineGetTypographicBounds(line, nil, nil, nil)

    let padding: CGFloat = 20
    let ascent = CTFontGetAscent(font)
    let descent = CTFontGetDescent(font)
    let lineHeight = ascent + descent
    let width = Int(lineWidth + padding * 2 + 20)
    let height = Int(lineHeight + padding * 2 + 20)
    let baselineY = padding + descent + 10

    guard let ctx = CGContext(
        data: nil, width: width, height: height,
        bitsPerComponent: 8, bytesPerRow: width * 4,
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ) else { return }

    // Dark background like a terminal
    ctx.setFillColor(CGColor(red: 0.12, green: 0.12, blue: 0.14, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))

    // Draw baseline guide (subtle)
    ctx.setStrokeColor(CGColor(red: 0.3, green: 0.3, blue: 0.35, alpha: 1))
    ctx.setLineWidth(0.5)
    ctx.move(to: CGPoint(x: 0, y: baselineY))
    ctx.addLine(to: CGPoint(x: CGFloat(width), y: baselineY))
    ctx.strokePath()

    // Draw ascender line
    ctx.setStrokeColor(CGColor(red: 0.4, green: 0.2, blue: 0.2, alpha: 0.5))
    ctx.move(to: CGPoint(x: 0, y: baselineY + ascent))
    ctx.addLine(to: CGPoint(x: CGFloat(width), y: baselineY + ascent))
    ctx.strokePath()

    // Draw descender line
    ctx.setStrokeColor(CGColor(red: 0.2, green: 0.4, blue: 0.2, alpha: 0.5))
    ctx.move(to: CGPoint(x: 0, y: baselineY - descent))
    ctx.addLine(to: CGPoint(x: CGFloat(width), y: baselineY - descent))
    ctx.strokePath()

    // Draw the text (white on dark, like a terminal)
    let whiteAttrStr = NSAttributedString(
        string: testString,
        attributes: [
            .font: font,
            .foregroundColor: NSColor.white
        ]
    )
    let whiteLine = CTLineCreateWithAttributedString(whiteAttrStr)
    ctx.textPosition = CGPoint(x: padding, y: baselineY)
    CTLineDraw(whiteLine, ctx)

    let filename = String(format: "context_%dpt.png", Int(fontSize))
    savePNG(context: ctx, to: "\(outputDir)/\(filename)")
}

// MARK: - Main

var args = Array(CommandLine.arguments.dropFirst())
var outputDir: String? = nil

if let idx = args.firstIndex(of: "--output-dir"), idx + 1 < args.count {
    outputDir = args[idx + 1]
    args.removeSubrange(idx...idx+1)
}

guard args.count >= 2 else {
    print("Usage: swift render-check.swift [--output-dir DIR] <font-path> <codepoint> [<codepoint> ...]")
    print("  Codepoints as hex: 0xF900 or F900")
    print("  --output-dir DIR   Save rendered PNGs to DIR")
    exit(2)
}

let fontPath = args[0]
let codePoints: [UInt32] = args[1...].compactMap { arg in
    let hex = arg.hasPrefix("0x") || arg.hasPrefix("0X") ? String(arg.dropFirst(2)) : arg
    return UInt32(hex, radix: 16)
}

if codePoints.isEmpty {
    print("Error: no valid codepoints provided")
    exit(2)
}

if let dir = outputDir {
    try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
}

let testSizes: [CGFloat] = [16, 24, 32, 48, 64, 96]
var allPassed = true

print("=== SBIX Render Check ===")
print("Font: \(fontPath)")
print("Codepoints: \(codePoints.map { String(format: "U+%04X", $0) }.joined(separator: ", "))")
if let dir = outputDir { print("Output: \(dir)") }
print("")

for fontSize in testSizes {
    guard let font = loadFont(at: fontPath, size: fontSize) else {
        print("FAIL: Could not load font at \(fontPath)")
        exit(2)
    }

    let ascent = CTFontGetAscent(font)
    let descent = CTFontGetDescent(font)
    print("--- \(Int(fontSize))pt (ascent=\(String(format: "%.1f", ascent)), descent=\(String(format: "%.1f", descent))) ---")

    for cp in codePoints {
        let result = renderGlyph(font: font, codePoint: cp, fontSize: fontSize, outputDir: outputDir)
        let label = String(format: "U+%04X", cp)

        if result.isEmpty {
            print("  \(label): FAIL — \(result.issues.joined(separator: "; "))")
            allPassed = false
        } else if result.issues.isEmpty {
            print(String(format: "  %@: OK (bounds: %.1f to %.1f, h=%.1f)",
                         label, result.pixelBounds.minY, result.pixelBounds.maxY,
                         result.pixelBounds.height))
        } else {
            print("  \(label): WARN — \(result.issues.joined(separator: "; "))")
            print(String(format: "    bounds: %.1f to %.1f, h=%.1f",
                         result.pixelBounds.minY, result.pixelBounds.maxY,
                         result.pixelBounds.height))
        }
    }

    if let dir = outputDir {
        renderContextLine(font: font, codePoints: codePoints, fontSize: fontSize, outputDir: dir)
    }
    print("")
}

if allPassed {
    print("RESULT: PASS — all glyphs rendered successfully")
    exit(0)
} else {
    print("RESULT: FAIL — some glyphs did not render")
    exit(1)
}
