import SwiftUI

@main
struct NXnativeiOSApp: App {
    @State private var engine = BuildEngine()
    init() { BackgroundKeeper.register(); CrashReports.shared.start() }
    var body: some Scene {
        WindowGroup {
            TabView(selection: Bindable(engine).tab) {
                Tab("Build", systemImage: "hammer", value: 0) { BuildView() }
                Tab("IPAs", systemImage: "shippingbox", value: 1) { IPAsView() }
                Tab("Settings", systemImage: "gearshape", value: 2) { SettingsView() }
            }
            .environment(engine)
        }
    }
}

enum Paths {
    static let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
    static let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
    static let ipas = documents.appendingPathComponent("IPAs", isDirectory: true)
    static let jobs = support.appendingPathComponent("Jobs", isDirectory: true)
    static let imports = support.appendingPathComponent("Imports", isDirectory: true)
    static let keys = support.appendingPathComponent("Keys", isDirectory: true)   // the keys the user entered once; they stay on the phone
    static let upstream = support.appendingPathComponent("nxnative", isDirectory: true)
    static let bundle = Bundle.main.bundleURL
    static let resources = Bundle.main.resourceURL!.appendingPathComponent("NXData")
    static func ensure() {
        for d in [ipas, jobs, imports, keys] { try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true) }
    }
}
