import SwiftUI

struct SettingsView: View {
    @Environment(BuildEngine.self) private var engine
    @AppStorage("showFPS") private var showFPS = true
    @AppStorage("smallIPA") private var smallIPA = false
    @AppStorage("fastBuild") private var fastBuild = true
    @AppStorage("language") private var language = ""
    @AppStorage("keepAlive") private var keepAlive = true
    @AppStorage("systemCard") private var systemCard = false
    @State private var cacheSize = ""
    private let languages = ["": "English (default)", "ja": "Japanese", "fr": "French", "de": "German", "es": "Spanish", "it": "Italian", "nl": "Dutch",
                             "pt": "Portuguese", "ru": "Russian", "ko": "Korean", "zh-Hans": "Chinese (Simplified)", "zh-Hant": "Chinese (Traditional)"]

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    if engine.keyFiles.isEmpty {
                        Button { DocPicker.present { engine.add($0, keys: true) } } label: { Label("Add keys", systemImage: "key.fill") }.disabled(engine.running)
                    } else {
                        Label("Keys saved on this phone", systemImage: "checkmark.seal.fill").foregroundStyle(.green)
                        Button("Forget keys", role: .destructive) { engine.forgetKeys() }.disabled(engine.running)
                    }
                } header: { Text("Keys") } footer: {
                    Text("Pick prod.keys once; it is saved on this phone and never leaves it. title.keys is optional (most .nsp files carry their own), and one .zip holding both works too. Switch 2 games (.nup) need no keys.")
                }
                SigningSection()
                Section("Games you build") {
                    Toggle("Show frame rate", isOn: $showFPS)
                    Toggle("Small IPA (game files stay in Files)", isOn: $smallIPA)
                    Toggle("Fast build (skip an optional speed table)", isOn: $fastBuild)
                    Picker("Game language", selection: $language) {
                        ForEach(languages.keys.sorted { (languages[$0] ?? "") < (languages[$1] ?? "") }, id: \.self) { Text(languages[$0] ?? $0).tag($0) }
                    }
                }
                Section {
                    Toggle("Keep building in the background", isOn: $keepAlive)
                    Toggle("Show iOS's progress card (experimental)", isOn: $systemCard)
                    Button("Delete leftover files (\(cacheSize))", role: .destructive) {
                        try? FileManager.default.removeItem(at: Paths.jobs); try? FileManager.default.removeItem(at: Paths.imports)
                        Paths.ensure(); measure()
                    }
                } footer: {
                    Text("Work files are deleted as soon as a build ends: only the finished IPA stays (in the IPAs tab). Your keys stay saved until you forget them.")
                }
                Section {
                    Button("Run self-test") { engine.runSelfTest() }.disabled(engine.running)
                    if let r = engine.selfTest {
                        Text(r).font(.caption.monospaced()).textSelection(.enabled)
                        ShareLink(item: r) { Label("Share report", systemImage: "square.and.arrow.up") }
                    }
                } header: { Text("Check") } footer: { Text("Checks Python and every tool a build needs, without a game. Takes a few seconds.") }
                if let l = engine.lastLogURL {
                    Section {
                        ShareLink(item: l) { Label("Share the full log of the last build", systemImage: "square.and.arrow.up") }
                    } header: { Text("Diagnostics") } footer: { Text("Everything the last build wrote, for when something went wrong (memory, timing, where it stopped).") }
                }
                if FileManager.default.fileExists(atPath: CrashReports.file.path) {
                    Section {
                        ShareLink(item: CrashReports.file) { Label("Share what iOS reported", systemImage: "square.and.arrow.up") }
                    } header: { Text("Crash reports") } footer: { Text("How iOS says the app ended (a crash, or closed for memory or time). It can arrive a day late.") }
                }
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
