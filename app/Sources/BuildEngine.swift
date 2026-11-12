import SwiftUI
import UIKit

struct JobStatus: Decodable {
    var state: String
    var stage: String?
    var progress: Double?
    var ipa: String?
    var error: String?
    var step: String?
    var detail: String?
    var eta: Double?
    var elapsed: Double?
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
        restoreLastJob()
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

    /// After the app was closed during a build (by the system, usually for memory), show what the build had logged and say so.
    private func restoreLastJob() {
        let fm = FileManager.default
        guard let dirs = try? fm.contentsOfDirectory(at: Paths.jobs, includingPropertiesForKeys: nil).sorted(by: { $0.lastPathComponent < $1.lastPathComponent }),
              let last = dirs.last, let d = try? Data(contentsOf: last.appendingPathComponent("status.json")),
              var st = try? JSONDecoder().decode(JobStatus.self, from: d) else { return }
        jobDir = last
        if st.state == "running" {
            st = JobStatus(state: "failed", stage: st.stage, progress: st.progress, ipa: nil,
                           error: "The app was closed during the last build (usually iOS ending it for memory). The log below shows where it stopped.")
        }
        status = st
        if let t = try? String(contentsOf: last.appendingPathComponent("log.txt"), encoding: .utf8) {
            logTail = Array(t.split(separator: "\n").compactMap { Self.readable(String($0)) }.suffix(250))
        }
        if let n = try? String(contentsOf: last.appendingPathComponent("bg.txt"), encoding: .utf8) { logTail += n.split(separator: "\n").map(String.init) }
    }

    func forgetKeys() { for u in keyFiles { try? FileManager.default.removeItem(at: u) }; keyFiles = [] }

    func remove(_ u: URL) { try? FileManager.default.removeItem(at: u); keyFiles.removeAll { $0 == u }; gameFiles.removeAll { $0 == u } }

    var startedAt: Date?

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
        jobDir = job; running = true; startedAt = .now; status = JobStatus(state: "running", stage: "starting", progress: 0); logTail = []
        BackgroundKeeper.shared.begin(notes: job.appendingPathComponent("bg.txt"))
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
        if let d = try? Data(contentsOf: job.appendingPathComponent("status.json")), let s = try? JSONDecoder().decode(JobStatus.self, from: d) { status = s; BackgroundKeeper.shared.update(progress: s.progress ?? 0, stage: s.stage ?? "working") }
        defer { if let n = try? String(contentsOf: job.appendingPathComponent("bg.txt"), encoding: .utf8) { logTail += n.split(separator: "\n").map(String.init) } }
        if let h = try? FileHandle(forReadingFrom: job.appendingPathComponent("log.txt")) {
            defer { try? h.close() }
            let size = (try? h.seekToEnd()) ?? 0
            let cut = size > 120_000
            try? h.seek(toOffset: cut ? size - 120_000 : 0)
            if let d = try? h.readToEnd(), let s = String(data: d, encoding: .utf8) {
                var lines = s.split(separator: "\n", omittingEmptySubsequences: true).map(String.init)
                if cut { lines.removeFirst() }   // it starts mid-line
                logTail = lines.compactMap { Self.readable($0) }.suffix(250).map { $0 }
            }
        }
    }

    /// A log line as a person reads it: progress events are for the bar, so they are left out here.
    nonisolated static func readable(_ line: String) -> String? {
        if line.hasPrefix("progress: ") || line.hasPrefix("[where]") || line.contains("\"ev\": \"progress\"") { return nil }
        guard line.hasPrefix("{\"ev\""), let j = try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any] else { return line.isEmpty ? nil : line }
        let name = j["name"] as? String ?? ""
        switch j["ev"] as? String {
        case "say": return j["msg"] as? String
        case "stage": return "▶ \(name)"
        case "step": let st = j["step"] as? String ?? ""; return st.isEmpty ? nil : "    \(st)"
        case "stage_end":
            let ok = (j["ok"] as? Bool) ?? true, sum = j["summary"] as? String ?? "", el = j["elapsed"] as? Double ?? 0
            return "\(ok ? "✓" : "✗") \(name)\(sum.isEmpty ? "" : ": \(sum)") (\(Int(el)) s)"
        default: return nil
        }
    }

    private func finish(error: String?) {
        timer?.invalidate(); timer = nil; running = false
        UIApplication.shared.isIdleTimerDisabled = false
        BackgroundKeeper.shared.end(success: error == nil && status?.state == "done")
        if let error { status = JobStatus(state: "failed", stage: nil, progress: nil, ipa: nil, error: error) }
        if status?.state == "done" { for u in gameFiles { try? FileManager.default.removeItem(at: u) }; gameFiles = [] }   // the saved keys stay
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
