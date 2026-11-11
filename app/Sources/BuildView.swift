import SwiftUI
import UniformTypeIdentifiers

struct BuildView: View {
    @Environment(BuildEngine.self) private var engine
    @State private var importing = false
    private static let types: [UTType] = [.zip, .data, .item]

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Button { importing = true } label: { Label("Add files", systemImage: "plus.circle.fill") }
                        .disabled(engine.running)
                    ForEach(engine.picked, id: \.self) { u in
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
                } header: { Text("Your files") } footer: {
                    Text("Pick a .zip holding prod.keys and the game, or the files one by one: prod.keys, the game (.nsp / .xci), its update and DLC. Nothing leaves this phone.")
                }
                Section {
                    Button { engine.start() } label: {
                        Label(engine.running ? "Building…" : "Build IPA", systemImage: "hammer.fill").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(engine.running || engine.picked.isEmpty)
                    .listRowBackground(Color.clear)
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
            .fileImporter(isPresented: $importing, allowedContentTypes: Self.types, allowsMultipleSelection: true) { r in
                if case .success(let urls) = r { engine.add(urls) }
            }
        }
    }

    private func ext(_ u: URL) -> String { u.pathExtension.lowercased() }
    private func icon(_ u: URL) -> String { ext(u) == "zip" ? "doc.zipper" : ext(u) == "keys" ? "key.fill" : "gamecontroller.fill" }
    private func kind(_ u: URL) -> String {
        switch ext(u) {
        case "zip": "zip (keys and game files inside are used)"
        case "keys": "keys"
        case "nsp", "xci", "nsz", "xcz": "game file"
        default: "not used: only .zip, .keys, .nsp, .xci, .nsz, .xcz"
        }
    }
    private func size(_ u: URL) -> String {
        let b = (try? u.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
        return ByteCountFormatter.string(fromByteCount: Int64(b), countStyle: .file)
    }
}
