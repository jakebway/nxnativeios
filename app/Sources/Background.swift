import AVFoundation
import BackgroundTasks
import UIKit

/// Keeps a long build running when the user leaves the app.
///  1. iOS 26's continued processing task: a user-started job the system lets run in the background, with a progress card.
///  2. Silent audio (the "audio" background mode): a fallback the system does not time out; it can be switched off in Settings.
/// The build itself runs on its own thread either way; this only keeps the app from being suspended.
@MainActor
final class BackgroundKeeper {
    static let shared = BackgroundKeeper()
    nonisolated static let taskID = "org.nxnativeios.builder.build"

    private var task: BGContinuedProcessingTask?
    private var player: AVAudioEngine?
    private var audioNode: AVAudioPlayerNode?
    private var lastTitle = "Building your game"
    private var grace: UIBackgroundTaskIdentifier = .invalid
    private var observers: [NSObjectProtocol] = []
    private var active = false

    /// Where background events are written (next to the job's log), so a failure in the background can be diagnosed afterwards.
    nonisolated(unsafe) static var notesPath: String?
    nonisolated static func note(_ text: String) {
        guard let p = notesPath else { return }
        let line = "[bg \(Date().formatted(date: .omitted, time: .standard))] \(text)\n"
        let fd = open(p, O_WRONLY | O_APPEND | O_CREAT, 0o644)   // appended whole, beside the build's own lines
        guard fd >= 0 else { return }
        defer { close(fd) }
        _ = line.utf8CString.withUnsafeBufferPointer { write(fd, $0.baseAddress, $0.count - 1) }
    }

    /// Before the app finishes launching (App.init).
    nonisolated static func register() {
        BGTaskScheduler.shared.register(forTaskWithIdentifier: taskID, using: nil) { t in
            guard let t = t as? BGContinuedProcessingTask else { t.setTaskCompleted(success: false); return }
            Task { @MainActor in BackgroundKeeper.shared.attach(t) }
        }
    }

    func begin(notes: URL) {
        Self.notesPath = notes.path; active = true; shown = 0
        // The system's progress card is off unless asked for: a build that ended every time right after the shader split, with the card showing "Task failed", while the app was in the foreground.
        if UserDefaults.standard.bool(forKey: "systemCard") {
            let r = BGContinuedProcessingTaskRequest(identifier: Self.taskID, title: lastTitle, subtitle: "Starting")
            r.strategy = .queue
            do { try BGTaskScheduler.shared.submit(r); Self.note("background task requested") }
            catch { Self.note("background task refused: \(error.localizedDescription)") }
        } else { Self.note("no iOS progress card (off in Settings)") }
        if UserDefaults.standard.object(forKey: "keepAlive") as? Bool ?? true { startAudio() }
        // A few extra seconds of grace if the app is sent to the background while nothing else is keeping it alive.
        grace = UIApplication.shared.beginBackgroundTask(withName: "build") { [weak self] in
            Self.note("the system ended the short grace period")
            MainActor.assumeIsolated { if let g = self?.grace, g != .invalid { UIApplication.shared.endBackgroundTask(g); self?.grace = .invalid } }   // not ending it gets the app killed
        }
        let nc = NotificationCenter.default
        observers = [
            nc.addObserver(forName: UIApplication.didEnterBackgroundNotification, object: nil, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { Self.note("app went to the background; audio \(self?.player?.isRunning == true ? "running" : "NOT running"); task \(self?.task == nil ? "not granted" : "granted")") }
            },
            nc.addObserver(forName: UIApplication.willEnterForegroundNotification, object: nil, queue: .main) { _ in Self.note("app is back in the foreground") },
            nc.addObserver(forName: UIApplication.didReceiveMemoryWarningNotification, object: nil, queue: .main) { _ in Self.note("MEMORY WARNING from iOS") },
            nc.addObserver(forName: AVAudioSession.interruptionNotification, object: nil, queue: .main) { [weak self] n in
                let type = (n.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt).flatMap(AVAudioSession.InterruptionType.init(rawValue:))
                MainActor.assumeIsolated { Self.note("audio interruption \(type == .began ? "began" : "ended")"); if type == .ended { self?.restartAudio() } }
            },
            nc.addObserver(forName: .AVAudioEngineConfigurationChange, object: nil, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { Self.note("audio engine reconfigured"); self?.restartAudio() }
            },
        ]
    }

    private func attach(_ t: BGContinuedProcessingTask) {
        guard active else { t.setTaskCompleted(success: true); return }
        task = t
        t.progress.totalUnitCount = Self.units
        t.expirationHandler = Self.expiry(t)
        Self.note("background task granted")
    }

    /// iOS kills the whole app when an expired task is not marked complete: the handler completes it at once (the build goes on, kept alive by the silent audio).
    /// Built outside the main actor: iOS calls the handler on its own queue.
    nonisolated private static func expiry(_ t: BGContinuedProcessingTask) -> @Sendable () -> Void {
        nonisolated(unsafe) let t = t
        return {
            t.setTaskCompleted(success: true)
            BackgroundKeeper.note("the system ended the background task; the build goes on")
            Task { @MainActor in BackgroundKeeper.shared.task = nil }
        }
    }

    nonisolated static let units: Int64 = 1_000_000
    private var shown: Int64 = 0

    /// iOS expires a continued processing task whose progress stops moving, and long steps (a module rewrite, the end of the shader split) report nothing for minutes:
    /// the card's count creeps up by a little every update, never past the real progress by more than the step to the end.
    func update(progress: Double, stage: String) {
        guard let t = task else { return }
        let real = Int64(max(0, min(1, progress)) * Double(Self.units))
        shown = min(Self.units - 1, max(real, shown + max(1, (Self.units - shown) / 2000)))
        t.progress.completedUnitCount = shown
        t.updateTitle(lastTitle, subtitle: stage)
    }

    func end(success: Bool) {
        active = false
        task?.setTaskCompleted(success: success); task = nil
        observers.forEach(NotificationCenter.default.removeObserver); observers = []
        player?.stop(); audioNode?.stop(); player = nil; audioNode = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        if grace != .invalid { UIApplication.shared.endBackgroundTask(grace); grace = .invalid }
        Self.note("build finished")
    }

    private func restartAudio() {
        guard active else { return }
        player?.stop(); audioNode?.stop(); player = nil; audioNode = nil
        if UserDefaults.standard.object(forKey: "keepAlive") as? Bool ?? true { startAudio() }
    }

    private func startAudio() {
        guard player == nil else { return }
        let s = AVAudioSession.sharedInstance()
        do { try s.setCategory(.playback, mode: .default, options: [.mixWithOthers]); try s.setActive(true) }
        catch { Self.note("audio session failed: \(error.localizedDescription)"); return }
        let e = AVAudioEngine(), n = AVAudioPlayerNode()
        guard let fmt = AVAudioFormat(standardFormatWithSampleRate: 44100, channels: 1),
              let buf = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: 44100) else { return }
        buf.frameLength = 44100   // a second of silence, looped
        e.attach(n); e.connect(n, to: e.mainMixerNode, format: fmt)
        do { try e.start() } catch { Self.note("audio engine failed: \(error.localizedDescription)"); return }
        n.scheduleBuffer(buf, at: nil, options: .loops); n.play()
        player = e; audioNode = n
        Self.note("silent audio started")
    }
}
