import SwiftUI

struct SettingsView: View {
    @Environment(BuildEngine.self) private var engine
    @AppStorage("showFPS") private var showFPS = true
    @AppStorage("language") private var language = ""
    @AppStorage("keepBuild") private var keepBuild = true
    @AppStorage("keepAlive") private var keepAlive = true
    @State private var cacheSize = ""
    private let languages = ["": "English (default)", "ja": "Japanese", "fr": "French", "de": "German", "es": "Spanish", "it": "Italian", "nl": "Dutch",
                             "pt": "Portuguese", "ru": "Russian", "ko": "Korean", "zh-Hans": "Chinese (Simplified)", "zh-Hant": "Chinese (Traditional)"]

    var body: some View {
        NavigationStack {
            Form {
                Section("Games you build") {
                    Toggle("Show frame rate", isOn: $showFPS)
                    Picker("Game language", selection: $language) {
                        ForEach(languages.keys.sorted { (languages[$0] ?? "") < (languages[$1] ?? "") }, id: \.self) { Text(languages[$0] ?? $0).tag($0) }
                    }
                }
                Section {
                    Toggle("Keep build files", isOn: $keepBuild)
                    Toggle("Keep building in the background", isOn: $keepAlive)
                    Button("Clear build files (\(cacheSize))", role: .destructive) {
                        try? FileManager.default.removeItem(at: Paths.jobs); try? FileManager.default.removeItem(at: Paths.imports)
                        Paths.ensure(); measure()
                    }
                } footer: {
                    Text("Kept build files make the next build of the same game much faster (finished steps are reused). Your keys are never kept.")
                }
                Section {
                    Button("Run self-test") { engine.runSelfTest() }.disabled(engine.running)
                    if let r = engine.selfTest {
                        Text(r).font(.caption.monospaced()).textSelection(.enabled)
                        ShareLink(item: r) { Label("Share report", systemImage: "square.and.arrow.up") }
                    }
                } header: { Text("Check") } footer: { Text("Checks Python and every tool a build needs, without a game. Takes a few seconds.") }
                Section("About") {
                    LabeledContent("Supported games", value: "\(supported) bundled player shells")
                    Text("Built on nxnative (MIT). Your games and keys stay on this phone. Not affiliated with Nintendo.").font(.caption).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Settings")
            .onAppear(perform: measure)
        }
    }

    private var supported: Int {
        ((try? FileManager.default.contentsOfDirectory(atPath: Paths.resources.appendingPathComponent("shells").path)) ?? []).filter { $0.hasSuffix(".zip") }.count
    }
    private func measure() {
        var total: Int64 = 0
        for root in [Paths.jobs, Paths.imports] {
            if let e = FileManager.default.enumerator(at: root, includingPropertiesForKeys: [.fileSizeKey]) {
                for case let u as URL in e { total += Int64((try? u.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0) }
            }
        }
        cacheSize = ByteCountFormatter.string(fromByteCount: total, countStyle: .file)
    }
}
