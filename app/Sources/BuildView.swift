import SwiftUI
import UniformTypeIdentifiers

struct BuildView: View {
    @Environment(BuildEngine.self) private var engine
    private enum Slot { case keys, games }
    @State private var slot: Slot?
    private var importing: Binding<Bool> { Binding(get: { slot != nil }, set: { if !$0 { slot = nil } }) }
    // .item matches any file, whatever its extension (.keys is not a type iOS knows); .zip is covered too
    private static let types: [UTType] = [.item, .data]

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Button { slot = .keys } label: { Label("Add keys", systemImage: "key.fill") }.disabled(engine.running)
                    ForEach(engine.keyFiles, id: \.self) { row($0) }
                } header: { Text("1. Keys") } footer: {
                    Text("Pick prod.keys. Title keys (title.keys) are optional: most .nsp files carry their own. You can also pick one .zip that holds both.")
                }
                Section {
                    Button { slot = .games } label: { Label("Add game", systemImage: "gamecontroller.fill") }.disabled(engine.running)
                    ForEach(engine.gameFiles, id: \.self) { row($0) }
                } header: { Text("2. Game") } footer: {
                    Text("Pick the .nsp or .xci (or a .zip of it). Add the update and DLC here too. Then tap Build: the rest is automatic. Nothing leaves this phone.")
                }
                Section {
                    Button { engine.start() } label: {
                        Label(engine.running ? "Building…" : "Build IPA", systemImage: "hammer.fill").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(engine.running || engine.keyFiles.isEmpty || engine.gameFiles.isEmpty)
                } footer: {
                    if engine.keyFiles.isEmpty || engine.gameFiles.isEmpty { Text(engine.keyFiles.isEmpty ? "Add your keys first." : "Add a game.") }
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
            .navigationTitle("NX Builder")
            .fileImporter(isPresented: importing, allowedContentTypes: Self.types, allowsMultipleSelection: true) { r in
                let keys = slot == .keys
                if case .success(let urls) = r { engine.add(urls, keys: keys) }
            }
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

    private func ext(_ u: URL) -> String { u.pathExtension.lowercased() }
    private func icon(_ u: URL) -> String { ext(u) == "zip" ? "doc.zipper" : ext(u) == "keys" ? "key.fill" : "gamecontroller.fill" }
    private func kind(_ u: URL) -> String {
        switch ext(u) {
        case "zip": "zip (keys and game files inside are used)"
        case "keys": u.lastPathComponent.lowercased().hasPrefix("title") ? "title keys" : "console keys"
        case "nsp", "xci", "nsz", "xcz": "game file"
        default: "not used: only .zip, .keys, .nsp, .xci, .nsz, .xcz"
        }
    }
    private func size(_ u: URL) -> String {
        let b = (try? u.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
        return ByteCountFormatter.string(fromByteCount: Int64(b), countStyle: .file)
    }
}
