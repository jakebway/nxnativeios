import SwiftUI
import UIKit
import UniformTypeIdentifiers

struct BuildView: View {
    @Environment(BuildEngine.self) private var engine

    var body: some View {
        NavigationStack {
            List {
                if engine.running { running } else { idle }
            }
            .navigationTitle("NXnativeiOS")
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
                    Text("\(Int((s?.progress ?? 0) * 100))%").font(.system(size: 44, weight: .semibold, design: .rounded)).monospacedDigit()
                    Spacer()
                    Text(s?.stage ?? "Starting").font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.trailing).lineLimit(2)
                }
                ProgressView(value: s?.progress ?? 0)
                HStack {
                    TimelineView(.periodic(from: .now, by: 1)) { _ in Text("Elapsed \(clock(engine.startedAt.map { Date.now.timeIntervalSince($0) } ?? s?.elapsed))") }
                    Spacer()
                    if let e = s?.eta, e > 1 { Text("About \(clock(e)) left") }
                }.font(.caption).foregroundStyle(.secondary).monospacedDigit()
                if let d = s?.detail, !d.isEmpty { Text(d).font(.caption).foregroundStyle(.secondary).lineLimit(1) }
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
                    if FileManager.default.fileExists(atPath: url.path) {
                        ShareLink(item: url) { Label("Share to FlareStore", systemImage: "square.and.arrow.up").frame(maxWidth: .infinity) }
                            .buttonStyle(.borderedProminent).controlSize(.large)
                    }
                    HStack(spacing: 24) {
                        Button("See it in IPAs") { engine.tab = 1 }
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

    /// keys and a game, or a .nup alone (Switch 2 games carry no encryption)
    private var ready: Bool {
        !engine.gameFiles.isEmpty && (!engine.keyFiles.isEmpty || engine.gameFiles.contains { ext($0) == "nup" })
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
