import SwiftUI

struct ContentView: View {
    @State private var captureStatus: String?

    // Meme code points injected by inject_sbix.py (CJK Compatibility range)
    private let memeChars = "\u{F900}\u{F901}"
    private let testSizes: [CGFloat] = [16, 24, 32, 48, 64, 96]

    var body: some View {
        ScrollView {
            testContent
                .padding(24)
        }
        .background(Color.white)
    }

    private var captureButton: some View {
        Button("Capture Snapshots") {
            captureStatus = "Capturing..."
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                let result = ImageCapture.captureAllSizes(
                    sizes: testSizes,
                    memeChars: memeChars
                )
                captureStatus = result
            }
        }
        .buttonStyle(.borderedProminent)
        .padding(.top, 8)
    }

    var testContent: some View {
        VStack(alignment: .leading, spacing: 20) {
            header
            ForEach(testSizes, id: \.self) { size in
                FontSizeRow(size: size, memeChars: memeChars)
            }
            captureButton
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("MemeFont Test")
                .font(.system(size: 28, weight: .bold))
                .foregroundColor(.black)
            if let psName = FontLoader.shared.registeredPostScriptName {
                Text("Loaded: \(psName)")
                    .font(.system(size: 14, weight: .regular))
                    .foregroundColor(.green)
            } else {
                Text("Font not loaded — using system fallback")
                    .font(.system(size: 14, weight: .regular))
                    .foregroundColor(.red)
            }
            if let status = captureStatus {
                Text(status)
                    .font(.system(size: 12))
                    .foregroundColor(.gray)
            }
        }
    }
}

struct FontSizeRow: View {
    let size: CGFloat
    let memeChars: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("\(Int(size))pt")
                .font(.system(size: 12, weight: .semibold))
                .foregroundColor(.gray)

            HStack(alignment: .lastTextBaseline, spacing: 4) {
                // Normal letters in meme font
                Text("ABCabc123")
                    .font(.init(FontLoader.shared.font(size: size)))
                    .foregroundColor(.black)

                // Meme glyphs
                Text(memeChars)
                    .font(.init(FontLoader.shared.font(size: size)))
                    .foregroundColor(.black)

                // System emoji for comparison
                Text("😀🔥")
                    .font(.system(size: size))
            }

            Divider()
        }
    }
}

#Preview {
    ContentView()
        .frame(width: 900, height: 700)
}
