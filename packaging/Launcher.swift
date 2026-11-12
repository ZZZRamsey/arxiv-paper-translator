// Native shell of arXiv Translator: starts the bundled backend and shows its page in a window.
import Cocoa
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var web: WKWebView!
    let backend = Process()
    var buffer = Data()
    var loaded = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 860, height: 900),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "arXiv 论文翻译"
        window.minSize = NSSize(width: 520, height: 520)
        window.setFrameAutosaveName("main")
        if !window.setFrameUsingName("main") { window.center() }
        web = WKWebView(frame: window.contentView!.bounds, configuration: WKWebViewConfiguration())
        web.autoresizingMask = [.width, .height]
        web.navigationDelegate = self
        web.uiDelegate = self
        window.contentView!.addSubview(web)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        show(message: "正在启动…")
        startBackend()
    }

    func startBackend() {
        let resources = Bundle.main.resourceURL!
        let executable = resources.appendingPathComponent("backend/arxiv-translator-backend")
        backend.executableURL = executable
        backend.arguments = ["ui", "--port", "0", "--no-browser", "--exit-with-parent"]
        var environment = ProcessInfo.processInfo.environment
        environment["ARXIV_TRANSLATOR_TOOLS"] = resources.appendingPathComponent("tools").path
        environment["PYTHONUNBUFFERED"] = "1"
        environment["LANG"] = environment["LANG"] ?? "zh_CN.UTF-8"
        backend.environment = environment
        backend.currentDirectoryURL = FileManager.default.homeDirectoryForCurrentUser
        let pipe = Pipe()
        backend.standardOutput = pipe
        backend.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            DispatchQueue.main.async { self?.received(data) }
        }
        backend.terminationHandler = { [weak self] process in
            DispatchQueue.main.async {
                guard let self = self, !self.loaded else { return }
                let output = String(data: self.buffer, encoding: .utf8) ?? ""
                self.show(message: "后台服务没有启动成功（退出码 \(process.terminationStatus)）。\n\n\(output)")
            }
        }
        do { try backend.run() } catch {
            show(message: "无法启动后台服务：\(error.localizedDescription)")
        }
    }

    // The backend prints "界面已启动：http://127.0.0.1:<port>…" once it is listening.
    func received(_ data: Data) {
        guard !loaded else { return }
        buffer.append(data)
        guard let text = String(data: buffer, encoding: .utf8),
              let range = text.range(of: #"http://127\.0\.0\.1:\d+"#, options: .regularExpression),
              let url = URL(string: String(text[range])) else { return }
        loaded = true
        web.load(URLRequest(url: url))
    }

    func show(message: String) {
        let escaped = message.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
        web.loadHTMLString("""
            <meta charset="utf-8"><style>body{font:14px -apple-system;color:#5d6879;background:#f3f5f8;
            display:grid;place-items:center;height:100vh;margin:0;white-space:pre-wrap;padding:40px;box-sizing:border-box}
            @media(prefers-color-scheme:dark){body{background:#11151c;color:#9aa5b6}}</style><div>\(escaped)</div>
            """, baseURL: nil)
    }

    // Links to other sites open in the default browser, never inside the app window.
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let url = action.request.url, let host = url.host, host != "127.0.0.1",
           url.scheme == "http" || url.scheme == "https" {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
        } else {
            decisionHandler(.allow)
        }
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url { NSWorkspace.shared.open(url) }
        return nil
    }

    func buildMenu() {
        let main = NSMenu()
        let app = NSMenuItem(); main.addItem(app)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "关于 arXiv Translator", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "隐藏", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(withTitle: "退出 arXiv Translator", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        app.submenu = appMenu
        let edit = NSMenuItem(); main.addItem(edit)
        let editMenu = NSMenu(title: "编辑")
        editMenu.addItem(withTitle: "撤销", action: Selector(("undo:")), keyEquivalent: "z")
        editMenu.addItem(withTitle: "重做", action: Selector(("redo:")), keyEquivalent: "Z")
        editMenu.addItem(.separator())
        editMenu.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "拷贝", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        edit.submenu = editMenu
        let view = NSMenuItem(); main.addItem(view)
        let viewMenu = NSMenu(title: "显示")
        viewMenu.addItem(withTitle: "重新载入", action: #selector(reload), keyEquivalent: "r")
        view.submenu = viewMenu
        let windowItem = NSMenuItem(); main.addItem(windowItem)
        let windowMenu = NSMenu(title: "窗口")
        windowMenu.addItem(withTitle: "最小化", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "关闭", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        windowItem.submenu = windowMenu
        NSApp.mainMenu = main
        NSApp.windowsMenu = windowMenu
    }

    @objc func reload() { web.reload() }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    // Quitting cancels a running translation, so ask first.
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard loaded else { return .terminateNow }
        web.evaluateJavaScript("typeof running !== 'undefined' && running") { value, _ in
            var quit = true
            if (value as? Bool) == true {
                let alert = NSAlert()
                alert.messageText = "翻译还在进行中"
                alert.informativeText = "现在退出会取消这次翻译。已完成的段落会留在缓存里，下次可以接着翻。"
                alert.addButton(withTitle: "继续翻译")
                alert.addButton(withTitle: "退出")
                quit = alert.runModal() == .alertSecondButtonReturn
            }
            NSApp.reply(toApplicationShouldTerminate: quit)
        }
        return .terminateLater
    }

    func applicationWillTerminate(_ notification: Notification) {
        if backend.isRunning { backend.terminate() }
    }
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
