import SwiftUI
import UIKit
import UniformTypeIdentifiers

struct BuildView: View {
    @Environment(BuildEngine.self) private var engine

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Button { DocPicker.present { engine.add($0, keys: true) } } label: { Label("Add keys", systemImage: "key.fill") }.disabled(engine.running)
                    ForEach(engine.keyFiles, id: \.self) { row($0) }
                } header: { Text("1. Keys") } footer: {
                    Text("Pick prod.keys. Title keys (title.keys) are optional: most .nsp files carry their own. You can also pick one .zip that holds both. Switch 2 games (.nup) need no keys.")
                }
                Section {
                    Button { DocPicker.present { engine.add($0, keys: false) } } label: { Label("Add game", systemImage: "gamecontroller.fill") }.disabled(engine.running)
                    ForEach(engine.gameFiles, id: \.self) { row($0) }
                } header: { Text("2. Game") } footer: {
                    Text("Pick the .nsp, .xci or .nup, or a .zip of it. Split archives (.zip.001 / .z01 / .part1.rar / .r00 ...): pick all the parts at once. Add the update and DLC here too. Then tap Build: the rest is automatic. Nothing leaves this phone.")
                }
                Section {
                    Button { engine.start() } label: {
                        Label(engine.running ? "Building…" : "Build IPA", systemImage: "hammer.fill").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(engine.running || !ready)
                } footer: {
                    if !ready { Text(engine.gameFiles.isEmpty ? "Add a game." : "Add your keys first.") }
                }
                if let s = engine.status {
                    Section("Progress") {
                        if s.state == "running" {
                            ProgressView(value: s.progress ?? 0) { Text(s.stage ?? "working") }
                            Text("Keep the app open: the screen stays on until the build ends.").font(.caption).foregroundStyle(.secondary)
                        } else if s.state == "done" {
                            Label("Done: \(URL(fileURLWithPath: s.ipa ?? "").lastPathComponent)", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
                            Text("Find it in the IPAs tab and share it to FlareStore.").font(.caption)
                        } else {
                            Label(s.error ?? "The build stopped", systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red)
                        }
                    }
                }
                if !engine.logTail.isEmpty {
                    Section("Log") {
                        ScrollView(.horizontal) {
                            Text(engine.logTail.joined(separator: "\n")).font(.caption2.monospaced()).textSelection(.enabled)
                        }
                        if let l = engine.logURL { ShareLink(item: l) { Label("Share full log", systemImage: "square.and.arrow.up") } }
                    }
                }
            }
            .navigationTitle("NXnativeiOS")
        }
    }

    private func row(_ u: URL) -> some View {
        HStack {
            Image(systemName: icon(u)).foregroundStyle(.secondary)
            VStack(alignment: .leading) {
                Text(u.lastPathComponent).lineLimit(1)
                Text(kind(u)).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Text(size(u)).font(.caption).foregroundStyle(.secondary)
        }
        .swipeActions { if !engine.running { Button("Remove", role: .destructive) { engine.remove(u) } } }
    }

    /// keys and a game, or a .nup alone (Switch 2 games carry no encryption)
    private var ready: Bool {
        !engine.gameFiles.isEmpty && (!engine.keyFiles.isEmpty || engine.gameFiles.contains { ext($0) == "nup" })
    }

    private func ext(_ u: URL) -> String { u.pathExtension.lowercased() }
    private func isPart(_ u: URL) -> Bool { let e = ext(u); return (e.count == 3 && Int(e) != nil) || (e.count == 3 && (e.hasPrefix("z") || e.hasPrefix("r")) && Int(e.dropFirst()) != nil) }
    private func icon(_ u: URL) -> String { ext(u) == "zip" || ext(u) == "rar" || isPart(u) ? "doc.zipper" : ext(u) == "keys" ? "key.fill" : "gamecontroller.fill" }
    private func kind(_ u: URL) -> String {
        if isPart(u) || u.lastPathComponent.lowercased().contains(".part") { return "part of a split archive (pick all the parts)" }
        switch ext(u) {
        case "zip": "zip (keys and game files inside are used)"
        case "rar": "rar (keys and game files inside are used)"
        case "keys": u.lastPathComponent.lowercased().hasPrefix("title") ? "title keys" : "console keys"
        case "nsp", "xci", "nsz", "xcz": "game file"
        case "nup": "Switch 2 game (no keys needed)"
        default: "not used: only .zip, .rar, .keys, .nsp, .xci, .nsz, .xcz, .nup"
        }
    }
    private func size(_ u: URL) -> String {
        let b = (try? u.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
        return ByteCountFormatter.string(fromByteCount: Int64(b), countStyle: .file)
    }
}

/// UIKit's document picker, presented straight from the top view controller (inside a SwiftUI sheet its Open button did nothing on iOS 27 beta).
/// asCopy: the picker copies the chosen files into the app's inbox itself (with its own progress), so there is no security-scoped access to manage.
@MainActor
enum DocPicker {
    private static var holder: Delegate?

    static func present(onPick: @escaping ([URL]) -> Void) {
        let p = UIDocumentPickerViewController(forOpeningContentTypes: [.item, .data, .zip], asCopy: true)
        p.allowsMultipleSelection = true
        let d = Delegate(onPick); holder = d; p.delegate = d
        var top = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.flatMap(\.windows).first { $0.isKeyWindow }?.rootViewController
        while let n = top?.presentedViewController { top = n }
        top?.present(p, animated: true)
    }

    private final class Delegate: NSObject, UIDocumentPickerDelegate {
        let onPick: ([URL]) -> Void
        init(_ f: @escaping ([URL]) -> Void) { onPick = f }
        func documentPicker(_ c: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            Task { @MainActor in onPick(urls); DocPicker.holder = nil }
        }
        func documentPickerWasCancelled(_ c: UIDocumentPickerViewController) { Task { @MainActor in DocPicker.holder = nil } }
    }
}
