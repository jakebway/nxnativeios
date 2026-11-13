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
    private var keepBuild: Bool { false }   // the work files (extracted game, rewritten code, shaders) are deleted as soon as the build ends: only the IPA stays

    init() {
        Paths.ensure()
        Self.purgeOldJobs()
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
        if let t = try? String(contentsOf: last.appendingPathComponent("story.txt"), encoding: .utf8) {
            logTail = Array(t.split(separator: "\n").compactMap { Self.readable(String($0)) }.suffix(250))
        }
    }

    func forgetKeys() { for u in keyFiles { try? FileManager.default.removeItem(at: u) }; keyFiles = [] }

    func remove(_ u: URL) { try? FileManager.default.removeItem(at: u); keyFiles.removeAll { $0 == u }; gameFiles.removeAll { $0 == u } }

    var startedAt: Date?
    var tab = 0                        // the selected tab: 0 Build, 1 IPAs, 2 Settings
    var gameName: String? { gameFiles.first.map { $0.deletingPathExtension().lastPathComponent } }

    func start() {
        guard !running, !picked.isEmpty else { return }
        let job = Paths.jobs.appendingPathComponent(ISO8601DateFormatter().string(from: .now).replacingOccurrences(of: ":", with: "-"))
        try? FileManager.default.createDirectory(at: job, withIntermediateDirectories: true)
        var options: [String: Any] = ["show_fps": showFPS, "keep_build": keepBuild, "fast_build": UserDefaults.standard.object(forKey: "fastBuild") as? Bool ?? true, "small_ipa": UserDefaults.standard.object(forKey: "smallIPA") as? Bool ?? false]
        if !language.isEmpty { options["language"] = language }
        let cfg: [String: Any] = [
            "inputs": picked.map(\.path), "ipas": Paths.ipas.path, "shells": Paths.resources.appendingPathComponent("shells").path,
            "upstream_zip": Paths.resources.appendingPathComponent("nxnative.zip").path, "upstream": Paths.upstream.path, "options": options,
        ]
        try? JSONSerialization.data(withJSONObject: cfg, options: .prettyPrinted).write(to: job.appendingPathComponent("job.json"))
        jobDir = job; running = true; startedAt = .now; status = JobStatus(state: "running", stage: "starting", progress: 0); logTail = []
        BackgroundKeeper.shared.begin(notes: job.appendingPathComponent("log.txt"))   // in the log itself, so a shared log shows them
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

    private var polls = 0
    private func poll() {
        guard let job = jobDir else { return }
        polls += 1
        if polls % 15 == 0 { BackgroundKeeper.note("app alive (\(UIApplication.shared.applicationState == .active ? "foreground" : "background"))") }
        if let d = try? Data(contentsOf: job.appendingPathComponent("status.json")), let s = try? JSONDecoder().decode(JobStatus.self, from: d) { status = s; BackgroundKeeper.shared.update(progress: s.progress ?? 0, stage: s.stage ?? "working") }
        if let h = try? FileHandle(forReadingFrom: job.appendingPathComponent("story.txt")) {
            defer { try? h.close() }
            let size = (try? h.seekToEnd()) ?? 0
            let cut = size > 120_000
            try? h.seek(toOffset: cut ? size - 120_000 : 0)
            if let d = try? h.readToEnd(), let s = String(data: d, encoding: .utf8) {
                var lines = s.split(separator: "\n", omittingEmptySubsequences: true).map(String.init)
                if cut, !lines.isEmpty { lines.removeFirst() }   // it starts mid-line
                logTail = lines.compactMap { Self.readable($0) }.suffix(250).map { $0 }
            }
        }
    }

    /// A log line as a person reads it: progress events are for the bar, so they are left out here.
    nonisolated static func readable(_ line: String) -> String? {
        // The app's log is the build's story only (what was read, each step, what went wrong); everything for debugging stays in the full log (Settings → Diagnostics).
        if line.hasPrefix("[") && !line.hasPrefix("[RED]") { return nil }                                  // [where], [memory], [bg], [py], [limits], [fatal] ...
        if line.hasPrefix("progress: ") || line.hasPrefix("frame step") || line.hasPrefix("function patch") || line.hasPrefix("    File ") || line.hasPrefix("  File ") { return nil }
        if line.contains("\"ev\": \"progress\"") || line.hasPrefix("shaders: ") || line.hasPrefix("main {") || line.hasPrefix("subsdk0 {") || line.hasPrefix("sdk {") { return nil }
        if !line.hasPrefix("{\"ev\"") { let ok = ["input:", "keys:", "game:", "rar:", "done:", "unpacking nxnative", "Traceback", "RuntimeError", "BuildError"]; if !ok.contains(where: { line.hasPrefix($0) }) { return nil } }
        guard line.hasPrefix("{\"ev\""), let j = try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any] else { return line.isEmpty ? nil : line }
        let name = j["name"] as? String ?? ""
        switch j["ev"] as? String {
        case "say":
            let m = j["msg"] as? String ?? ""
            return (m.contains("work folder") || m.contains("output IPA") || m.contains("Documents/env.txt")) ? nil : m
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
        if let j = jobDir { Self.cleanWork(j) }
        if status?.state == "done" { for u in gameFiles { try? FileManager.default.removeItem(at: u) }; gameFiles = [] }   // the saved keys stay
    }

    /// Work files are huge (the extracted game alone is as big as the game): only the log and status of a job stay.
    nonisolated static func cleanWork(_ job: URL) {
        for n in ["build", "input", "extract"] { try? FileManager.default.removeItem(at: job.appendingPathComponent(n)) }
    }

    /// At launch: older jobs go entirely, the last one keeps its log.
    nonisolated static func purgeOldJobs() {
        guard let dirs = try? FileManager.default.contentsOfDirectory(at: Paths.jobs, includingPropertiesForKeys: nil).sorted(by: { $0.lastPathComponent < $1.lastPathComponent }) else { return }
        for d in dirs.dropLast() { try? FileManager.default.removeItem(at: d) }
        if let last = dirs.last { cleanWork(last) }
    }

    var logURL: URL? { jobDir?.appendingPathComponent("log.txt") }
    /// The newest job's complete log (also after a restart), for the Diagnostics section.
    var lastLogURL: URL? {
        let dirs = (try? FileManager.default.contentsOfDirectory(at: Paths.jobs, includingPropertiesForKeys: nil))?.sorted { $0.lastPathComponent < $1.lastPathComponent }
        guard let u = dirs?.last?.appendingPathComponent("log.txt"), FileManager.default.fileExists(atPath: u.path) else { return nil }
        return u
    }

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
