import SwiftUI
import UIKit
import UniformTypeIdentifiers

struct BuildView: View {
    @Environment(BuildEngine.self) private var engine
    @State private var free: Int64 = 0
    @State private var leftovers: Int64 = 0

    var body: some View {
        NavigationStack {
            List {
                if engine.running { running } else { idle }
            }
            .navigationTitle("NXnativeiOS")
            .task(id: engine.running) { await refreshStorage() }
        }
    }

    /// Nothing building: the game to pick, the Build button, and how the last build ended.
    @ViewBuilder private var idle: some View {
        if let s = engine.status, s.state != "running", s.state != "done" || FileManager.default.fileExists(atPath: s.ipa ?? "") { result(s) }
        Section {
            Button { DocPicker.present { engine.add($0, keys: false) } } label: { Label("Add game", systemImage: "gamecontroller.fill") }
            ForEach(engine.gameFiles, id: \.self) { row($0) }
        } header: { Text("Game") } footer: {
            Text("Pick the .nsp, .xci or .nup, or a .zip / .rar of it. Split archives (.zip.001, .z01, .part1.rar, .r00 ...): pick all the parts at once. Add the update and DLC here too. Nothing leaves this phone.")
        }
        Section {
            Button { DocPicker.present { if let u = $0.first { engine.setIcon(u) } } } label: { Label(engine.hasIcon ? "Icon chosen: change it" : "Choose an icon", systemImage: "photo") }
            if engine.hasIcon { Button("Remove the icon", role: .destructive) { engine.clearIcon() } }
        } header: { Text("Icon") } footer: {
            Text("Used only when the game has no icon of its own (Switch 2 games carry none): any picture, JPEG or PNG. Games that have an icon keep theirs.")
        }
        if !engine.gameFiles.isEmpty || leftovers > 200_000_000 {
            Section {
                HStack { Label("Free space", systemImage: "internaldrive"); Spacer(); Text(Storage.text(free)).foregroundStyle(enoughSpace ? Color.secondary : Color.red) }
                if needed > 0 { HStack { Text("This build needs about"); Spacer(); Text(Storage.text(needed)).foregroundStyle(.secondary) } }
                if leftovers > 200_000_000 {
                    Button { clearLeftovers() } label: { Label("Clear leftovers (\(Storage.text(leftovers)))", systemImage: "trash") }
                }
            } header: { Text("Storage") } footer: {
                if !enoughSpace { Text("There may not be enough room. Free some space in Settings → General → iPhone Storage, or clear the leftovers above. The build gives its work files back as it goes.") }
            }
        }
        Section {
            Button { engine.start() } label: { Label("Build IPA", systemImage: "hammer.fill").frame(maxWidth: .infinity) }
                .buttonStyle(.borderedProminent).controlSize(.large).disabled(!ready)
        } footer: {
            if engine.gameFiles.isEmpty { Text("Add a game to start.") }
            else if !ready { Button("Add your keys in Settings first") { engine.tab = 2 }.font(.footnote) }
        }
    }

    /// Building: only the progress, with the log beside it.
    @ViewBuilder private var running: some View {
        let s = engine.status
        Section {
            VStack(alignment: .leading, spacing: 10) {
                Text(engine.gameName ?? "Your game").font(.headline).lineLimit(2)
                HStack(alignment: .firstTextBaseline) {
                    if let k = s?.k, let n = s?.n, n > 0 {
                        Text("\(min(k, n))/\(n)").font(.system(size: 44, weight: .semibold, design: .rounded)).monospacedDigit()
                    } else { Text("Starting").font(.system(size: 28, weight: .semibold, design: .rounded)) }
                    Spacer()
                    Text(plain(s?.stage)).font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.trailing).lineLimit(2)
                }
                if let k = s?.k, let n = s?.n, n > 0 {   // one segment per step: a step is done or it is not, nothing pretends to be 37 %
                    HStack(spacing: 4) {
                        ForEach(1...n, id: \.self) { i in
                            Capsule().fill(i < k ? Color.accentColor : i == k ? Color.accentColor.opacity(0.55) : Color.secondary.opacity(0.25)).frame(height: 6)
                        }
                    }
                }
                TimelineView(.periodic(from: .now, by: 1)) { _ in Text("Elapsed \(clock(engine.startedAt.map { Date.now.timeIntervalSince($0) } ?? s?.elapsed))") }
                    .font(.caption).foregroundStyle(.secondary).monospacedDigit()
                if let d = s?.detail, !d.isEmpty { Text(d).font(.caption).foregroundStyle(.secondary).lineLimit(1) }
                if let u = s?.used_gb, let f = s?.free_gb { Text("Using \(String(format: "%.1f", u)) GB · \(String(format: "%.0f", f)) GB free").font(.caption).foregroundStyle(f < 8 ? Color.red : Color.secondary).monospacedDigit() }
            }.padding(.vertical, 4)
        } footer: { Text("You can leave the app: it keeps building. Big games take a while.") }
        logSection
    }

    @ViewBuilder private func result(_ s: JobStatus) -> some View {
        if s.state == "done" {
            let url = URL(fileURLWithPath: s.ipa ?? "")
            let bytes = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize).flatMap { $0 }.map(Int64.init)
            Section {
                VStack(spacing: 12) {
                    Image(systemName: "checkmark.circle.fill").font(.system(size: 52)).foregroundStyle(.green)
                    Text("Your IPA is ready").font(.title3.weight(.semibold))
                    Text([url.deletingPathExtension().lastPathComponent, bytes.map { ByteCountFormatter.string(fromByteCount: $0, countStyle: .file) }].compactMap { $0 }.joined(separator: " · "))
                        .font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    if FileManager.default.fileExists(atPath: url.deletingPathExtension().path + " game files/romfs.img") {
                        Text("After installing, open Files → On My iPhone → NXnativeiOS → IPAs → “\(url.deletingPathExtension().lastPathComponent) game files”, copy romfs.img and the msl folder, and paste both into the game's own folder (On My iPhone → the game).")
                            .font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    }
                    if FileManager.default.fileExists(atPath: url.path) {
                        ShareLink(item: url) { Label("Install with FlareStore", systemImage: "square.and.arrow.up").frame(maxWidth: .infinity) }
                            .buttonStyle(.borderedProminent).controlSize(.large)
                    }
                    HStack(spacing: 24) {
                        Button("See it in IPAs") { engine.tab = 1 }
                        Button("Open in Files") { openInFiles(Paths.ipas) }
                        Button("Dismiss", role: .cancel) { engine.status = nil }.foregroundStyle(.secondary)
                    }.font(.subheadline).buttonStyle(.borderless)
                }.frame(maxWidth: .infinity).padding(.vertical, 8)
            }
        } else {
            Section {
                VStack(spacing: 8) {
                    Image(systemName: "exclamationmark.triangle.fill").font(.system(size: 40)).foregroundStyle(.red)
                    Text(s.error ?? "The build stopped").font(.subheadline).multilineTextAlignment(.center)
                    Button("Dismiss", role: .cancel) { engine.status = nil }.font(.subheadline).buttonStyle(.borderless).foregroundStyle(.secondary)
                }.frame(maxWidth: .infinity).padding(.vertical, 8)
            }
        }
        if !engine.logTail.isEmpty { Section { DisclosureGroup("Log") { logBox } } }
    }

    @ViewBuilder private var logSection: some View {
        if !engine.logTail.isEmpty { Section("Log") { logBox } }
    }

    private var logBox: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 1) {
                    ForEach(Array(engine.logTail.enumerated()), id: \.offset) { i, line in
                        Text(line).font(.system(size: 11, design: .monospaced)).frame(maxWidth: .infinity, alignment: .leading).id(i)
                    }
                }.textSelection(.enabled)
            }
            .frame(height: 260)
            .onChange(of: engine.logTail.count) { _, n in if n > 0 { proxy.scrollTo(n - 1, anchor: .bottom) } }
            .onAppear { if !engine.logTail.isEmpty { proxy.scrollTo(engine.logTail.count - 1, anchor: .bottom) } }
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

    /// keys and a game, a .nup alone (Switch 2 games carry no encryption), or an archive (what is inside it is only known once it is opened)
    private var ready: Bool {
        !engine.gameFiles.isEmpty && (!engine.keyFiles.isEmpty || engine.gameFiles.contains { ext($0) == "nup" || ext($0) == "rar" || ext($0) == "zip" || isPart($0) })   // an archive may hold a .nup (or the keys): the build looks inside
    }

    private var needed: Int64 {   // the games' sizes times what a build takes at its peak (the app's own check refuses only below 1.5 times)
        Int64(Double(engine.gameFiles.reduce(Int64(0)) { $0 + Int64((try? $1.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0) }) * 2.4)
    }
    private var enoughSpace: Bool { needed == 0 || free >= needed }

    private func refreshStorage() async {
        free = Storage.free()
        leftovers = await Task.detached { Storage.size(Paths.jobs) }.value
    }

    private func clearLeftovers() {
        try? FileManager.default.removeItem(at: Paths.jobs)
        try? FileManager.default.createDirectory(at: Paths.jobs, withIntermediateDirectories: true)
        Task { await refreshStorage() }
    }

    /// the script's step names in plain words
    private func plain(_ stage: String?) -> String {
        let t = (stage ?? "").lowercased()
        if t.isEmpty { return "Starting" }
        if t.contains("unpack") || t.contains("extract") || t.contains("decompress") { return "Unpacking the game" }
        if t.contains("check") { return "Checking the files" }
        if t.contains("rewrite") { return "Preparing the game's code" }
        if t.contains("shader split") { return "Finding the shaders" }
        if t.contains("shaders") { return "Translating the shaders" }
        if t.contains("pack") || t.contains("app build") { return "Packing the app" }
        return stage ?? "Working"
    }

    private func ext(_ u: URL) -> String { u.pathExtension.lowercased() }
    private func isPart(_ u: URL) -> Bool { let e = ext(u); return (e.count == 3 && Int(e) != nil) || (e.count == 3 && (e.hasPrefix("z") || e.hasPrefix("r")) && Int(e.dropFirst()) != nil) }
    private func icon(_ u: URL) -> String { ext(u) == "zip" || ext(u) == "rar" || isPart(u) ? "doc.zipper" : ext(u) == "keys" ? "key.fill" : "gamecontroller.fill" }
    private func kind(_ u: URL) -> String {
        if isPart(u) || u.lastPathComponent.lowercased().contains(".part") { return "part of a split archive (pick all the parts)" }
        return switch ext(u) {
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

func clock(_ t: Double?) -> String {
    let n = Int(t ?? 0); return n >= 3600 ? String(format: "%d:%02d:%02d", n / 3600, n / 60 % 60, n % 60) : String(format: "%d:%02d", n / 60, n % 60)
}
