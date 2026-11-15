import SwiftUI

struct IPAFile: Identifiable, Hashable {
    let url: URL; let size: Int64; let date: Date
    var id: URL { url }
}

/// The IPA manager: built and downloaded IPAs (Documents/IPAs, also visible in the Files app), with share (to FlareStore), rename and delete.
struct IPAsView: View {
    @State private var files: [IPAFile] = []
    @State private var renaming: IPAFile?
    @State private var newName = ""

    var body: some View {
        NavigationStack {
            List {
                if files.isEmpty {
                    ContentUnavailableView("No IPAs yet", systemImage: "shippingbox", description: Text("Games you build appear here, ready to sign."))
                }
                ForEach(files) { f in
                    VStack(spacing: 10) {
                    HStack(spacing: 14) {
                        Image(systemName: "gamecontroller.fill").font(.title3).foregroundStyle(.white)
                            .frame(width: 48, height: 48)
                            .background(LinearGradient(colors: [.indigo, .purple], startPoint: .topLeading, endPoint: .bottomTrailing), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                        VStack(alignment: .leading, spacing: 3) {
                            Text(f.url.deletingPathExtension().lastPathComponent).font(.headline).lineLimit(2)
                            Text("\(ByteCountFormatter.string(fromByteCount: f.size, countStyle: .file)) · \(f.date.formatted(date: .abbreviated, time: .shortened))")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer(minLength: 4)
                        ShareLink(item: f.url) { Image(systemName: "square.and.arrow.up").font(.body.weight(.semibold)).frame(width: 40, height: 40).background(.tint.opacity(0.15), in: Circle()) }.buttonStyle(.borderless)
                    }
                    if let g = gameFiles(for: f) {   // the game's files, beside its IPA: one tap to the folder, one to copy them to the app's Documents once it is installed
                        HStack(spacing: 10) {
                            Image(systemName: "folder.fill").foregroundStyle(.orange)
                            VStack(alignment: .leading, spacing: 1) {
                                Text("Game files").font(.subheadline.weight(.medium))
                                Text(ByteCountFormatter.string(fromByteCount: g.size, countStyle: .file) + " · copy to the game's folder after installing").font(.caption2).foregroundStyle(.secondary)
                            }
                            Spacer(minLength: 4)
                            Button { openInFiles(g.url) } label: { Label("Open", systemImage: "folder").font(.subheadline) }.buttonStyle(.bordered).controlSize(.small)
                            if let r = g.image { ShareLink(item: r) { Image(systemName: "square.and.arrow.up") }.buttonStyle(.bordered).controlSize(.small) }
                        }
                        .padding(10).background(Color.orange.opacity(0.1), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                    }
                    }
                    .padding(.vertical, 4)
                    .contextMenu {
                        ShareLink(item: f.url) { Label("Share (open in FlareStore)", systemImage: "square.and.arrow.up") }
                        Button { renaming = f; newName = f.url.deletingPathExtension().lastPathComponent } label: { Label("Rename", systemImage: "pencil") }
                        Button(role: .destructive) { delete(f) } label: { Label("Delete", systemImage: "trash") }
                    }
                    .swipeActions {
                        Button(role: .destructive) { delete(f) } label: { Label("Delete", systemImage: "trash") }
                        Button { renaming = f; newName = f.url.deletingPathExtension().lastPathComponent } label: { Label("Rename", systemImage: "pencil") }.tint(.orange)
                    }
                }
                if !files.isEmpty {
                    Section { } footer: {
                        Text("Total \(ByteCountFormatter.string(fromByteCount: files.reduce(0) { $0 + $1.size }, countStyle: .file)). In FlareStore, keep the Increased Memory Limit entitlement on: the bigger games need it.")
                    }
                }
            }
            .navigationTitle("IPAs")
            .toolbar { Button { openInFiles(Paths.ipas) } label: { Label("Open in Files", systemImage: "folder") } }
            .refreshable { load() }
            .onAppear(perform: load)
            .alert("Rename", isPresented: Binding(get: { renaming != nil }, set: { if !$0 { renaming = nil } })) {
                TextField("Name", text: $newName)
                Button("Rename") { rename() }
                Button("Cancel", role: .cancel) { renaming = nil }
            }
        }
    }

    private func load() {
        Paths.ensure()
        let keys: [URLResourceKey] = [.fileSizeKey, .contentModificationDateKey]
        let urls = (try? FileManager.default.contentsOfDirectory(at: Paths.ipas, includingPropertiesForKeys: keys)) ?? []
        files = urls.filter { $0.pathExtension.lowercased() == "ipa" }.map { u in
            let v = try? u.resourceValues(forKeys: Set(keys))
            return IPAFile(url: u, size: Int64(v?.fileSize ?? 0), date: v?.contentModificationDate ?? .distantPast)
        }.sorted { $0.date > $1.date }
    }
    /// "<name> game files" beside the IPA (romfs.img and the msl folder), when the build left them out of the IPA
    private func gameFiles(for f: IPAFile) -> (url: URL, size: Int64, image: URL?)? {
        let dir = f.url.deletingPathExtension().path + " game files"
        let u = URL(fileURLWithPath: dir, isDirectory: true)
        guard FileManager.default.fileExists(atPath: u.path) else { return nil }
        let img = u.appendingPathComponent("romfs.img")
        return (u, Storage.size(u), FileManager.default.fileExists(atPath: img.path) ? img : nil)
    }
    private func delete(_ f: IPAFile) {
        try? FileManager.default.removeItem(at: f.url)
        try? FileManager.default.removeItem(at: URL(fileURLWithPath: f.url.deletingPathExtension().path + " game files"))   // nothing left behind
        load()
    }
    private func rename() {
        guard let f = renaming else { return }
        let clean = newName.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: "/", with: "-")
        if !clean.isEmpty { try? FileManager.default.moveItem(at: f.url, to: f.url.deletingLastPathComponent().appendingPathComponent(clean + ".ipa")) }
        renaming = nil; load()
    }
}

/// The Files app, opened on a folder of this app's Documents (the folder is created first: Files only lists what exists).
@MainActor func openInFiles(_ dir: URL) {
    try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    if let u = URL(string: "shareddocuments://" + dir.path.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed)!) { UIApplication.shared.open(u) }
}
