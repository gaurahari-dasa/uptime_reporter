"""
Display today's system uptime as a floating widget above the taskbar clock,
styled like the battery/volume status indicators.

Usage:
    python uptime_reporter.py                  # widget only
    python uptime_reporter.py --notify 8h      # notify after 8 hours
    python uptime_reporter.py --notify 2h30m   # notify after 2h 30m
    python uptime_reporter.py --notify 45m     # notify after 45 minutes

Dependencies: pip install pystray Pillow pywin32
"""

from __future__ import annotations

import argparse
import datetime
import re
import tkinter as tk
import win32evtlog
import pystray
from PIL import Image, ImageDraw


UPDATE_INTERVAL_MS = 60_000


def parse_threshold(value: str) -> datetime.timedelta:
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?", value.strip())
    if not m or not m.group(0):
        raise argparse.ArgumentTypeError(
            f"Invalid threshold '{value}'. Use formats like 8h, 45m, or 2h30m."
        )
    return datetime.timedelta(hours=int(m.group(1) or 0), minutes=int(m.group(2) or 0))


def get_todays_boot_time() -> datetime.datetime | None:
    handle = win32evtlog.OpenEventLog(None, "System")
    flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
    today = datetime.date.today()
    earliest: datetime.datetime | None = None
    try:
        while True:
            events = win32evtlog.ReadEventLog(handle, flags, 0)
            if not events:
                break
            for event in events:
                dt = event.TimeGenerated.replace(tzinfo=None)
                if dt.date() < today:
                    return earliest
                eid = event.EventID & 0xFFFF
                if (
                    (eid in (1, 12) and event.SourceName == "Microsoft-Windows-Kernel-General")
                    or (eid == 1 and event.SourceName == "Microsoft-Windows-Power-Troubleshooter")
                ):
                    earliest = dt
        return earliest
    finally:
        win32evtlog.CloseEventLog(handle)
    return None


def _make_tray_icon() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, 60, 60), fill=(60, 60, 60, 220))
    draw.text((32, 32), "U", fill="white", anchor="mm")
    return img


class UptimeWidget:
    _BG = "#1e1e2e"
    _FG_HOURS = "#ffffff"
    _FG_MINS = "#94a3b8"
    # _FG_CAPTION = "#475569"
    _FG_CAPTION = "#94a3b8"
    _BORDER = "#334155"
    _ALERT = "#f59e0b"

    def __init__(self, root: tk.Tk, threshold: datetime.timedelta | None):
        self.root = root
        self.threshold = threshold
        self.notified = False
        self._tray: pystray.Icon | None = None
        self._drag_x = self._drag_y = 0

        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.93)
        root.configure(bg=self._BORDER)

        inner = tk.Frame(root, bg=self._BG, padx=6, pady=0)
        inner.pack(padx=1, pady=1)

        # Top row: large hours + smaller minutes side by side
        row = tk.Frame(inner, bg=self._BG)
        row.pack()

        self._lbl_h = tk.Label(
            row, text="--", font=("Segoe UI", 13, "bold"),
            fg=self._FG_HOURS, bg=self._BG,
        )
        self._lbl_h.pack(side=tk.LEFT)

        self._lbl_m = tk.Label(
            row, text="--", font=("Segoe UI", 7),
            fg=self._FG_MINS, bg=self._BG, pady=6,
        )
        self._lbl_m.pack(side=tk.LEFT, anchor=tk.S)

        self._lbl_cap = tk.Label(
            inner, text="Hare Krishna", font=("Segoe UI", 6),
            fg=self._FG_CAPTION, bg=self._BG,
        )
        self._lbl_cap.pack()

        # Drag and right-click on every child widget
        for w in self._all_widgets(root):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<Button-3>", self._show_menu)

        self._menu = tk.Menu(
            root, tearoff=0, bg="#1e1e2e", fg="white",
            activebackground="#334155", activeforeground="white",
        )
        self._menu.add_command(label="Quit", command=self._quit)

        # self._position_near_clock()
        self._position_near_top()
        self.root.after(0, self._tick)

    # ------------------------------------------------------------------
    def _all_widgets(self, parent):
        yield parent
        for child in parent.winfo_children():
            yield from self._all_widgets(child)

    def _position_near_clock(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = self.root.winfo_reqwidth()
        h = self.root.winfo_reqheight()
        self.root.geometry(f"+{sw - w - 180}+{sh - h - 8}")

    def _position_near_top(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = self.root.winfo_reqwidth()
        h = self.root.winfo_reqheight()
        self.root.geometry(f"+{sw - w - 60}+{0}")

    def _drag_start(self, event):
        self._drag_x = event.x_root - self.root.winfo_x()
        self._drag_y = event.y_root - self.root.winfo_y()

    def _drag_move(self, event):
        self.root.geometry(f"+{event.x_root - self._drag_x}+{event.y_root - self._drag_y}")

    def _show_menu(self, event):
        self._menu.tk_popup(event.x_root, event.y_root)

    def _quit(self):
        if self._tray:
            self._tray.stop()
        self.root.destroy()

    def _show_window(self):
        self.root.after(0, self._do_show_window)

    def _do_show_window(self):
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.focus_set()

    def attach_tray(self, icon: pystray.Icon):
        self._tray = icon

    # ------------------------------------------------------------------
    def _tick(self):
        boot_time = get_todays_boot_time()
        if boot_time:
            delta = datetime.datetime.now() - boot_time
            h, rem = divmod(int(delta.total_seconds()), 3600)
            m = rem // 60
            self._lbl_h.config(text=f"{h}h")
            self._lbl_m.config(text=f" {m:02d}m")
            if self._tray:
                self._tray.title = f"Uptime: {h}h {m:02d}m  (booted {boot_time.strftime('%H:%M')})"

            if self.threshold and not self.notified and delta >= self.threshold:
                self._alert()
                self.notified = True
        else:
            self._lbl_h.config(text="N/A")
            self._lbl_m.config(text="")

        self.root.after(UPDATE_INTERVAL_MS, self._tick)

    def _alert(self):
        # Flash the widget amber for a few seconds
        self._lbl_h.config(fg=self._ALERT)
        self._lbl_m.config(fg=self._ALERT)
        self.root.after(5000, lambda: self._lbl_h.config(fg=self._FG_HOURS))
        self.root.after(5000, lambda: self._lbl_m.config(fg=self._FG_MINS))

        if self._tray:
            h, rem = divmod(int(self.threshold.total_seconds()), 3600)
            m = rem // 60
            label = f"{h}h {m}m" if h and m else (f"{h}h" if h else f"{m}m")
            self._tray.notify(
                f"Your system has been running for {label}.",
                "Uptime Reminder",
            )


def main():
    parser = argparse.ArgumentParser(description="System uptime taskbar widget")
    parser.add_argument(
        "--notify", metavar="THRESHOLD", type=parse_threshold, default=None,
        help="Notify when uptime reaches this value (e.g. 8h, 45m, 2h30m)",
    )
    args = parser.parse_args()

    root = tk.Tk()
    widget = UptimeWidget(root, args.notify)

    tray = pystray.Icon(
        name="uptime",
        icon=_make_tray_icon(),
        title="Uptime",
        menu=pystray.Menu(
            pystray.MenuItem("Show Window", lambda *_: widget._show_window()),
            pystray.MenuItem("Quit", lambda *_: widget._quit()),
        ),
    )
    widget.attach_tray(tray)
    tray.run_detached()

    root.mainloop()


if __name__ == "__main__":
    main()
