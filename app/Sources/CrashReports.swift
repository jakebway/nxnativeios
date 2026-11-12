import Foundation
import MetricKit

/// What iOS itself says about how the app ended (a crash, or being killed for memory, CPU or time). MetricKit hands these over on a later launch,
/// sometimes a day later; they are kept in a file the Settings tab can share.
final class CrashReports: NSObject, MXMetricManagerSubscriber, @unchecked Sendable {
    static let shared = CrashReports()
    static var file: URL { Paths.support.appendingPathComponent("ios-reports.txt") }

    func start() { MXMetricManager.shared.add(self) }

    func didReceive(_ payloads: [MXMetricPayload]) {
        for p in payloads { if let e = p.applicationExitMetrics { append("exit metrics \(p.timeStampBegin) to \(p.timeStampEnd)", e.jsonRepresentation()) } }
    }
    func didReceive(_ payloads: [MXDiagnosticPayload]) {
        for p in payloads { append("diagnostics \(p.timeStampBegin) to \(p.timeStampEnd)", p.jsonRepresentation()) }
    }

    private func append(_ title: String, _ json: Data) {
        let text = "== \(title)\n" + (String(data: json, encoding: .utf8) ?? "") + "\n"
        if let h = try? FileHandle(forWritingTo: Self.file) { defer { try? h.close() }; _ = try? h.seekToEnd(); try? h.write(contentsOf: Data(text.utf8)) }
        else { try? Data(text.utf8).write(to: Self.file) }
    }
}
