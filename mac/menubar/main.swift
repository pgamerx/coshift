// ClaudeSwitchMenu: menu bar front-end for claude-switch.
// It only ever runs `claude-switch status|list|use <name>|toggle|side-by-side[-close] <name>` and opens the Coshift board
// page (board/board.py web --open). It never touches data folders.
import AppKit
import Foundation
import ServiceManagement

// MARK: - Model (pure, testable)

struct Profile: Equatable {
    let name: String        // real profile name; the only thing ever passed to claude-switch
    let active: Bool
    let incomplete: Bool
}

struct MenuItemSpec: Equatable {
    let title: String
    let action: String   // "toggle", "use:<name>", "sbs:<name>", "sbsclose:<name>", "rename", "login", "showname", "refresh", "quit", "noop", "none", "sep"
    let enabled: Bool
    let checked: Bool
    let key: String?     // Command-<key> shortcut, if any
}

func spec(_ title: String, _ action: String, enabled: Bool = true, checked: Bool = false,
          key: String? = nil) -> MenuItemSpec {
    MenuItemSpec(title: title, action: action, enabled: enabled, checked: checked, key: key)
}

func parseActive(status: String) -> String? {
    for line in status.split(separator: "\n") where line.hasPrefix("Active profile") {
        guard let r = line.range(of: ":") else { continue }
        let v = line[r.upperBound...].trimmingCharacters(in: .whitespaces)
        if v.isEmpty || v.hasPrefix("<") { return nil }
        return v
    }
    return nil
}

/// True when `claude-switch status` reports a second window (side-by-side instance) running.
func parseSideBySide(status: String) -> Bool {
    status.split(separator: "\n").contains { $0.hasPrefix("Side-by-side") && $0.contains("running") }
}

func parseProfiles(list: String) -> [Profile] {
    var out: [Profile] = []
    for line in list.split(separator: "\n") {
        guard line.hasPrefix("* ") || line.hasPrefix("  ") else { continue }
        let rest = line.dropFirst(2)
        guard let name = rest.split(separator: " ").first else { continue }
        out.append(Profile(name: String(name), active: line.hasPrefix("* "),
                           incomplete: rest.contains("incomplete")))
    }
    return out
}

// MARK: - Display names (stored only in names.json; never touches claude-switch or its folders)

let maxNameLength = 20
let iconPresets: [(label: String, emoji: String)] = [
    ("None", ""), ("Briefcase", "\u{1F4BC}"), ("House", "\u{1F3E0}"), ("Flask", "\u{1F9EA}"),
    ("Star", "\u{2B50}"), ("Lock", "\u{1F512}"), ("Rocket", "\u{1F680}"),
]

/// Accent palette: mid-tone colors that stay readable on light and dark menu bars and wallpapers.
let accentPalette: [(id: String, label: String, rgb: (CGFloat, CGFloat, CGFloat))] = [
    ("orange", "Orange", (0.91, 0.50, 0.25)),
    ("blue",   "Blue",   (0.29, 0.55, 0.96)),
    ("green",  "Green",  (0.20, 0.68, 0.43)),
    ("purple", "Purple", (0.62, 0.43, 0.95)),
    ("pink",   "Pink",   (0.93, 0.40, 0.60)),
    ("teal",   "Teal",   (0.15, 0.65, 0.70)),
]
func validAccent(_ id: String?) -> Bool { id.map { i in accentPalette.contains { $0.id == i } } ?? false }

struct NameEntry: Equatable {
    var name: String
    var icon: String?
    var color: String? = nil   // accent id from accentPalette
}

/// App-wide options kept in the same file under the reserved key "@settings" (not a valid profile name).
struct Settings: Equatable {
    var showName = true
}
let settingsKey = "@settings"

/// Returns the trimmed name, or an error message.
func validateDisplayName(_ raw: String, for real: String, taken others: [String: String]) -> Result<String, NameError> {
    let name = raw.trimmingCharacters(in: .whitespacesAndNewlines)
    if name.isEmpty { return .failure(NameError(message: "The name can't be empty.")) }
    if name.count > maxNameLength { return .failure(NameError(message: "Use at most \(maxNameLength) characters (this is \(name.count)).")) }
    if name.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) || $0 == "\n" }) {
        return .failure(NameError(message: "The name can't contain control characters."))
    }
    for (other, shown) in others where other != real && shown.lowercased() == name.lowercased() {
        return .failure(NameError(message: "\u{201C}\(shown)\u{201D} is already used by profile \u{201C}\(other)\u{201D}."))
    }
    return .success(name)
}

func namesFilePath() -> String {
    ProcessInfo.processInfo.environment["CLAUDE_SWITCH_MENU_NAMES"]
        ?? (NSHomeDirectory() + "/Library/Application Support/ClaudeSwitchMenu/names.json")
}

/// Loads names.json. A missing or broken file yields an empty map (callers fall back to real names).
func loadNames(path: String = namesFilePath()) -> (entries: [String: NameEntry], settings: Settings, broken: Bool) {
    guard let data = FileManager.default.contents(atPath: path) else { return ([:], Settings(), false) }
    guard let obj = try? JSONSerialization.jsonObject(with: data), let dict = obj as? [String: Any] else {
        return ([:], Settings(), true)
    }
    var settings = Settings()
    if let o = dict[settingsKey] as? [String: Any], let v = o["showName"] as? Bool { settings.showName = v }
    var out: [String: NameEntry] = [:]
    var used = Set<String>()
    for key in dict.keys.sorted() where validName(key) {
        var name: String?, icon: String?, color: String?
        if let s = dict[key] as? String { name = s }
        else if let o = dict[key] as? [String: Any] {
            name = o["name"] as? String; icon = o["icon"] as? String; color = o["color"] as? String
        }
        guard let raw = name else { continue }
        let t = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty, t.count <= maxNameLength, !used.contains(t.lowercased()) else { continue }
        used.insert(t.lowercased())
        let ic = icon.flatMap { i in iconPresets.contains(where: { $0.emoji == i && !i.isEmpty }) ? i : nil }
        out[key] = NameEntry(name: t, icon: ic, color: validAccent(color) ? color : nil)
    }
    return (out, settings, false)
}

struct NameError: Error { let message: String }

enum SaveError: Error { case failed(String) }

/// Atomic write; folder is created 700 and the file 600. A broken existing file is moved aside, not deleted.
func saveNames(_ entries: [String: NameEntry], settings: Settings, path: String = namesFilePath()) throws {
    let fm = FileManager.default
    let dir = (path as NSString).deletingLastPathComponent
    do {
        if !fm.fileExists(atPath: dir) {
            try fm.createDirectory(atPath: dir, withIntermediateDirectories: true,
                                   attributes: [.posixPermissions: 0o700])
        }
        if fm.fileExists(atPath: path), loadNames(path: path).broken {
            try fm.moveItem(atPath: path, toPath: path + ".broken.\(Int(Date().timeIntervalSince1970))")
        }
        var obj: [String: Any] = [:]
        for (k, v) in entries {
            var o: [String: Any] = ["name": v.name]
            if let i = v.icon { o["icon"] = i }
            if let c = v.color { o["color"] = c }
            obj[k] = o.count == 1 ? v.name : o
        }
        obj[settingsKey] = ["showName": settings.showName]
        let data = try JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted, .sortedKeys])
        try data.write(to: URL(fileURLWithPath: path), options: .atomic)
        try fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path)
    } catch {
        throw SaveError.failed(error.localizedDescription)
    }
}

func displayName(_ real: String, _ names: [String: NameEntry]) -> String { names[real]?.name ?? real }

/// Name plus optional icon emoji, as shown in the menu rows (the menu bar never shows the emoji).
func displayText(_ real: String, _ names: [String: NameEntry]) -> String {
    let n = displayName(real, names)
    if let i = names[real]?.icon { return "\(i) \(n)" }
    return n
}

/// Accent per profile: the stored one if valid, otherwise the first palette color no other profile uses
/// (in list order, so `main` gets orange and `second` blue); cycles if there are more profiles than colors.
func resolveAccents(_ reals: [String], _ names: [String: NameEntry]) -> [String: String] {
    var out: [String: String] = [:]
    for r in reals { if let c = names[r]?.color { out[r] = c } }
    var taken = Set(out.values)
    for (i, r) in reals.enumerated() where out[r] == nil {
        let free = accentPalette.first { !taken.contains($0.id) }?.id ?? accentPalette[i % accentPalette.count].id
        out[r] = free
        taken.insert(free)
    }
    return out
}

struct BarLabel: Equatable {
    let symbol: String   // SF Symbol
    let tint: String     // accent id, or "grey"
    let text: String     // empty = sparkle only
}

let barSymbol = "sparkle"
let barMaxChars = 24

func barText(_ name: String) -> String { name.count > barMaxChars ? String(name.prefix(barMaxChars - 1)) + "\u{2026}" : name }

func barLabel(active: String?, switching: Bool, names: [String: NameEntry], showName: Bool = true,
              accents: [String: String] = [:]) -> BarLabel {
    if switching { return BarLabel(symbol: barSymbol, tint: "grey", text: "Switching") }
    guard let a = active else { return BarLabel(symbol: barSymbol, tint: "grey", text: showName ? "?" : "") }
    return BarLabel(symbol: barSymbol, tint: accents[a] ?? resolveAccents([a], names)[a] ?? "grey",
                    text: showName ? barText(displayName(a, names)) : "")
}

/// Launch-at-login state, as reported by SMAppService (never touches profiles or claude-switch).
enum LoginState { case off, on, needsApproval, unavailable }

func loginState() -> LoginState {
    guard #available(macOS 13.0, *) else { return .unavailable }
    switch SMAppService.mainApp.status {
    case .enabled: return .on
    case .requiresApproval: return .needsApproval
    default: return .off
    }
}

/// Registers/unregisters this app as a login item. Returns an error message on failure.
func setLaunchAtLogin(_ on: Bool) -> String? {
    guard #available(macOS 13.0, *) else { return "Launch at Login needs macOS 13 or newer." }
    do {
        if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
        return nil
    } catch { return error.localizedDescription }
}

func buildMenu(active: String?, profiles: [Profile], switching: Bool, names: [String: NameEntry],
               login: LoginState = .off, showName: Bool = true, sideBySide: Bool = false) -> [MenuItemSpec] {
    var m: [MenuItemSpec] = []
    let sep = spec("-", "sep", enabled: false)
    if profiles.isEmpty { m.append(spec("No profiles found", "none", enabled: false)) }
    for p in profiles {
        let isActive = p.name == active
        let t = displayText(p.name, names) + (p.incomplete ? " (incomplete)" : "")
        // The active row is a no-op (never re-runs a switch); it is just enabled so it reads at full contrast.
        // Switching to a profile that's open side by side closes that instance first (claude-switch use does it).
        m.append(spec(t, isActive ? "noop" : "use:\(p.name)", enabled: !switching && !p.incomplete, checked: isActive))
    }
    m.append(sep)
    let others = profiles.filter { $0.name != active && !$0.incomplete }
    if let o = others.first {
        // `toggle` is main <-> second; only offered when there is exactly one other profile.
        let action = (profiles.count == 2 || others.count == 1) ? "toggle" : "use:\(o.name)"
        m.append(spec("Switch to \(displayText(o.name, names))", action, enabled: !switching, key: "s"))
        // Closing its window doesn't quit the second instance on macOS, so offer to close it here.
        m.append(sideBySide
                 ? spec("Close \(displayText(o.name, names)) Side by Side", "sbsclose:\(o.name)", enabled: !switching, key: "o")
                 : spec("Open \(displayText(o.name, names)) Side by Side", "sbs:\(o.name)", enabled: !switching, key: "o"))
    } else {
        m.append(spec("No other profile", "none", enabled: false))
    }
    m.append(spec("Open Coshift Board", "board", key: "b"))
    m.append(spec("Rename...", "rename", enabled: !switching && !profiles.isEmpty, key: "r"))
    m.append(sep)
    m.append(spec(login == .needsApproval ? "Launch at Login (needs approval...)" : "Launch at Login", "login",
                  enabled: !switching && login != .unavailable, checked: login == .on))
    m.append(spec("Show Name in Menu Bar", "showname", enabled: !switching, checked: showName))
    m.append(spec("Refresh", "refresh", enabled: !switching))
    m.append(sep)
    m.append(spec("Quit", "quit", key: "q"))
    return m
}

func validName(_ s: String) -> Bool {
    !s.isEmpty && s.range(of: "^[A-Za-z0-9._-]+$", options: .regularExpression) != nil
}

// MARK: - Running claude-switch

let switchBin: String = ProcessInfo.processInfo.environment["CLAUDE_SWITCH_BIN"]
    ?? (NSHomeDirectory() + "/bin/claude-switch")

func run(_ args: [String]) -> (code: Int32, out: String) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: switchBin)
    p.arguments = args
    var env = ProcessInfo.processInfo.environment
    env["PATH"] = "\(NSHomeDirectory())/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    p.environment = env
    let pipe = Pipe()
    p.standardOutput = pipe
    p.standardError = pipe
    do { try p.run() } catch { return (127, "cannot run \(switchBin): \(error.localizedDescription)") }
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    return (p.terminationStatus, String(decoding: data, as: UTF8.self))
}

func notify(title: String, message: String) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
    p.arguments = ["-e", "on run argv", "-e", "display notification (item 1 of argv) with title (item 2 of argv)",
                   "-e", "end run", String(message.prefix(400)), title]
    try? p.run()
}

// MARK: - Dry-run / mock mode (no GUI, no claude-switch calls when MOCK_* are set)
// ClaudeSwitchMenu --print-menu   uses MOCK_STATUS / MOCK_LIST (else real read-only status/list)
// and CLAUDE_SWITCH_MENU_NAMES (path of names.json to read).

func printMenu() {
    let env = ProcessInfo.processInfo.environment
    let status = env["MOCK_STATUS"] ?? run(["status"]).out
    let list = env["MOCK_LIST"] ?? run(["list"]).out
    let active = parseActive(status: status)
    let loaded = loadNames()
    let profiles = parseProfiles(list: list)
    let accents = resolveAccents(profiles.map { $0.name }, loaded.entries)
    let login: LoginState = {
        switch env["MOCK_LOGIN"] ?? "" { case "on": return .on; case "approval": return .needsApproval; default: return .off }
    }()
    print("names.json: \(loaded.broken ? "BROKEN -> real names, defaults" : loaded.entries.isEmpty ? "none/empty -> real names" : "\(loaded.entries.count) entries"); showName=\(loaded.settings.showName)")
    print("accents: " + profiles.map { "\($0.name)=\(accents[$0.name] ?? "?")" }.joined(separator: " "))
    for switching in [false, true] {
        print("== switching=\(switching) ==")
        let l = barLabel(active: active, switching: switching, names: loaded.entries,
                         showName: loaded.settings.showName, accents: accents)
        print("bar: [\(l.symbol), medium, tint=\(l.tint)]" + (l.text.isEmpty ? "  (sparkle only)" : " \"\(l.text)\""))
        for i in buildMenu(active: active, profiles: profiles, switching: switching, names: loaded.entries,
                           login: login, showName: loaded.settings.showName,
                           sideBySide: parseSideBySide(status: status)) {
            if i.action == "sep" { print("  ----"); continue }
            print("  [\(i.checked ? "x" : " ")] \(i.title)"
                  + (i.key.map { "    Cmd-\($0.uppercased())" } ?? "")
                  + (i.enabled ? "" : "  (disabled)"))
        }
    }
}

// MARK: - AppKit helpers

func nsColor(_ id: String) -> NSColor {
    if id == "grey" { return .systemGray }
    let c = (accentPalette.first { $0.id == id } ?? accentPalette[0]).rgb
    return NSColor(srgbRed: c.0, green: c.1, blue: c.2, alpha: 1)
}

/// Round swatch, used only inside the Rename dialog's color picker.
func swatchImage(_ color: NSColor) -> NSImage {
    let img = NSImage(size: NSSize(width: 10, height: 10), flipped: false) { r in
        color.setFill()
        NSBezierPath(ovalIn: r.insetBy(dx: 0.5, dy: 0.5)).fill()
        return true
    }
    img.isTemplate = false
    return img
}

/// The menu bar symbol: medium weight at menu bar font size, tinted via a palette configuration.
/// If tinting is unavailable (older macOS or a failed configuration) it falls back to a template image.
func barImage(symbol: String, tint: String) -> NSImage? {
    let size = NSFont.menuBarFont(ofSize: 0).pointSize
    let names = [symbol, "sparkles", "star.fill"]   // older macOS may lack "sparkle"
    guard let base = names.lazy.compactMap({ NSImage(systemSymbolName: $0, accessibilityDescription: "Claude profile") }).first
    else { return nil }
    let sized = NSImage.SymbolConfiguration(pointSize: size, weight: .medium)
    if #available(macOS 12.0, *) {
        let cfg = sized.applying(NSImage.SymbolConfiguration(paletteColors: [nsColor(tint)]))
        if let tinted = base.withSymbolConfiguration(cfg) {
            tinted.isTemplate = false
            return tinted
        }
    }
    let plain = base.withSymbolConfiguration(sized) ?? base
    plain.isTemplate = true
    return plain
}

/// Popup/text-field glue for the rename dialog.
final class RenameForm: NSObject {
    let profilePopup = NSPopUpButton(frame: .zero, pullsDown: false)
    let field = NSTextField(frame: .zero)
    let iconPopup = NSPopUpButton(frame: .zero, pullsDown: false)
    let colorPopup = NSPopUpButton(frame: .zero, pullsDown: false)
    let view = NSView(frame: NSRect(x: 0, y: 0, width: 280, height: 122))
    let reals: [String]
    var names: [String: NameEntry]
    var accents: [String: String]

    init(reals: [String], preselect: String, names: [String: NameEntry]) {
        self.reals = reals
        self.names = names
        self.accents = resolveAccents(reals, names)
        super.init()
        for r in reals { profilePopup.addItem(withTitle: "\(r)  (\(displayName(r, names)))") }
        profilePopup.selectItem(at: reals.firstIndex(of: preselect) ?? 0)
        for p in iconPresets { iconPopup.addItem(withTitle: p.emoji.isEmpty ? "No icon" : "\(p.emoji)  \(p.label)") }
        for c in accentPalette {
            colorPopup.addItem(withTitle: c.label)
            colorPopup.lastItem?.image = swatchImage(nsColor(c.id))
        }
        profilePopup.target = self; profilePopup.action = #selector(profileChanged)
        profilePopup.frame = NSRect(x: 0, y: 96, width: 280, height: 26)
        field.frame = NSRect(x: 0, y: 66, width: 280, height: 24)
        iconPopup.frame = NSRect(x: 0, y: 34, width: 280, height: 26)
        colorPopup.frame = NSRect(x: 0, y: 4, width: 280, height: 26)
        [profilePopup, field, iconPopup, colorPopup].forEach { view.addSubview($0) }
        profileChanged()
    }

    var selectedReal: String { reals[max(0, profilePopup.indexOfSelectedItem)] }
    var selectedIcon: String? {
        let e = iconPresets[max(0, iconPopup.indexOfSelectedItem)].emoji
        return e.isEmpty ? nil : e
    }

    var selectedColor: String { accentPalette[max(0, colorPopup.indexOfSelectedItem)].id }

    @objc func profileChanged() {
        let r = selectedReal
        field.stringValue = displayName(r, names)
        let i = iconPresets.firstIndex(where: { $0.emoji == (names[r]?.icon ?? "") }) ?? 0
        iconPopup.selectItem(at: i)
        colorPopup.selectItem(at: accentPalette.firstIndex { $0.id == accents[r] } ?? 0)
    }
}

// MARK: - App

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    let menu = NSMenu()
    var active: String?
    var profiles: [Profile] = []
    var names: [String: NameEntry] = [:]
    var settings = Settings()
    var switching = false          // only touched on the main thread
    var sideBySide = false         // a second window is open (from `claude-switch status`)

    func applicationDidFinishLaunching(_ n: Notification) {
        menu.delegate = self
        menu.autoenablesItems = false
        item.menu = menu
        let loaded = loadNames()
        names = loaded.entries
        settings = loaded.settings
        render()
        refresh()
        Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in self?.refresh() }
    }

    func menuWillOpen(_ menu: NSMenu) { refresh() }

    func refresh() {
        if switching { return }
        DispatchQueue.global().async {
            let s = run(["status"]), l = run(["list"])
            let n = loadNames()
            DispatchQueue.main.async {
                if self.switching { return }
                self.active = s.code == 0 ? parseActive(status: s.out) : nil
                self.sideBySide = s.code == 0 && parseSideBySide(status: s.out)
                self.profiles = l.code == 0 ? parseProfiles(list: l.out) : []
                self.names = n.entries
                self.settings = n.settings
                self.persistAccents(broken: n.broken)
                self.render()
            }
        }
    }

    /// Stores automatically chosen accents next to the display names, once per profile. Skipped while the
    /// file is broken (never replaces it implicitly) and on any write error (colors then stay computed).
    func persistAccents(broken: Bool) {
        guard !broken, !profiles.isEmpty else { return }
        let reals = profiles.map { $0.name }
        let accents = resolveAccents(reals, names)
        var updated = names
        for r in reals where names[r]?.color == nil {
            var e = names[r] ?? NameEntry(name: r, icon: nil)
            e.color = accents[r]
            updated[r] = e
        }
        guard updated != names else { return }
        if (try? saveNames(updated, settings: settings)) != nil { names = updated }
    }

    func render() {
        let accents = resolveAccents(profiles.map { $0.name }, names)
        let label = barLabel(active: active, switching: switching, names: names,
                             showName: settings.showName, accents: accents)
        if let b = item.button {
            b.image = barImage(symbol: label.symbol, tint: label.tint)
            b.imagePosition = label.text.isEmpty ? .imageOnly : .imageLeading
            // Default menu bar font and kerning; only the symbol carries color.
            b.attributedTitle = NSAttributedString(string: label.text, attributes: [.font: NSFont.menuBarFont(ofSize: 0)])
        }
        menu.removeAllItems()
        for spec in buildMenu(active: active, profiles: profiles, switching: switching, names: names,
                              login: loginState(), showName: settings.showName, sideBySide: sideBySide) {
            if spec.action == "sep" { menu.addItem(.separator()); continue }
            let mi = NSMenuItem(title: spec.title, action: #selector(clicked(_:)), keyEquivalent: spec.key ?? "")
            if spec.key != nil { mi.keyEquivalentModifierMask = .command }
            mi.target = self
            mi.representedObject = spec.action
            mi.isEnabled = spec.enabled
            mi.state = spec.checked ? .on : .off
            menu.addItem(mi)
        }
    }

    @objc func clicked(_ sender: NSMenuItem) {
        guard let action = sender.representedObject as? String else { return }
        switch action {
        case "refresh": refresh()
        case "quit": NSApp.terminate(nil)
        case "toggle": startSwitch(["toggle"])
        case "rename": rename()
        case "board": openBoard()
        case "login": toggleLaunchAtLogin()
        case "showname": toggleShowName()
        case "noop": break
        default:
            if action.hasPrefix("use:") {
                let name = String(action.dropFirst(4))
                if validName(name) { startSwitch(["use", name]) }
            } else if action.hasPrefix("sbs:") {
                let name = String(action.dropFirst(4))
                if validName(name) { startSwitch(["side-by-side", name]) }
            } else if action.hasPrefix("sbsclose:") {
                let name = String(action.dropFirst(9))
                if validName(name) { startSwitch(["side-by-side-close", name]) }
            }
        }
    }

    /// Starts the Coshift board page if needed and opens it in the browser. Never touches profiles.
    func openBoard() {
        let script = ProcessInfo.processInfo.environment["COSHIFT_PY"]
            ?? (NSHomeDirectory() + "/.coshift/board.py")
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        p.arguments = [script, "web", "--open"]
        p.terminationHandler = { proc in
            if proc.terminationStatus != 0 {
                notify(title: "Claude Switch Menu", message: "Could not open the Coshift board (\(script))")
            }
        }
        do { try p.run() } catch {
            notify(title: "Claude Switch Menu", message: "Could not open the Coshift board: \(error.localizedDescription)")
        }
    }

    /// Flips the bar between "sparkle + name" and "sparkle only"; only writes the settings file.
    func toggleShowName() {
        guard !switching else { return }
        var next = settings
        next.showName.toggle()
        do {
            try saveNames(names, settings: next)
            settings = next
        } catch SaveError.failed(let why) {
            notify(title: "Claude Switch Menu", message: "Could not save settings: \(why)")
        } catch {}
        render()
    }

    /// Only registers/unregisters the login item; never runs a switch.
    func toggleLaunchAtLogin() {
        if loginState() == .needsApproval {
            SMAppService.openSystemSettingsLoginItems()
            return
        }
        if let err = setLaunchAtLogin(loginState() != .on) {
            notify(title: "Claude Switch Menu", message: "Could not change Launch at Login: \(err)")
        }
        render()
    }

    /// Display-name dialog. Only writes names.json; never calls claude-switch.
    func rename() {
        guard !switching, !profiles.isEmpty else { return }
        let loaded = loadNames()
        var current = loaded.entries
        settings = loaded.settings
        let reals = profiles.map { $0.name }
        let form = RenameForm(reals: reals, preselect: active ?? reals[0], names: current)
        var error: String? = loaded.broken ? "names.json was unreadable; real names are shown. Saving will replace it (the old file is kept aside)." : nil
        NSApp.activate(ignoringOtherApps: true)
        while true {
            let alert = NSAlert()
            alert.messageText = "Rename profile"
            alert.informativeText = (error.map { $0 + "\n\n" } ?? "")
                + "Display name only (1\u{2013}\(maxNameLength) characters). The real profile name and folder don't change."
            alert.accessoryView = form.view
            alert.addButton(withTitle: "Save")
            alert.addButton(withTitle: "Cancel")
            alert.window.initialFirstResponder = form.field
            guard alert.runModal() == .alertFirstButtonReturn else { return }
            let real = form.selectedReal
            var shown: [String: String] = [:]
            for r in reals { shown[r] = displayName(r, current) }
            switch validateDisplayName(form.field.stringValue, for: real, taken: shown) {
            case .failure(let e):
                error = e.message
                form.names = current
                continue
            case .success(let name):
                current[real] = NameEntry(name: name, icon: form.selectedIcon, color: form.selectedColor)
                do {
                    try saveNames(current, settings: settings)
                    names = current
                    render()
                } catch SaveError.failed(let why) {
                    notify(title: "Claude Switch Menu", message: "Could not save names.json: \(why)")
                } catch {}
                return
            }
        }
    }

    func startSwitch(_ args: [String]) {
        guard !switching else { return }   // block a second click
        switching = true
        render()
        DispatchQueue.global().async {
            let r = run(args)
            DispatchQueue.main.async {
                self.switching = false
                if r.code != 0 {
                    let msg = r.out.trimmingCharacters(in: .whitespacesAndNewlines)
                    notify(title: "Claude Switch failed", message: msg.isEmpty ? "exit code \(r.code)" : msg)
                }
                self.refresh()
                self.render()
            }
        }
    }
}

// MARK: - Self-test of names.json handling (uses CLAUDE_SWITCH_MENU_NAMES; no claude-switch calls)

func selfTest() -> Int32 {
    var fails = 0
    func check(_ ok: Bool, _ what: String) { print((ok ? "PASS " : "FAIL ") + what); if !ok { fails += 1 } }
    let path = namesFilePath()
    let taken = ["main": "Work", "second": "second"]
    func isErr(_ r: Result<String, NameError>) -> Bool { if case .failure = r { return true }; return false }
    check(isErr(validateDisplayName("   ", for: "main", taken: taken)), "empty/whitespace rejected")
    check(isErr(validateDisplayName(String(repeating: "x", count: 21), for: "main", taken: taken)), "21 chars rejected")
    check(!isErr(validateDisplayName(String(repeating: "x", count: 20), for: "main", taken: taken)), "20 chars accepted")
    check(isErr(validateDisplayName("work", for: "second", taken: taken)), "duplicate (case-insensitive) rejected")
    check(isErr(validateDisplayName("second", for: "main", taken: taken)), "duplicate of other real name rejected")
    check(!isErr(validateDisplayName("Work", for: "main", taken: taken)), "keeping own name accepted")
    if case .success(let n) = validateDisplayName("  Home  ", for: "main", taken: taken) { check(n == "Home", "trimmed") }
    do {
        try saveNames(["main": NameEntry(name: "Work", icon: "\u{1F4BC}", color: "purple"), "second": NameEntry(name: "Home", icon: nil)],
                      settings: Settings(showName: false))
        let dir = (path as NSString).deletingLastPathComponent
        let dp = (try FileManager.default.attributesOfItem(atPath: dir)[.posixPermissions] as? Int) ?? 0
        let fp = (try FileManager.default.attributesOfItem(atPath: path)[.posixPermissions] as? Int) ?? 0
        check(dp == 0o700, "folder is 700 (got \(String(dp, radix: 8)))")
        check(fp == 0o600, "file is 600 (got \(String(fp, radix: 8)))")
        let back = loadNames()
        check(!back.broken && back.entries["main"] == NameEntry(name: "Work", icon: "\u{1F4BC}", color: "purple")
              && back.entries["second"]?.name == "Home" && back.settings.showName == false, "round trip (name, emoji, color, showName)")
        check(resolveAccents(["main", "second"], [:]) == ["main": "orange", "second": "blue"], "auto accents: orange, blue")
        check(resolveAccents(["a", "b"], ["a": NameEntry(name: "a", icon: nil, color: "orange")]) == ["a": "orange", "b": "blue"], "auto accent skips used")
        check(barLabel(active: "main", switching: true, names: [:]) == BarLabel(symbol: "sparkle", tint: "grey", text: "Switching"), "switching label")
        check(barLabel(active: "main", switching: false, names: [:], showName: false).text.isEmpty, "name hidden -> sparkle only")
        check(barImage(symbol: "sparkle", tint: "orange") != nil, "bar symbol renders")
        try "{ not json".write(toFile: path, atomically: true, encoding: .utf8)
        check(loadNames().broken && loadNames().entries.isEmpty, "broken file -> fallback to real names")
        try saveNames(["main": NameEntry(name: "Again", icon: nil)], settings: Settings())
        let aside = (try FileManager.default.contentsOfDirectory(atPath: dir)).filter { $0.contains(".broken.") }
        check(aside.count == 1 && !loadNames().broken, "broken file moved aside (not deleted), new file valid")
    } catch { check(false, "save/load threw \(error)") }
    return fails == 0 ? 0 : 1
}

/// ClaudeSwitchMenu --render-png out.png: draws the bar label (same inputs as --print-menu, normal and Switching
/// state) on light, dark and wallpaper-like backgrounds so tint and legibility can be checked without a GUI.
func renderPNG(to path: String) {
    let env = ProcessInfo.processInfo.environment
    let active = parseActive(status: env["MOCK_STATUS"] ?? "")
    let loaded = loadNames()
    let reals = parseProfiles(list: env["MOCK_LIST"] ?? "").map { $0.name }
    let accents = resolveAccents(reals, loaded.entries)
    let backgrounds: [(NSColor, NSColor)] = [
        (NSColor(white: 0.95, alpha: 1), .black), (NSColor(white: 0.14, alpha: 1), .white),
        (NSColor(srgbRed: 0.95, green: 0.80, blue: 0.55, alpha: 1), .black), (NSColor(srgbRed: 0.10, green: 0.16, blue: 0.35, alpha: 1), .white),
    ]
    let scale: CGFloat = 3, w: CGFloat = 220, h: CGFloat = 24
    let rows = backgrounds.count * 2
    guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(w * scale), pixelsHigh: Int(h * scale) * rows,
                                     bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                     colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
          let ctx = NSGraphicsContext(bitmapImageRep: rep) else { print("render failed"); return }
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = ctx
    ctx.cgContext.scaleBy(x: scale, y: scale)
    var row = 0
    for switching in [false, true] {
        let l = barLabel(active: active, switching: switching, names: loaded.entries,
                         showName: loaded.settings.showName, accents: accents)
        for (bg, fg) in backgrounds {
            let y = CGFloat(rows - 1 - row) * h
            bg.setFill(); NSRect(x: 0, y: y, width: w, height: h).fill()
            var x: CGFloat = 8
            if let img = barImage(symbol: l.symbol, tint: l.tint) {
                let s = img.size
                if img.isTemplate {   // template fallback: tint by drawing into the foreground color
                    let t = NSImage(size: s, flipped: false) { r in img.draw(in: r); fg.setFill(); r.fill(using: .sourceAtop); return true }
                    t.draw(in: NSRect(x: x, y: y + (h - s.height) / 2, width: s.width, height: s.height))
                } else {
                    img.draw(in: NSRect(x: x, y: y + (h - s.height) / 2, width: s.width, height: s.height))
                }
                x += s.width + 4
            }
            if !l.text.isEmpty {
                let font = NSFont.menuBarFont(ofSize: 0)
                let str = NSAttributedString(string: l.text, attributes: [.font: font, .foregroundColor: fg])
                str.draw(at: NSPoint(x: x, y: y + (h - str.size().height) / 2))
            }
            row += 1
        }
    }
    NSGraphicsContext.restoreGraphicsState()
    if let png = rep.representation(using: .png, properties: [:]) {
        try? png.write(to: URL(fileURLWithPath: path))
        print("wrote \(path)")
    }
}

if let i = CommandLine.arguments.firstIndex(of: "--render-png"), i + 1 < CommandLine.arguments.count {
    renderPNG(to: CommandLine.arguments[i + 1])
} else if CommandLine.arguments.contains("--print-menu") {
    printMenu()
} else if CommandLine.arguments.contains("--selftest") {
    exit(selfTest())
} else {
    // One menu bar item only: quit if another copy (e.g. a second login item) is already running.
    let me = ProcessInfo.processInfo.processIdentifier
    if NSRunningApplication.runningApplications(withBundleIdentifier: "local.claude-switch.menubar")
        .contains(where: { $0.processIdentifier != me }) { exit(0) }
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)
    let d = AppDelegate()
    app.delegate = d
    app.run()
}
