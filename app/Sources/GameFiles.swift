import SwiftUI

/// The step after installing: the game's files (romfs.img and the shader libraries, in "<name> game files" beside the IPA) go into the installed game's own folder.
/// The person picks that folder once ("On My iPhone → the game"); the app remembers it, copies with a progress bar, and moves the files (the source is deleted once everything is across).
@MainActor
final class GameFilesInstaller: ObservableObject {
    enum Phase: Equatable { case idle, copying(Double, String), done, failed(String) }
    @Published var phase: Phase = .idle
    private var task: Task<Void, Never>?

    static func folder(for ipa: URL) -> URL { ipa.deletingPathExtension().deletingLastPathComponent().appendingPathComponent(ipa.deletingPathExtension().lastPathComponent + " game files", isDirectory: true) }
    static func has(_ ipa: URL) -> Bool { FileManager.default.fileExists(atPath: folder(for: ipa).path) }
    private static func key(_ ipa: URL) -> String { "gamefolder." + ipa.deletingPathExtension().lastPathComponent }

    /// asks for the game's folder only the first time
    func start(for ipa: URL) {
        if let saved = Self.saved(ipa) { run(ipa, target: saved) }
        else { chooseFolder(for: ipa) }
    }
    func chooseFolder(for ipa: URL) {
        DocPicker.presentFolder { [weak self] url in
            if let b = try? url.bookmarkData() { UserDefaults.standard.set(b, forKey: Self.key(ipa)) }
            self?.run(ipa, target: url)
        }
    }
    private static func saved(_ ipa: URL) -> URL? {
        guard let b = UserDefaults.standard.data(forKey: key(ipa)) else { return nil }
        var stale = false
        guard let u = try? URL(resolvingBookmarkData: b, bookmarkDataIsStale: &stale), !stale else { UserDefaults.standard.removeObject(forKey: key(ipa)); return nil }
        return u
    }
    func forget(_ ipa: URL) { UserDefaults.standard.removeObject(forKey: Self.key(ipa)); phase = .idle }

    private func run(_ ipa: URL, target: URL) {
        let src = Self.folder(for: ipa)
        phase = .copying(0, "Starting")
        task = Task.detached(priority: .userInitiated) { [weak self] in
            let scoped = target.startAccessingSecurityScopedResource()
            defer { if scoped { target.stopAccessingSecurityScopedResource() } }
            do {
                let fm = FileManager.default
                let items = try fm.contentsOfDirectory(at: src, includingPropertiesForKeys: nil)
                var files: [(URL, URL, Int64)] = []   // source file, destination file, size
                func gather(_ s: URL, _ d: URL) throws {
                    var isDir: ObjCBool = false
                    fm.fileExists(atPath: s.path, isDirectory: &isDir)
                    if isDir.boolValue { for c in try fm.contentsOfDirectory(at: s, includingPropertiesForKeys: nil) { try gather(c, d.appendingPathComponent(c.lastPathComponent)) } }
                    else { files.append((s, d, Int64((try? s.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0))) }
                }
                for i in items { try gather(i, target.appendingPathComponent(i.lastPathComponent)) }
                let total = max(1, files.reduce(0) { $0 + $1.2 }); var done: Int64 = 0; var lastUI = Date.distantPast
                for (s, d, size) in files {
                    try Task.checkCancellation()
                    try fm.createDirectory(at: d.deletingLastPathComponent(), withIntermediateDirectories: true)
                    if let have = try? d.resourceValues(forKeys: [.fileSizeKey]).fileSize, Int64(have) == size { done += size; continue }   // already across (a repeat after an interruption)
                    let part = d.appendingPathExtension("part"); try? fm.removeItem(at: part)
                    fm.createFile(atPath: part.path, contents: nil)
                    let inH = try FileHandle(forReadingFrom: s), outH = try FileHandle(forWritingTo: part)
                    defer { try? inH.close(); try? outH.close() }
                    while true {
                        let chunk: Data? = try autoreleasepool { try inH.read(upToCount: 8 << 20) }
                        guard let c = chunk, !c.isEmpty else { break }
                        try outH.write(contentsOf: c); done += Int64(c.count)
                        if Date().timeIntervalSince(lastUI) > 0.25 {
                            lastUI = Date(); let f = Double(done) / Double(total), n = s.lastPathComponent
                            await MainActor.run { self?.phase = .copying(f, n) }
                        }
                    }
                    try? fm.removeItem(at: d)
                    try fm.moveItem(at: part, to: d)
                }
                for i in items { try? fm.removeItem(at: i) }   // moved, not copied: the phone keeps only one set
                try? fm.removeItem(at: src)
                await MainActor.run { self?.phase = .done }
            } catch is CancellationError {
                await MainActor.run { self?.phase = .idle }
            } catch {
                await MainActor.run { self?.phase = .failed(error.localizedDescription) }
            }
        }
    }
    func cancel() { task?.cancel() }
}

/// The two steps after a build: install the IPA, then send the game files into the game. Used by the success card and the IPA manager.
struct GameFilesCard: View {
    let ipa: URL
    @StateObject private var installer = GameFilesInstaller()

    var body: some View {
        if GameFilesInstaller.has(ipa) || installer.phase == .done {
            VStack(alignment: .leading, spacing: 10) {
                switch installer.phase {
                case .idle:
                    Label("Open the game once after installing, so its folder exists. Then:", systemImage: "2.circle.fill").font(.footnote).foregroundStyle(.secondary)
                    Button { installer.start(for: ipa) } label: { Label("Send game files to the game", systemImage: "arrow.down.doc.fill").frame(maxWidth: .infinity) }
                        .buttonStyle(.borderedProminent).controlSize(.large).tint(.indigo)
                    Text("Pick the game's folder when asked (On My iPhone → the game). You only do this once; the files are moved, not copied.")
                        .font(.caption).foregroundStyle(.secondary)
                case .copying(let f, let name):
                    ProgressView(value: f) { Text("Sending game files…").font(.subheadline.weight(.semibold)) } currentValueLabel: { Text("\(Int(f * 100))% · \(name)").font(.caption).lineLimit(1) }
                    Button("Stop", role: .cancel) { installer.cancel() }.buttonStyle(.borderless).font(.footnote)
                case .done:
                    Label("Game files are in. Close the game fully and open it again.", systemImage: "checkmark.seal.fill").font(.subheadline).foregroundStyle(.green)
                case .failed(let why):
                    Label(why, systemImage: "exclamationmark.triangle.fill").font(.footnote).foregroundStyle(.red)
                    HStack {
                        Button("Try again") { installer.start(for: ipa) }
                        Button("Pick another folder") { installer.forget(ipa); installer.chooseFolder(for: ipa) }
                    }.buttonStyle(.bordered).font(.footnote)
                }
            }
            .padding(14).frame(maxWidth: .infinity, alignment: .leading)
            .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
    }
}
