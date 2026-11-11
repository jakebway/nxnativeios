import SwiftUI

@main
struct NXnativeiOSApp: App {
    @State private var engine = BuildEngine()
    var body: some Scene {
        WindowGroup {
            TabView {
                Tab("Build", systemImage: "hammer") { BuildView() }
                Tab("IPAs", systemImage: "shippingbox") { IPAsView() }
                Tab("Settings", systemImage: "gearshape") { SettingsView() }
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
    static let upstream = support.appendingPathComponent("nxnative", isDirectory: true)
    static let bundle = Bundle.main.bundleURL
    static let resources = Bundle.main.resourceURL!.appendingPathComponent("NXData")
    static func ensure() {
        for d in [ipas, jobs, imports] { try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true) }
    }
}
