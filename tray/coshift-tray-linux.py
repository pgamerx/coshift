#!/usr/bin/env python3
"""Coshift tray for Linux. With an AppIndicator-capable desktop (KDE, Cinnamon, XFCE, Ubuntu's GNOME, or GNOME
with the AppIndicator extension) it shows an icon with every account's limits and a menu. Otherwise it runs
quietly and sends desktop notifications (notify-send) when a session needs you or an account hits its stop line.
Started at login by `coshift tray install`. `--once` prints the summary and exits (used by tests)."""
import json, os, shutil, subprocess, sys, time, webbrowser

BOARD = os.environ.get("COSHIFT_PY") or os.path.expanduser("~/.coshift/board.py")


def read():
    try:
        r = subprocess.run([sys.executable, BOARD, "tray-json"], capture_output=True, text=True, timeout=30)
        return json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def account_lines(s):
    out = []
    for a in s["accounts"]:
        pct = lambda v: "?" if v is None else f"{v}%"  # noqa: E731
        out.append((a["name"], f"{a['name']}   5h {pct(a['five_hour_pct'])} · week {pct(a['weekly_pct'])}"
                               + ("  (stopped)" if a["stop"] else "")))
    return out


def notify(title, body):
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "Coshift", title, body], check=False)


def start_claude(name=""):
    cmd = f"coshift run {name}".strip()
    for term, args in (("x-terminal-emulator", ["-e"]), ("gnome-terminal", ["--"]), ("konsole", ["-e"]),
                       ("xfce4-terminal", ["-x"]), ("kitty", []), ("alacritty", ["-e"]), ("xterm", ["-e"])):
        if shutil.which(term):
            subprocess.Popen([term, *args, "sh", "-c", f"{cmd}; exec $SHELL"])
            return
    notify("Coshift", f"No terminal found. Run: {cmd}")


class Watcher:
    """Notifies once per new question and once per account crossing its stop line."""
    def __init__(self):
        self.seen, self.stopped = None, set()

    def check(self, s):
        ids = {n["id"] for n in s["needs"]}
        if self.seen is not None:
            for n in s["needs"]:
                if n["id"] not in self.seen:
                    notify(f"{n['by']} needs you on #{n['id']}", n["q"])
        self.seen = ids
        now_stopped = {a["name"] for a in s["accounts"] if a["stop"]}
        for name in now_stopped - self.stopped:
            notify(f"{name} reached its stop line", "Its sessions hand their work over to another account.")
        self.stopped = now_stopped


def run_indicator():
    import gi
    gi.require_version("Gtk", "3.0")
    try:
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3 as AI
    except (ValueError, ImportError):
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3 as AI
    from gi.repository import GLib, Gtk

    ind = AI.Indicator.new("coshift", "user-available", AI.IndicatorCategory.APPLICATION_STATUS)
    ind.set_status(AI.IndicatorStatus.ACTIVE)
    watcher = Watcher()

    def item(menu, label, cb=None, sensitive=True):
        mi = Gtk.MenuItem(label=label)
        mi.set_sensitive(sensitive)
        if cb:
            mi.connect("activate", lambda *_: cb())
        menu.append(mi)

    def refresh():
        s, menu = read(), Gtk.Menu()
        if not s:
            item(menu, "Coshift isn't set up yet: run coshift setup", sensitive=False)
        else:
            watcher.check(s)
            for name, line in account_lines(s):
                item(menu, line, lambda n=name: start_claude(n))
            if s["needs"]:
                n = s["needs"][0]
                item(menu, f"! {len(s['needs'])} need you: #{n['id']} {n['title']}", lambda: webbrowser.open(s["url"]))
            menu.append(Gtk.SeparatorMenuItem())
            item(menu, "Start Claude Code (most limit left)", start_claude)
            item(menu, "Open Coshift board", lambda: webbrowser.open(s["url"]))
            ind.set_label(f" {len(s['needs'])} need you" if s["needs"] else "", "")
        menu.append(Gtk.SeparatorMenuItem())
        item(menu, "Quit", Gtk.main_quit)
        menu.show_all()
        ind.set_menu(menu)
        return True

    refresh()
    GLib.timeout_add_seconds(60, refresh)
    Gtk.main()


def run_notifications():
    watcher = Watcher()
    while True:
        s = read()
        if s:
            watcher.check(s)
        time.sleep(60)


def main():
    if "--once" in sys.argv:
        s = read()
        if not s:
            print("Coshift isn't set up yet: run coshift setup")
            return 1
        for _, line in account_lines(s):
            print(line)
        print(f"{len(s['needs'])} need you · {s['claimed']} in progress · {s['open']} queued · {s['url']}")
        return 0
    try:
        run_indicator()
    except (ImportError, ValueError) as e:  # no AppIndicator on this desktop: notifications only
        print(f"No tray support ({e}); sending desktop notifications instead.", file=sys.stderr)
        run_notifications()
    return 0


if __name__ == "__main__":
    sys.exit(main())
