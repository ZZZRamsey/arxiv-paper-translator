// Draws the app icon at one size: usage MakeIcon <pixels> <output.png>
import Cocoa

let size = CGFloat(Double(CommandLine.arguments[1])!)
let image = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size), pixelsHigh: Int(size),
                             bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                             colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: image)
let inset = size * 0.1
let rect = NSRect(x: inset, y: inset, width: size - 2 * inset, height: size - 2 * inset)
let sheet = NSBezierPath(roundedRect: rect, xRadius: size * 0.18, yRadius: size * 0.18)
NSGradient(colors: [NSColor(red: 0.20, green: 0.34, blue: 0.86, alpha: 1),
                    NSColor(red: 0.10, green: 0.19, blue: 0.60, alpha: 1)])!.draw(in: sheet, angle: -90)
func draw(_ text: String, font: NSFont, color: NSColor, centerY: CGFloat) {
    let attributes: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: color]
    let bounds = (text as NSString).size(withAttributes: attributes)
    (text as NSString).draw(at: NSPoint(x: (size - bounds.width) / 2, y: centerY - bounds.height / 2),
                            withAttributes: attributes)
}
let serif = NSFont(name: "Songti SC Bold", size: size * 0.46) ?? NSFont.boldSystemFont(ofSize: size * 0.46)
draw("译", font: serif, color: .white, centerY: size * 0.55)
let mono = NSFont.monospacedSystemFont(ofSize: size * 0.085, weight: .semibold)
draw("arXiv → 中文", font: mono, color: NSColor(white: 1, alpha: 0.8), centerY: size * 0.24)
NSGraphicsContext.current = nil
try! image.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[2]))
