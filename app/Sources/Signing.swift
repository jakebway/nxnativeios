import SwiftUI
import Security
import UniformTypeIdentifiers

/// The user's own signing material: a .p12 with its password and a .mobileprovision. They are kept in the app's private storage (the password in the Keychain) and never leave the phone.
@MainActor @Observable final class SigningStore {
    static let shared = SigningStore()
    struct Info { var cert: String?; var profileName: String?; var team: String?; var expires: Date?; var devices: Int?; var appID: String?; var warning: String? }
    var info = Info()
    var message = ""
    private var dir: URL { Paths.support.appendingPathComponent("Signing", isDirectory: true) }
    var p12URL: URL { dir.appendingPathComponent("cert.p12") }
    var profileURL: URL { dir.appendingPathComponent("profile.mobileprovision") }
    var password: String { Keychain.get("p12password") ?? "" }
    var ready: Bool { info.cert != nil && info.profileName != nil }

    init() { try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true); refresh() }

    func importFile(_ url: URL, kind: Kind) {
        let access = url.startAccessingSecurityScopedResource(); defer { if access { url.stopAccessingSecurityScopedResource() } }
        do {
            let data = try Data(contentsOf: url)
            switch kind {
            case .p12: try data.write(to: p12URL, options: .atomic)
            case .profile: try data.write(to: profileURL, options: .atomic)
            }
            message = ""
        } catch { message = "Could not read that file: \(error.localizedDescription)" }
        refresh()
    }

    func setPassword(_ p: String) { Keychain.set("p12password", p); refresh() }

    func forget() {
        try? FileManager.default.removeItem(at: p12URL); try? FileManager.default.removeItem(at: profileURL); Keychain.set("p12password", ""); info = Info(); message = ""
    }

    enum Kind { case p12, profile }

    /// Reads both files and checks that the certificate opens with the password and is one the profile lists.
    func refresh() {
        var i = Info(); var certDER: Data?
        if let data = try? Data(contentsOf: p12URL) {
            var items: CFArray?
            let st = SecPKCS12Import(data as CFData, [kSecImportExportPassphrase as String: password] as CFDictionary, &items)
            if st == errSecSuccess, let d = (items as? [[String: Any]])?.first, let idRef = d[kSecImportItemIdentity as String] {
                var cert: SecCertificate?; SecIdentityCopyCertificate(idRef as! SecIdentity, &cert)
                if let cert { i.cert = SecCertificateCopySubjectSummary(cert) as String? ?? "certificate"; certDER = SecCertificateCopyData(cert) as Data }
            } else if st == errSecAuthFailed || st == errSecPkcs12VerifyFailure { i.warning = "The .p12 is saved, but the password is wrong." }
            else { i.warning = "That .p12 could not be opened (error \(st))." }
        }
        if let data = try? Data(contentsOf: profileURL), let plist = Self.profilePlist(data) {
            i.profileName = plist["Name"] as? String; i.team = (plist["TeamName"] as? String) ?? (plist["TeamIdentifier"] as? [String])?.first
            i.expires = plist["ExpirationDate"] as? Date; i.devices = (plist["ProvisionedDevices"] as? [String])?.count
            i.appID = ((plist["Entitlements"] as? [String: Any])?["application-identifier"] as? String)
            if let e = i.expires, e < Date() { i.warning = "The provisioning profile has expired." }
            if let der = certDER, let certs = plist["DeveloperCertificates"] as? [Data], !certs.contains(der), i.warning == nil { i.warning = "This profile does not list that certificate: signing with the pair will fail." }
        } else if FileManager.default.fileExists(atPath: profileURL.path) { i.warning = "That file is not a provisioning profile." }
        info = i
    }

    /// A .mobileprovision is a signed (CMS) wrapper around an XML plist: the plist is the part between its own tags.
    static func profilePlist(_ data: Data) -> [String: Any]? {
        guard let a = data.range(of: Data("<?xml".utf8)), let b = data.range(of: Data("</plist>".utf8)) else { return nil }
        return (try? PropertyListSerialization.propertyList(from: data[a.lowerBound..<b.upperBound], format: nil)) as? [String: Any]
    }
}

enum Keychain {
    static func set(_ key: String, _ value: String) {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrAccount as String: key, kSecAttrService as String: "org.nxnativeios.signing"]
        SecItemDelete(q as CFDictionary)
        guard !value.isEmpty else { return }
        SecItemAdd(q.merging([kSecValueData as String: Data(value.utf8), kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]) { $1 } as CFDictionary, nil)
    }
    static func get(_ key: String) -> String? {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrAccount as String: key, kSecAttrService as String: "org.nxnativeios.signing", kSecReturnData as String: true]
        var r: AnyObject?; guard SecItemCopyMatching(q as CFDictionary, &r) == errSecSuccess, let d = r as? Data else { return nil }
        return String(data: d, encoding: .utf8)
    }
}

/// Settings → Signing: the certificate, its password and the profile the app signs a built game with.
struct SigningSection: View {
    @State private var store = SigningStore.shared
    @State private var password = ""
    @AppStorage("signLocally") private var signLocally = true
    /// The same UIKit picker as Add keys / Add game (SwiftUI's fileImporter does nothing useful here)
    private func pick(_ k: SigningStore.Kind) {
        if k == .p12 { store.setPassword(password) }
        DocPicker.present { urls in if let u = urls.first { store.importFile(u, kind: k) } }
    }

    var body: some View {
        Section {
            Button { pick(.p12) } label: { Label(store.info.cert.map { "Certificate: \($0)" } ?? "Add certificate (.p12)", systemImage: store.info.cert == nil ? "plus.circle" : "checkmark.seal.fill") }
            SecureField("Certificate password", text: $password).textContentType(.password).submitLabel(.done)
                .onSubmit { store.setPassword(password) }
            Button { pick(.profile) } label: { Label(store.info.profileName.map { "Profile: \($0)" } ?? "Add provisioning profile (.mobileprovision)", systemImage: store.info.profileName == nil ? "plus.circle" : "checkmark.seal.fill") }
            if store.ready { Toggle("Sign built games with this certificate", isOn: $signLocally) }
            if let e = store.info.expires { LabeledContent("Profile expires", value: e.formatted(date: .abbreviated, time: .omitted)) }
            if let d = store.info.devices { LabeledContent("Devices in the profile", value: "\(d)") }
            if let w = store.info.warning { Label(w, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange).font(.footnote) }
            if !store.message.isEmpty { Text(store.message).font(.footnote).foregroundStyle(.red) }
            if store.info.cert != nil || store.info.profileName != nil { Button("Forget certificate and profile", role: .destructive) { store.forget(); password = "" } }
        } header: { Text("Signing") } footer: {
            Text("Your own .p12, its password and a .mobileprovision that lists this phone. They stay on this phone; the password is kept in the Keychain.")
        }
        .onAppear { password = store.password }
    }
}
