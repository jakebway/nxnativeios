import SwiftUI
import UIKit

struct JobStatus: Decodable {
    var state: String
    var stage: String?
    var progress: Double?
    var ipa: String?
    var error: String?
}

@Observable @MainActor
final class BuildEngine {
    var keyFiles: [URL] = []          // copies of the picked key files (prod.keys, title.keys, or a .zip holding them), in Imports/
    var gameFiles: [URL] = []         // copies of the picked games (.nsp / .xci / .zip, updates, DLC), in Imports/
    var picked: [URL] { keyFiles + gameFiles }
    var running = false
    var status: JobStatus?
    var logTail: [String] = []
    var pythonError: String?
    private var jobDir: URL?
    private var timer: Timer?

    private var showFPS: Bool { UserDefaults.standard.object(forKey: "showFPS") as? Bool ?? true }
    private var language: String { UserDefaults.standard.string(forKey: "language") ?? "" }
    private var keepBuild: Bool { UserDefaults.standard.object(forKey: "keepBuild") as? Bool ?? true }

    init() {
        Paths.ensure()
        keyFiles = ((try? FileManager.default.contentsOfDirectory(at: Paths.keys, includingPropertiesForKeys: nil)) ?? [])
            .filter { !$0.lastPathComponent.hasPrefix(".") }.sorted { $0.lastPathComponent < $1.lastPathComponent }
    }

    /// Picked files are copied in right away: a security-scoped URL from Files does not outlive the picker for an hour-long build.
    /// Key files are named by what is inside them (prod.keys / title.keys), so "prod (1).keys" or "prod.keys.txt" still work.
    func add(_ urls: [URL], keys: Bool) {
        for u in urls {
            let ok = u.startAccessingSecurityScopedResource(); defer { if ok { u.stopAccessingSecurityScopedResource() } }
            var name = u.lastPathComponent
            let isZip = u.pathExtension.lowercased() == "zip"
            if keys && !isZip, let kind = Self.keyKind(u) { name = kind }
            let dst = (keys ? Paths.keys : Paths.imports).appendingPathComponent(name)
            try? FileManager.default.removeItem(at: dst)
            do {
                do { try FileManager.default.moveItem(at: u, to: dst) } catch { try FileManager.default.copyItem(at: u, to: dst) }   // the picker's own copy is moved, not copied twice
                if keys { if !keyFiles.contains(dst) { keyFiles.append(dst) } } else if !gameFiles.contains(dst) { gameFiles.append(dst) }
            } catch { logTail.append("could not import \(u.lastPathComponent): \(error.localizedDescription)") }
        }
    }

    /// "prod.keys" if the file has the console keys, "title.keys" if it is a list of 32-hex title keys, else nil (small text files only).
    private static func keyKind(_ u: URL) -> String? {
        guard let size = (try? u.resourceValues(forKeys: [.fileSizeKey]).fileSize), size < 2_000_000,
              let t = try? String(contentsOf: u, encoding: .utf8) else { return nil }
        if t.contains("master_key_00") || t.contains("aes_kek_generation_source") { return "prod.keys" }
        let lines = t.split(whereSeparator: \.isNewline).filter { !$0.hasPrefix("#") && $0.contains("=") }
        if !lines.isEmpty, lines.allSatisfy({ $0.split(separator: "=", maxSplits: 1).first.map { $0.trimmingCharacters(in: .whitespaces).count == 32 } ?? false }) { return "title.keys" }
        return nil
    }

    func forgetKeys() { for u in keyFiles { try? FileManager.default.removeItem(at: u) }; keyFiles = [] }

    func remove(_ u: URL) { try? FileManager.default.removeItem(at: u); keyFiles.removeAll { $0 == u }; gameFiles.removeAll { $0 == u } }

    func start() {
        guard !running, !picked.isEmpty else { return }
        let job = Paths.jobs.appendingPathComponent(ISO8601DateFormatter().string(from: .now).replacingOccurrences(of: ":", with: "-"))
        try? FileManager.default.createDirectory(at: job, withIntermediateDirectories: true)
        var options: [String: Any] = ["show_fps": showFPS, "keep_build": keepBuild]
        if !language.isEmpty { options["language"] = language }
        let cfg: [String: Any] = [
            "inputs": picked.map(\.path), "ipas": Paths.ipas.path, "shells": Paths.resources.appendingPathComponent("shells").path,
            "upstream_zip": Paths.resources.appendingPathComponent("nxnative.zip").path, "upstream": Paths.upstream.path, "options": options,
        ]
        try? JSONSerialization.data(withJSONObject: cfg, options: .prettyPrinted).write(to: job.appendingPathComponent("job.json"))
        jobDir = job; running = true; status = JobStatus(state: "running", stage: "starting", progress: 0); logTail = []
        UIApplication.shared.isIdleTimerDisabled = true   // iOS suspends a background app: keep the screen on while building
        let bundle = Paths.bundle.path, upstream = Paths.upstream.path, jobPath = job.path
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in Task { @MainActor in self?.poll() } }
        Task.detached(priority: .userInitiated) {
            var err = [CChar](repeating: 0, count: 512)
            if nxb_python_start(bundle, upstream, &err, Int32(err.count)) != 0 {
                let msg = String(cString: err)
                await MainActor.run { self.finish(error: "Python did not start: \(msg)") }; return
            }
            _ = nxb_python_build(jobPath)
            await MainActor.run { self.poll(); self.finish(error: nil) }
        }
    }

    private func poll() {
        guard let job = jobDir else { return }
        if let d = try? Data(contentsOf: job.appendingPathComponent("status.json")), let s = try? JSONDecoder().decode(JobStatus.self, from: d) { status = s }
        if let h = try? FileHandle(forReadingFrom: job.appendingPathComponent("log.txt")) {
            defer { try? h.close() }
            let size = (try? h.seekToEnd()) ?? 0
            try? h.seek(toOffset: size > 16000 ? size - 16000 : 0)
            if let d = try? h.readToEnd(), let s = String(data: d, encoding: .utf8) {
                logTail = s.split(separator: "\n").suffix(60).map { line in
                    // progress events are for the bar; show their message, not the JSON
                    if line.hasPrefix("{\"ev\""), let j = try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any] {
                        return (j["msg"] as? String) ?? [j["name"], j["step"]].compactMap { $0 as? String }.joined(separator: ": ")
                    }
                    return String(line)
                }.filter { !$0.isEmpty }
            }
        }
    }

    private func finish(error: String?) {
        timer?.invalidate(); timer = nil; running = false
        UIApplication.shared.isIdleTimerDisabled = false
        if let error { status = JobStatus(state: "failed", stage: nil, progress: nil, ipa: nil, error: error) }
        if status?.state == "done" { for u in gameFiles { try? FileManager.default.removeItem(at: u) }; gameFiles = []   // the saved keys stay }
    }

    var logURL: URL? { jobDir?.appendingPathComponent("log.txt") }

    var selfTest: String?
    func runSelfTest() {
        selfTest = "Running…"
        let bundle = Paths.bundle.path, upstream = Paths.upstream.path
        Task.detached(priority: .userInitiated) {
            var err = [CChar](repeating: 0, count: 512)
            var report: String
            if nxb_python_start(bundle, upstream, &err, Int32(err.count)) != 0 { report = "❌ Python did not start: \(String(cString: err))" }
            else if let r = nxb_python_selftest() { report = String(cString: r); free(r) }
            else { report = "❌ the self-test did not run" }
            let final = report
            await MainActor.run { self.selfTest = final }
        }
    }
}
