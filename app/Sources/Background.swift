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

    /// Before the app finishes launching (App.init).
    nonisolated static func register() {
        BGTaskScheduler.shared.register(forTaskWithIdentifier: taskID, using: nil) { t in
            guard let t = t as? BGContinuedProcessingTask else { t.setTaskCompleted(success: false); return }
            Task { @MainActor in BackgroundKeeper.shared.attach(t) }
        }
    }

    func begin() {
        let r = BGContinuedProcessingTaskRequest(identifier: Self.taskID, title: lastTitle, subtitle: "Starting")
        r.strategy = .queue
        try? BGTaskScheduler.shared.submit(r)
        if UserDefaults.standard.object(forKey: "keepAlive") as? Bool ?? true { startAudio() }
    }

    private func attach(_ t: BGContinuedProcessingTask) {
        task = t
        t.progress.totalUnitCount = 1000
        t.expirationHandler = { /* the build goes on; the silent audio keeps the app alive if the system gives the task up */ }
    }

    func update(progress: Double, stage: String) {
        guard let t = task else { return }
        t.progress.completedUnitCount = Int64(max(0, min(1, progress)) * 1000)
        t.updateTitle(lastTitle, subtitle: stage)
    }

    func end(success: Bool) {
        task?.setTaskCompleted(success: success); task = nil
        player?.stop(); audioNode?.stop(); player = nil; audioNode = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    private func startAudio() {
        guard player == nil else { return }
        let s = AVAudioSession.sharedInstance()
        try? s.setCategory(.playback, mode: .default, options: [.mixWithOthers]); try? s.setActive(true)
        let e = AVAudioEngine(), n = AVAudioPlayerNode()
        guard let fmt = AVAudioFormat(standardFormatWithSampleRate: 44100, channels: 1),
              let buf = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: 44100) else { return }
        buf.frameLength = 44100   // a second of silence, looped
        e.attach(n); e.connect(n, to: e.mainMixerNode, format: fmt)
        do { try e.start() } catch { return }
        n.scheduleBuffer(buf, at: nil, options: .loops); n.play()
        player = e; audioNode = n
    }
}
